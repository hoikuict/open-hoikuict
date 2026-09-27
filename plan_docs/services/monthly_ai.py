"""Explicit local Ollama generation, with signed and scope-bound provenance."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

_generation_slot = threading.BoundedSemaphore(1)
PROMPT_VERSION = "monthly-conditions-v1"


class GenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classroom_id: int = Field(gt=0)
    target_month: str
    age: int = Field(ge=0, le=5)
    field: str = Field(max_length=100)
    document_id: int | None = Field(default=None, gt=0)


def config(nursery_ref: str) -> dict:
    try:
        value = json.loads(os.getenv("HOIKU_MONTHLY_OLLAMA_SOURCES", "{}"))[nursery_ref]
        url, model = value["url"].rstrip("/"), value["model"]
        parsed = urlsplit(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not isinstance(model, str) or not 1 <= len(model) <= 100
                or not os.getenv("HOIKUICT_SECRET_KEY")):
            raise ValueError
        return {"url": url, "model": model}
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise HTTPException(503, "この園のAI提案は未接続です") from exc


def availability(nursery_ref: str) -> dict:
    try:
        return {"enabled": True, "model": config(nursery_ref)["model"]}
    except HTTPException:
        return {"enabled": False}


def _signature(encoded: str) -> str:
    key = os.getenv("HOIKUICT_SECRET_KEY")
    if not key:
        raise HTTPException(503, "AI提案の保存設定が利用できません")
    return hmac.new(key.encode(), ("monthly-ai-v1:" + encoded).encode(), hashlib.sha256).hexdigest()


def _scope(nursery_ref: str, payload) -> list:
    return [nursery_ref, payload.classroom_id, payload.target_month, payload.age, payload.field]


def resolve_origin(token: str, nursery_ref: str, classroom_id: int, target_month: str,
                   age: int, field: str) -> dict:
    try:
        encoded, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(_signature(encoded), signature):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(encoded))
        if data["scope"] != [nursery_ref, classroom_id, target_month, age, field]:
            raise ValueError
        return {**data["origin"], "token": token}
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "AI提案の生成情報または対象欄を確認できません") from exc


def generate(nursery_ref: str, payload: GenerateInput, definition: dict) -> dict:
    settings = config(nursery_ref)
    if not _generation_slot.acquire(blocking=False):
        raise HTTPException(429, "AIが別の候補を生成中です。少し待ってから再試行してください")
    try:
        return _generate(settings, nursery_ref, payload, definition)
    finally:
        _generation_slot.release()


def _generate(settings, nursery_ref, payload, definition):
    # Do not include names, class identifiers, entered text, keywords, history or
    # the phrase corpus. Only canonical field metadata is sent to the model.
    conditions = {"年齢クラス": f"{payload.age}歳児", "対象月": int(payload.target_month[-2:]),
                  "区分": definition["section"], "入力欄": definition["label"],
                  "領域": definition["ryoiki"]}
    system = (
        "あなたは保育園の月案作成を補助します。指定された欄に合う日本語の短い文例を2件提案してください。"
        "年齢に合った具体的な計画とし、実際に観察した事実や園児の名前を創作しないでください。"
        "計画欄は『用意する』『整える』『楽しむ』などの常体で書き、実績や現状を断定しないでください。"
        "評価・反省の欄では実施済みの成果を創作せず、振り返るための観点を『〜を振り返る』と書いてください。"
        "参考原文は渡されていないので、原文や出典を主張しないでください。"
        "candidatesという文字列配列だけを持つJSONで回答してください。"
    )
    schema = {"type": "object", "properties": {"candidates": {
        "type": "array", "minItems": 2, "maxItems": 2,
        "items": {"type": "string", "minLength": 1, "maxLength": 300}}},
        "required": ["candidates"], "additionalProperties": False}
    try:
        with httpx.Client(timeout=httpx.Timeout(150, connect=5), trust_env=False,
                          follow_redirects=False) as client:
            metadata = client.post(settings["url"] + "/api/show", json={"model": settings["model"]})
            metadata.raise_for_status()
            local = metadata.json()
            if (local.get("remote_host") or local.get("remote_model")
                    or local.get("details", {}).get("format") != "gguf"):
                raise HTTPException(503, "実機に保存されたローカルモデルを設定してください")
            response = client.post(settings["url"] + "/api/chat", json={
                "model": settings["model"], "stream": False, "think": False,
                "keep_alive": "5m", "format": schema,
                "options": {"temperature": 0.2, "num_predict": 600, "num_ctx": 4096},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": json.dumps(conditions, ensure_ascii=False)}]})
            response.raise_for_status()
            result = response.json()
        content = json.loads(result["message"]["content"])
        texts = content["candidates"]
        if (result.get("done") is not True or result.get("done_reason") == "length"
                or not isinstance(texts, list) or len(texts) != 2
                or any(not isinstance(text, str) or not 1 <= len(text.strip()) <= 300 for text in texts)
                or len({text.strip() for text in texts}) != 2):
            raise ValueError
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "AI生成が時間切れになりました。入力内容は保持されています。しばらくして再試行してください") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "実機のAIに接続できません。入力内容は保持されています") from exc
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(502, "AIから候補を読み取れませんでした。再生成してください") from exc
    generation_id, created_at = uuid4().hex, datetime.now(timezone.utc).isoformat()
    items = []
    for index, text in enumerate(texts):
        origin = {"kind": "ai", "candidate_id": f"{generation_id}:{index}",
                  "generation_id": generation_id, "model": settings["model"],
                  "created_at": created_at, "text": text.strip(),
                  "prompt_version": PROMPT_VERSION, "reference_mode": "conditions_only",
                  "age": payload.age, "month": int(payload.target_month[-2:]),
                  "section": definition["section"], "item": definition["item"],
                  "ryoiki": definition["ryoiki"]}
        encoded = base64.urlsafe_b64encode(json.dumps({"scope": _scope(nursery_ref, payload),
            "origin": origin}, ensure_ascii=False, separators=(",", ":")).encode()).decode()
        items.append({**origin, "token": encoded + "." + _signature(encoded)})
    return {"items": items, "has_more": False}
