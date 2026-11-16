"""Cell merge behavior for the disposable local mock only."""
from collections import OrderedDict
from copy import deepcopy
from secrets import token_urlsafe
from threading import RLock

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from plan_docs.auth_adapter import StaffUser
from plan_docs.routers import monthly_library as monthly
from plan_docs.services.monthly_library import SaveInput, validated_fields
from plan_docs.store import SqlModelDocumentRepository


def wire_cell(value):
    value = value or {}
    origins = []
    for origin in value.get("origins", []):
        origins.append({"kind": "ai", "token": origin["token"]} if origin.get("kind") == "ai"
            else {"source_key": origin["source_key"], "phrase_id": origin["phrase_id"]})
    return {"body": value.get("body", ""), "origins": origins}


def values(context):
    return {key: wire_cell(value) for key, value in context["sheet"]["fields"].items()} | {"@owner": context["owner_name"]}


def field_label(context, key):
    if key == "@owner":
        return "担任名"
    ref = ":".join(key.split(":")[:2]) if key.startswith("child:") else None
    name = next((child["name"] for child in context["sheet"]["children"] if child["ref"] == ref), context["classroom_name"])
    return f"{name} / {context['definitions'].get(key, {}).get('label', key)}"


class CellSaveInput(SaveInput):
    base_token: str = Field(min_length=1, max_length=100)


class PeerSaveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_token: str = Field(min_length=1, max_length=100)
    field: str = Field(min_length=1, max_length=100)
    body: str = Field(max_length=20000)


class CellMergePreview:
    def __init__(self, preview, actors):
        self.preview = preview
        self.actors = actors
        self.bases = OrderedDict()
        self.lock = RLock()

    def issue(self, user, context):
        token = token_urlsafe(24)
        with self.lock:
            self.bases[token] = (user.actor_ref, user.nursery_ref, deepcopy(context))
            while len(self.bases) > 2000:
                self.bases.popitem(last=False)
        return token

    def baseline(self, token, user):
        saved = self.bases.get(token)
        if saved is None or saved[:2] != (user.actor_ref, user.nursery_ref):
            raise HTTPException(409, "見本の保存元を確認できません。入力を控えてから画面を開き直してください。")
        return deepcopy(saved[2])

    def save(self, payload, request, user, repository):
        base = self.baseline(payload.base_token, user)
        for key in ("classroom_id", "target_month", "age", "document_id"):
            if getattr(payload, key) != base[key]:
                raise HTTPException(409, "保存元の月案と対象が一致しません。入力は保持されています。")
        latest = self.preview.context(user, repository, payload.classroom_id, payload.target_month, payload.age)
        if not latest["editable"]:
            raise HTTPException(403, latest["preview_permission"])
        if base["document_id"] and latest["document_id"] != base["document_id"]:
            raise HTTPException(409, "月案が置き換わっています。入力は保持されています。")
        submitted = deepcopy(base)
        submitted["owner_name"] = payload.owner_name
        submitted["sheet"]["fields"] = validated_fields(payload, latest["sheet"], user.nursery_ref)
        original, theirs, ours = values(base), values(latest), values(submitted)
        keys = original.keys() | theirs.keys() | ours.keys()
        empty = {"body": "", "origins": []}
        mine = {key for key in keys if ours.get(key, empty) != original.get(key, empty)}
        remote = {key for key in keys if theirs.get(key, empty) != original.get(key, empty)}
        conflicts = sorted(key for key in mine & remote if ours.get(key, empty) != theirs.get(key, empty))
        if conflicts:
            return JSONResponse({"detail": {"kind": "cell_conflict", "latest": latest,
                "conflicts": [{"key": key, "label": field_label(latest, key)} for key in conflicts]}}, status_code=409)
        merged = dict(theirs)
        for key in mine:
            merged[key] = ours.get(key, empty)
        if mine or latest["document_id"] is None:
            write = SaveInput(document_id=latest["document_id"], lock_version=latest["lock_version"],
                classroom_id=payload.classroom_id, target_month=payload.target_month, age=payload.age,
                owner_name=merged.pop("@owner"), fields=merged)
            latest = monthly.save(write, request, user, repository)
        latest["merged_remote_fields"] = [field_label(latest, key) for key in sorted(remote - mine)]
        return latest

    def install(self, app):
        @app.post("/preview/cell-save")
        def cell_save(payload: CellSaveInput, request: Request):
            with self.lock, Session(self.preview.fixture.engine) as session:
                return self.save(payload, request, self.preview.user(request), SqlModelDocumentRepository(session))

        @app.post("/preview/cell-peer")
        def peer_save(payload: PeerSaveInput, request: Request):
            with self.lock, Session(self.preview.fixture.engine) as session:
                user = self.preview.user(request)
                base = self.baseline(payload.base_token, user)
                repository = SqlModelDocumentRepository(session)
                current = self.preview.context(user, repository, base["classroom_id"], base["target_month"], base["age"])
                if not current["editable"]:
                    raise HTTPException(403, current["preview_permission"])
                for actor, (name, role, _) in self.actors.items():
                    if actor == user.staff_id:
                        continue
                    peer = StaffUser(role=role, actor_ref=f"staff:{actor}", nursery_ref=user.nursery_ref,
                        classroom_refs=("A組", "B組"), name=name)
                    target = self.preview.context(peer, repository, base["classroom_id"], base["target_month"], base["age"])
                    if target["editable"]:
                        break
                else:
                    raise HTTPException(409, "この対象月には、保存を試せる別の担当者がいません。")
                fields = {key: wire_cell(value) for key, value in target["sheet"]["fields"].items()}
                owner = target["owner_name"]
                if payload.field == "@owner":
                    owner = payload.body
                elif payload.field in target["definitions"]:
                    fields[payload.field] = {"body": payload.body, "origins": []}
                else:
                    raise HTTPException(422, "帳票にない欄です。")
                monthly.save(SaveInput(**{key: target[key] for key in
                    ("document_id", "lock_version", "classroom_id", "target_month", "age")},
                    owner_name=owner, fields=fields), request, peer, repository)
                return {"name": name.split("（")[0], "field_label": field_label(target, payload.field)}
