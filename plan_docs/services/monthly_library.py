"""Versioned monthly sheets and a nursery-scoped, read-only phrase adapter."""
from __future__ import annotations

import calendar
import json
import os
import re
import sqlite3
import unicodedata
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import select

from models import Child, Classroom

PERSONAL = [("life", "生活・健康"), ("play", "あそび"),
            ("help", "環境構成・援助活動"), ("review", "評価・反省")]
COLUMNS = [("goal", "ねらい"), ("environment", "環境設定"),
           ("expected", "予想される子どもの姿"), ("support", "配慮事項")]
DOMAINS = [("care", "生命・情緒"), ("health", "健康"), ("relations", "人間関係"),
           ("nature", "環境"), ("language", "言葉"), ("expression", "表現")]
TEMPLATES = [
    ("infant-0", "原案 月案（0歳児).xls", "1ynTjwavMis4xHihKq0phLq8rgqcsn49s"),
    ("infant-1", "新 月案（1歳児）.xls", "1DGbgBkene3rOun0SS12OJmT3SxR_AKDt"),
    ("infant-2", "月案（２歳児） 新.xls", "1V5isie1zxemNMbmW-1BkNul-JCbeeKFe"),
    ("group-3plus", "月案原本（幼児）.xls", "1tsMSt2gVgkM72EOmm2ms0tBpwVIIxLkn"),
]
TEMPLATE_VERSION = "2026-09-27.1"


class OriginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phrase_id: int = Field(gt=0)
    source_key: str = Field(min_length=1, max_length=100)


class AIOriginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["ai"]
    token: str = Field(min_length=1, max_length=16000)


class CellInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(default="", max_length=20000)
    origins: list[OriginInput | AIOriginInput] = Field(default_factory=list, max_length=100)


class SaveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: int | None = Field(default=None, gt=0)
    lock_version: int = Field(default=0, ge=0)
    classroom_id: int = Field(gt=0)
    target_month: str
    age: int = Field(ge=0, le=5)
    owner_name: str = Field(min_length=1, max_length=100)
    fields: dict[str, CellInput]


def month_date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise HTTPException(422, "対象月をYYYY-MMで指定してください")
    try:
        result = date.fromisoformat(value + "-01")
    except ValueError as exc:
        raise HTTPException(422, "対象月が不正です") from exc
    if not 1900 <= result.year <= 2199:
        raise HTTPException(422, "対象年は1900〜2199年で指定してください")
    return result


def previous_months(value: str) -> list[str]:
    target = month_date(value)
    index = target.year * 12 + target.month - 1
    return [f"{(index - n) // 12:04d}-{(index - n) % 12 + 1:02d}" for n in (3, 2, 1)]


def new_sheet(session, classroom: Classroom, target_month: str, age: int) -> dict:
    target = month_date(target_month)
    end = date(target.year, target.month, calendar.monthrange(target.year, target.month)[1])
    children = session.exec(select(Child).where(
        Child.classroom_id == classroom.id, Child.enrollment_date <= end,
        (Child.withdrawal_date.is_(None) | (Child.withdrawal_date >= target)),
    ).order_by(Child.last_name_kana, Child.first_name_kana, Child.id)).all() if age < 3 else []
    return {
        "schema_version": 1, "template_id": TEMPLATES[min(age, 3)][0],
        "template_version": TEMPLATE_VERSION, "classroom_id": classroom.id, "age": age,
        "children": [{"ref": f"child:{child.id}", "name": child.full_name,
                      "birth_date": child.birth_date.isoformat()} for child in children],
        "fields": {},
    }


def field_definitions(sheet: dict, target_month: str) -> dict[str, dict]:
    """Stable field IDs are independent of labels and roster positions."""
    result = {}

    def add(key, label, section=None, item=None, ryoiki=None):
        result[key] = {"label": label, "section": section, "item": item, "ryoiki": ryoiki}

    add("common:goal", "ねらい" if sheet["age"] < 3 else "今月のねらい", "クラス全体", "ねらい")
    add("common:home", "家庭との連携", "クラス全体", "家庭との連携")
    add("common:review", "評価・反省", "クラス全体", "評価・反省")
    if sheet["age"] < 3:
        add("common:events", "行事")
        for child in sheet["children"]:
            for key, label in PERSONAL:
                add(f"{child['ref']}:{key}", label, "個人別",
                    "環境構成・援助" if key == "help" else label)
    else:
        items = ["ねらい", "環境構成", "予想される子どもの姿", "援助・配慮"]
        for domain, label in DOMAINS:
            for (column, title), item in zip(COLUMNS, items):
                add(f"group:{domain}:{column}", f"{label} / {title}",
                    "養護" if domain == "care" else "教育", item, label)
        add("group:food", "食育", "食育", "食育")
        target = month_date(target_month)
        for day in range(1, calendar.monthrange(target.year, target.month)[1] + 1):
            add(f"event:{day}", f"{day}日 行事・活動")
    return result


def source_config(nursery_ref: str) -> tuple[str, Path]:
    # Explicit per-nursery binding. Never use an arbitrary browser-supplied path.
    try:
        config = json.loads(os.getenv("HOIKU_MONTHLY_LIBRARY_SOURCES", "{}"))[nursery_ref]
        key, path = config["id"], Path(config["path"]).expanduser().resolve()
        if not isinstance(key, str) or not 1 <= len(key) <= 100 or not path.is_file():
            raise ValueError
        return key, path
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise HTTPException(503, "この園の文例データソースが未設定、または利用できません") from exc


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold()


