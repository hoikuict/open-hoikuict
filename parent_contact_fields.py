"""Facility-local contact visibility and immutable per-contact field snapshots."""
from copy import deepcopy
from datetime import date
from hashlib import sha256
import json

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from models import Classroom, ParentContactFieldSetting, ParentContactFieldAudit
from time_utils import utc_now

GROUPS = {
    "temperature": ("体温", ("temperature",)),
    "sleep": ("睡眠", ("bedtime", "wakeup_time", "sleep_notes")),
    "dinner": ("夕食", ("dinner_appetite", "dinner_contents")),
    "breakfast": ("朝食", ("breakfast_appetite", "breakfast_contents", "breakfast_status")),
    "stool": ("排便", ("stool_consistency", "stool_count", "bowel_movement_status")),
    "mood": ("機嫌", ("mood",)),
    "cough": ("咳", ("cough",)),
    "runny_nose": ("鼻水", ("runny_nose",)),
    "medication": ("服薬", ("medication",)),
    "condition": ("体調メモ", ("condition_note",)),
}
SNAPSHOT_KEY = "parent_contact_fields"


def all_fields():
    return dict.fromkeys(GROUPS, True)


def classrooms(session):
    return session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()


def default_policy():
    return {"mode": "age", "age": {str(i): all_fields() for i in range(6)}, "class": {}, "class_versions": {}}


def room_revision(rooms):
    return sha256(json.dumps([(room.id, room.created_at.isoformat()) for room in rooms]).encode()).hexdigest()


def policy_for_rooms(policy, rooms):
    policy = deepcopy(policy)
    versions = policy.setdefault("class_versions", {})
    for room in rooms:
        key, version = str(room.id), room.created_at.isoformat()
        if versions.get(key) != version:
            policy["class"][key] = all_fields()
            versions[key] = version
    return policy


def get_policy(session):
    setting = session.get(ParentContactFieldSetting, 1)
    return (deepcopy(setting.policy), setting.revision) if setting else (default_policy(), 0)


def policy_groups(policy, rooms):
    return [("age", [(str(i), f"{i}歳児") for i in range(6)]),
            ("class", [(str(room.id), room.name) for room in rooms])]


def parse_policy(form, previous, rooms):
    policy = policy_for_rooms(previous, rooms)
    if form.get("mode") not in {"age", "class"}:
        raise ValueError("年齢ごと、クラスごとのどちらかを選んでください。")
    if form.get("room_ids", "") != room_revision(rooms):
        raise HTTPException(409, "クラスが変更されました。画面を開き直してください。")
    if form["mode"] == "class" and not rooms:
        raise ValueError("クラスを登録してから、クラスごとを選んでください。")
    policy["mode"] = form["mode"]
    for mode, columns in policy_groups(policy, rooms):
        for key, _ in columns:
            values = {}
            for group in GROUPS:
                value = form.get(f"{mode}_{key}_{group}")
                if value not in {"show", "hide"}:
                    raise ValueError("各項目の「表示する／表示しない」を選んでください。")
                values[group] = value == "show"
            policy[mode][key] = values
    return policy


def save_policy(session, policy, revision, actor):
    previous, current = get_policy(session)
    if revision != current:
        raise HTTPException(409, "別の管理者が設定を更新しました。画面を開き直してください。")
    now = utc_now()
    try:
        if session.get(ParentContactFieldSetting, 1) is None:
            session.add(ParentContactFieldSetting(policy=policy, revision=1,
                updated_at=now, updated_by_name=actor.display_name))
            session.flush()
        else:
            changed = session.execute(update(ParentContactFieldSetting).where(
                ParentContactFieldSetting.id == 1, ParentContactFieldSetting.revision == revision,
            ).values(policy=policy, revision=revision + 1, updated_at=now,
                     updated_by_name=actor.display_name)).rowcount
            if changed != 1:
                raise HTTPException(409, "別の管理者が設定を更新しました。画面を開き直してください。")
        session.add(ParentContactFieldAudit(previous_policy=previous, policy=policy,
            revision=revision + 1, changed_by_name=actor.display_name, changed_by_user_id=actor.id))
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "別の操作で設定が更新されました。画面を開き直してください。") from None


def age_group(birth_date, day):
    if not birth_date or birth_date > day:
        return None
    april = date(day.year if day.month >= 4 else day.year - 1, 4, 1)
    age = max(0, april.year - birth_date.year - ((april.month, april.day) < (birth_date.month, birth_date.day)))
    return str(age) if age <= 5 else None


def fields_snapshot(session, child, day, entry=None):
    if entry is not None and entry.id is not None:
        snapshot = (entry.extra_data or {}).get(SNAPSHOT_KEY)
        if snapshot:
            return deepcopy(snapshot)
        # Old records always retain all their original fields when edited.
        return {"version": 1, "mode": "legacy", "group": "", "revision": 0, "fields": all_fields()}
    policy, revision = get_policy(session)
    mode = policy["mode"]
    key = age_group(child.birth_date, day) if mode == "age" else str(child.classroom_id or "")
    if mode == "class":
        room = session.get(Classroom, child.classroom_id) if child.classroom_id else None
        if room is None or policy.get("class_versions", {}).get(key) != room.created_at.isoformat():
            key = None
    return {"version": 1, "mode": mode, "group": key, "revision": revision,
            "fields": deepcopy(policy[mode].get(key, all_fields()))}


def snapshot_token(snapshot):
    return sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def check_submission(session, snapshot, token, *, existing):
    if token != snapshot_token(snapshot) and (token or (not existing and snapshot["revision"] != 0)):
        raise HTTPException(409, "連絡項目の設定が変わりました。画面を開き直して入力項目を確認してください。")
    if existing:
        return
    # Serialize first submissions with settings changes; never create settings on GET.
    revision = snapshot["revision"]
    try:
        if session.get(ParentContactFieldSetting, 1) is None:
            session.add(ParentContactFieldSetting(policy=default_policy(), revision=0))
            session.flush()
        changed = session.execute(update(ParentContactFieldSetting).where(
            ParentContactFieldSetting.id == 1, ParentContactFieldSetting.revision == revision,
        ).values(revision=revision)).rowcount
        if changed != 1:
            raise HTTPException(409, "連絡項目の設定が変わりました。画面を開き直してください。")
    except IntegrityError:
        raise HTTPException(409, "連絡項目の設定が変わりました。画面を開き直してください。") from None


def sanitize_fields(values, snapshot):
    for group, (_, names) in GROUPS.items():
        if not snapshot["fields"].get(group, True):
            for name in names:
                values[name] = ""


def contact_field_enabled(entry, group):
    snapshot = (entry.extra_data or {}).get(SNAPSHOT_KEY, {}) if entry else {}
    return snapshot.get("fields", {}).get(group, True)
