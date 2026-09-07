"""Consistent import snapshots and audit metadata without personal values."""
import hashlib
import json

from sqlalchemy import select

from models import Child, Classroom, Family, Guardian, ParentAccount, ParentChildLink, User


TABLES = (Family, Child, Guardian, ParentAccount, ParentChildLink, Classroom, User)


def ledger_state(session):
    state = {}
    for model in TABLES:
        table = model.__table__
        # Authentication activity must not invalidate an unrelated ledger preview.
        rows = session.execute(select(table)).mappings().all()
        state[table.name] = {
            str(row["id"]): {key: value for key, value in row.items() if key != "last_login_at"}
            for row in rows
        }
    return state


def state_revision(state):
    content = json.dumps(state, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def audit_changes(before, after):
    changes = []
    for table in after:
        for item_id, row in after[table].items():
            previous = before[table].get(item_id, {})
            fields = sorted(key for key in row if row[key] != previous.get(key) and key not in {"created_at", "updated_at"})
            if fields:
                changes.append({"table": table, "id": item_id, "fields": fields})
        for item_id in before[table].keys() - after[table].keys():
            changes.append({"table": table, "id": item_id, "fields": ["deleted"]})
    return changes