def _filter(definition: dict, age: int, month: int) -> tuple[list[str], list]:
    clauses, params = ["p.age = ?", "p.month = ?"], [age, month]
    if definition["section"] == "食育":
        clauses.append("(p.section = '食育' OR p.item = '食育')")
    else:
        clauses.extend(["p.section = ?", "p.item = ?"])
        params.extend([definition["section"], definition["item"]])
        if definition["ryoiki"]:
            if definition["section"] == "養護":
                clauses.append("p.ryoiki IN ('生命・情緒', '生命の保持', '情緒の安定')")
            else:
                clauses.append("p.ryoiki = ?")
                params.append(definition["ryoiki"])
    return clauses, params


def search_phrases(nursery_ref: str, definition: dict, age: int, month: int,
                   keyword: str = "", offset: int = 0, phrase_ids: list[int] | None = None) -> dict:
    if not definition["section"]:
        return {"items": [], "has_more": False}
    source_key, path = source_config(nursery_ref)
    clauses, params = _filter(definition, age, month)
    # Facets bound the scan. NFKC substring matching also handles 1/2-character
    # terms and full-width text which cannot safely be excluded by trigram FTS.
    for term in normalize(keyword).split():
        clauses.append("instr(normalize(p.text), ?) > 0")
        params.append(term)
    if phrase_ids is not None:
        if not phrase_ids:
            return {"items": [], "has_more": False}
        clauses.append(f"p.id IN ({','.join('?' for _ in phrase_ids)})")
        params.extend(phrase_ids)
    partition = "p.id" if phrase_ids is not None else "normalize(p.text)"
    sql = f"""WITH ranked AS (
        SELECT p.*, row_number() OVER (PARTITION BY {partition}
            ORDER BY p.year DESC, p.id DESC) AS rank
        FROM phrase p WHERE {' AND '.join(clauses)}
    ) SELECT p.id, p.text, p.year, p.item, p.section, p.ryoiki,
        p.cell_id, p.source_id, s.rel_path, c.sheet
        FROM ranked p JOIN source s ON s.id = p.source_id JOIN cell c ON c.id = p.cell_id
        WHERE p.rank = 1 ORDER BY p.year DESC, p.id DESC LIMIT ? OFFSET ?"""
    params.extend([len(phrase_ids) if phrase_ids is not None else 51, offset])
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)) as con:
            con.execute("PRAGMA query_only=ON")
            con.create_function("normalize", 1, normalize, deterministic=True)
            con.row_factory = sqlite3.Row
            rows = con.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(503, "文例データを読み込めません。入力内容は保持されています") from exc
    items = [{"phrase_id": row["id"], "source_key": source_key, "kind": "original",
              "text": row["text"], "year": row["year"], "age": age, "month": month,
              "item": row["item"], "section": row["section"], "ryoiki": row["ryoiki"],
              "cell_id": row["cell_id"], "source_id": row["source_id"],
              "relative_path": row["rel_path"], "sheet": row["sheet"]} for row in rows]
    return {"items": items if phrase_ids is not None else items[:50],
            "has_more": phrase_ids is None and len(items) > 50}


def validated_fields(payload: SaveInput, sheet: dict, nursery_ref: str) -> dict:
    definitions = field_definitions(sheet, payload.target_month)
    if set(payload.fields) - definitions.keys():
        raise HTTPException(422, "帳票に存在しない欄または園児が指定されています")
    if sum(len(cell.body) for cell in payload.fields.values()) > 500000:
        raise HTTPException(422, "本文が保存可能な容量を超えています")
    result = {}
    for key, cell in payload.fields.items():
        if not cell.body and not cell.origins:
            continue
        saved_origins = sheet["fields"].get(key, {}).get("origins", [])
        existing = {(o["source_key"], o["phrase_id"]): o
                    for o in saved_origins if o.get("kind") != "ai"}
        existing_ai = {o["token"]: o for o in saved_origins if o.get("kind") == "ai"}
        new = [o for o in cell.origins if isinstance(o, OriginInput)
               and (o.source_key, o.phrase_id) not in existing]
        if new:
            found = search_phrases(nursery_ref, definitions[key], payload.age,
                                   month_date(payload.target_month).month,
                                   phrase_ids=[o.phrase_id for o in new])["items"]
            existing.update({(o["source_key"], o["phrase_id"]): o for o in found})
        origins = []
        for origin in cell.origins:
            if isinstance(origin, AIOriginInput):
                from .monthly_ai import resolve_origin
                resolved = existing_ai.get(origin.token)
                if resolved is None:
                    resolved = resolve_origin(origin.token, nursery_ref, payload.classroom_id,
                                              payload.target_month, payload.age, key)
            else:
                resolved = existing.get((origin.source_key, origin.phrase_id))
            if resolved is None:
                raise HTTPException(422, "選択した文例の出典または対象欄を確認できません")
            if resolved not in origins:
                origins.append(resolved)
        result[key] = {"body": cell.body, "origins": origins}
    return result
