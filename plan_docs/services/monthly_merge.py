"""Three-way cell merge against server-owned immutable document revisions."""
import base64
import hashlib
import hmac
import json
import os
from copy import deepcopy

from fastapi import HTTPException

from ..db_models import PlanRevisionRow


def signature(encoded):
    key = os.getenv("HOIKUICT_SECRET_KEY")
    if not key:
        raise HTTPException(503, "月案の保存設定が利用できません。管理者に連絡してください")
    return hmac.new(key.encode(), ("monthly-base-v1:" + encoded).encode(), hashlib.sha256).hexdigest()


def scope(user, classroom_id, target_month, age):
    return [user.nursery_ref, str(user.user_id), user.actor_ref, classroom_id, target_month, age]


def baseline_token(user, repository, context):
    document_id = context["document_id"]
    head = repository.head(document_id) if document_id else None
    data = {"scope": scope(user, context["classroom_id"], context["target_month"], context["age"]),
            "document_id": document_id, "revision_id": head.current_revision_id if head else None,
            "owner": context["owner_name"] if document_id is None else None}
    encoded = base64.urlsafe_b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
    return encoded + "." + signature(encoded)


def read_baseline(payload, user, repository):
    try:
        encoded, signed = payload.base_token.rsplit(".", 1)
        if not hmac.compare_digest(signed, signature(encoded)):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(encoded))
        if (data["scope"] != scope(user, payload.classroom_id, payload.target_month, payload.age)
                or data["document_id"] != payload.document_id):
            raise ValueError
        if data["document_id"] is None:
            if data["revision_id"] is not None:
                raise ValueError
            return {"fields": {}, "owner": data["owner"]}
        revision = repository.session.get(PlanRevisionRow, data["revision_id"])
        if revision is None or revision.document_id != data["document_id"]:
            raise ValueError
        snapshot = revision.snapshot
        sheet = snapshot["monthly_sheet"]
        if (snapshot["nursery_ref"] != user.nursery_ref or sheet["classroom_id"] != payload.classroom_id
                or snapshot["target_month"] != payload.target_month or sheet["age"] != payload.age):
            raise ValueError
        return {"fields": sheet["fields"], "owner": snapshot["owner_name"]}
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise HTTPException(409, "保存の基準を確認できません。入力を保持したまま、別画面で最新版を確認してください") from exc


def wire_cell(cell):
    cell = cell or {}
    return {"body": cell.get("body", ""), "origins": [
        {"kind": "ai", "token": o["token"]} if o.get("kind") == "ai"
        else {"source_key": o["source_key"], "phrase_id": o["phrase_id"]}
        for o in cell.get("origins", [])]}


def merge_cells(base, mine, latest):
    keys = set(base["fields"]) | set(mine["fields"]) | set(latest["fields"]) | {"@owner"}
    def value(record, key):
        return record["owner"] if key == "@owner" else wire_cell(record["fields"].get(key))
    changed = {key for key in keys if value(mine, key) != value(base, key)}
    remote = {key for key in keys if value(latest, key) != value(base, key)}
    conflicts = sorted(key for key in changed & remote if value(mine, key) != value(latest, key))
    merged = deepcopy(latest)
    for key in changed:
        if key == "@owner":
            merged["owner"] = mine["owner"]
        elif key in mine["fields"]:
            merged["fields"][key] = mine["fields"][key]
        else:
            merged["fields"].pop(key, None)
    return merged, conflicts, sorted(remote - changed)
