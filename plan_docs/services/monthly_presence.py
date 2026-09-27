"""Short-lived presence shared by workers in the production application container.

Stored outside the business database, in a private temporary directory. No body
text, tokens or names are persisted; names and assignments are resolved afresh.
Presence is advisory, while revision-based saves enforce concurrency separately.
"""
import hashlib
import json
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from models import User
from ..auth_adapter import StaffUser
from ..contracts import Role
from .monthly_access import can_edit_monthly

TTL = 60


class PresenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classroom_id: int = Field(gt=0)
    target_month: str
    age: int = Field(ge=0, le=5)
    document_id: int | None = Field(default=None, gt=0)
    tab_id: UUID
    field: str | None = Field(default=None, max_length=100)
    state: Literal["open", "selected", "typing", "leave"] = "open"


def cache_path(session):
    identity = str(session.get_bind().url)
    directory = Path(tempfile.gettempdir()) / ("hoikuict-monthly-presence-" + hashlib.sha256(identity.encode()).hexdigest()[:20])
    directory.mkdir(mode=0o700, exist_ok=True)
    return directory / "presence.sqlite"


def heartbeat(session, user, payload, context):
    if payload.field and payload.field != "@owner" and payload.field not in context["definitions"]:
        raise HTTPException(422, "編集中の欄を確認できません")
    scope = json.dumps([user.nursery_ref, payload.classroom_id, payload.target_month, payload.age])
    now = time.time()
    actor, tab = str(user.user_id), str(payload.tab_id)
    with closing(sqlite3.connect(cache_path(session), timeout=3)) as con, con:
        con.execute("CREATE TABLE IF NOT EXISTS presence (scope TEXT, actor TEXT, tab TEXT, field TEXT, state TEXT, seen REAL, PRIMARY KEY (scope, actor, tab))")
        con.execute("DELETE FROM presence WHERE seen < ?", (now - TTL,))
        if context["editable"] and payload.state != "leave":
            con.execute("INSERT INTO presence VALUES (?,?,?,?,?,?) ON CONFLICT(scope,actor,tab) DO UPDATE SET field=excluded.field,state=excluded.state,seen=excluded.seen",
                        (scope, actor, tab, payload.field, payload.state, now))
        else:
            con.execute("DELETE FROM presence WHERE scope=? AND actor=? AND tab=?", (scope, actor, tab))
        rows = con.execute("SELECT actor,tab,field,state FROM presence WHERE scope=? AND NOT (actor=? AND tab=?) ORDER BY actor,tab", (scope, actor, tab)).fetchall()
    peers = {}
    # An approved/reviewing sheet cannot have active body editors.
    if context["status"] not in {"未保存", "下書き", "差戻し"}:
        return {"peers": [], "ttl_seconds": TTL, "editable": context["editable"], "edit_reason": context["edit_reason"]}
    for actor_id, tab_id, field, state in rows:
        staff = session.get(User, UUID(actor_id), populate_existing=True)
        if not staff or not staff.is_active or staff.staff_role not in {"can_edit", "admin"}:
            continue
        peer = StaffUser(role=Role(staff.staff_role), user_id=staff.id,
                         actor_ref="staff:" + str(staff.id), nursery_ref=user.nursery_ref,
                         classroom_refs=(), name=staff.display_name)
        if not can_edit_monthly(session, peer, payload.classroom_id, payload.target_month):
            continue
        if field and field != "@owner" and field not in context["definitions"]:
            continue
        item = peers.setdefault(actor_id, {"name": staff.display_name, "self": actor_id == actor, "fields": []})
        entry = {"key": field, "state": state}
        if entry not in item["fields"]:
            item["fields"].append(entry)
    return {"peers": list(peers.values()), "ttl_seconds": TTL,
            "editable": context["editable"], "edit_reason": context["edit_reason"]}
