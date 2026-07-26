from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from family_support import family_form_data_from_family, guardian_profiles_from_child
from models import (
    Child,
    ChildAllergy,
    ChildProfileChangeRequest,
    ChildProfileChangeRequestStatus,
    ChildProfileHistory,
    Classroom,
    Family,
    ParentAccount,
)
from time_utils import local_naive_now


JST = timezone(timedelta(hours=9), name="JST")


PROFILE_GROUPS = [
    {
        "title": "子どもの個人情報",
        "fields": [
            ("last_name", "姓"),
            ("first_name", "名"),
            ("last_name_kana", "姓（カナ）"),
            ("first_name_kana", "名（カナ）"),
            ("birth_date", "生年月日"),
            ("enrollment_date", "入園日"),
            ("withdrawal_date", "退園日"),
            ("status", "在籍状況"),
            ("classroom", "クラス"),
            ("allergy", "アレルギー"),
            ("medical_notes", "医療メモ"),
        ],
    },
    {
        "title": "家族情報",
        "fields": [
            ("family_name", "家族名"),
            ("home_address", "自宅住所"),
            ("home_phone", "自宅電話番号"),
        ],
    },
    {
        "title": "保護者1",
        "fields": [
            ("g1_last_name", "姓"),
            ("g1_first_name", "名"),
            ("g1_last_name_kana", "姓（カナ）"),
            ("g1_first_name_kana", "名（カナ）"),
            ("g1_relationship", "続柄"),
            ("g1_phone", "電話番号"),
            ("g1_workplace", "勤務先"),
            ("g1_workplace_address", "勤務先住所"),
            ("g1_workplace_phone", "勤務先電話番号"),
        ],
    },
    {
        "title": "保護者2",
        "fields": [
            ("g2_last_name", "姓"),
            ("g2_first_name", "名"),
            ("g2_last_name_kana", "姓（カナ）"),
            ("g2_first_name_kana", "名（カナ）"),
            ("g2_relationship", "続柄"),
            ("g2_phone", "電話番号"),
            ("g2_workplace", "勤務先"),
            ("g2_workplace_address", "勤務先住所"),
            ("g2_workplace_phone", "勤務先電話番号"),
        ],
    },
]

FIELD_LABELS = {
    key: f"{group['title']} {label}" if str(group["title"]).startswith("保護者") else label
    for group in PROFILE_GROUPS
    for key, label in group["fields"]
}

ALLERGY_DETAIL_FIELDS = [
    ("allergen_category", "カテゴリー"),
    ("allergen_name", "アレルゲン名"),
    ("severity", "重症度"),
    ("symptoms", "症状"),
    ("diagnosis_confirmed", "医師診断"),
    ("diagnosis_date", "診断日"),
    ("treating_doctor", "担当医"),
    ("removal_required", "除去対応"),
    ("substitute_food", "代替食品"),
    ("action_plan", "緊急時対応"),
    ("source_document", "根拠資料"),
    ("source_document_date", "資料日"),
    ("valid_until", "有効期限"),
    ("is_active", "状態"),
    ("notes", "備考"),
]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _local_wall_clock(value: Optional[datetime]) -> datetime:
    if value is None:
        return local_naive_now()
    if value.tzinfo is not None:
        return value.astimezone(JST).replace(tzinfo=None)
    return value


def _utc_storage_to_local_wall_clock(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(JST).replace(tzinfo=None)


def build_allergy_records_snapshot(session: Session, child_id: int) -> list[dict[str, Any]]:
    session.flush()
    allergies = session.exec(
        select(ChildAllergy)
        .where(ChildAllergy.child_id == child_id)
        .order_by(ChildAllergy.id)
    ).all()
    return [
        {
            "id": allergy.id,
            "allergen_category": allergy.allergen_category.label,
            "allergen_name": _text(allergy.allergen_name),
            "severity": allergy.severity.label,
            "symptoms": _text(allergy.symptoms),
            "diagnosis_confirmed": "あり" if allergy.diagnosis_confirmed else "なし",
            "diagnosis_date": allergy.diagnosis_date.isoformat() if allergy.diagnosis_date else "",
            "treating_doctor": _text(allergy.treating_doctor),
            "removal_required": "必要" if allergy.removal_required else "不要",
            "substitute_food": _text(allergy.substitute_food),
            "action_plan": _text(allergy.action_plan),
            "source_document": _text(allergy.source_document),
            "source_document_date": (
                allergy.source_document_date.isoformat() if allergy.source_document_date else ""
            ),
            "valid_until": allergy.valid_until.isoformat() if allergy.valid_until else "",
            "is_active": "有効" if allergy.is_active else "解除",
            "notes": _text(allergy.notes),
        }
        for allergy in allergies
    ]


def build_allergy_record_changes(
    previous_records: list[dict[str, Any]],
    current_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    previous_by_id = {str(item.get("id")): item for item in previous_records}
    current_by_id = {str(item.get("id")): item for item in current_records}
    changes: list[dict[str, Any]] = []

    for record_id in sorted(set(previous_by_id) | set(current_by_id)):
        previous = previous_by_id.get(record_id)
        current = current_by_id.get(record_id)
        if previous is None and current is not None:
            field_changes = [
                {"key": key, "label": label, "old": "", "new": _text(current.get(key))}
                for key, label in ALLERGY_DETAIL_FIELDS
                if _text(current.get(key))
            ]
            changes.append(
                {
                    "allergy_id": current.get("id"),
                    "event": "added",
                    "title": f"{current.get('allergen_name') or 'アレルギー'}を追加",
                    "before": {},
                    "after": current,
                    "fields": field_changes,
                }
            )
            continue
        if current is None and previous is not None:
            changes.append(
                {
                    "allergy_id": previous.get("id"),
                    "event": "removed",
                    "title": f"{previous.get('allergen_name') or 'アレルギー'}を削除",
                    "before": previous,
                    "after": {},
                    "fields": [],
                }
            )
            continue

        field_changes = []
        for key, label in ALLERGY_DETAIL_FIELDS:
            old_value = _text(previous.get(key))
            new_value = _text(current.get(key))
            if old_value != new_value:
                field_changes.append(
                    {"key": key, "label": label, "old": old_value, "new": new_value}
                )
        if not field_changes:
            continue

        old_status = _text(previous.get("is_active"))
        new_status = _text(current.get("is_active"))
        name = current.get("allergen_name") or previous.get("allergen_name") or "アレルギー"
        if old_status == "有効" and new_status == "解除":
            event = "deactivated"
            title = f"{name}を解除"
        elif old_status == "解除" and new_status == "有効":
            event = "reactivated"
            title = f"{name}を再有効化"
        else:
            event = "updated"
            title = f"{name}を更新"
        changes.append(
            {
                "allergy_id": current.get("id"),
                "event": event,
                "title": title,
                "before": previous,
                "after": current,
                "fields": field_changes,
            }
        )
    return changes


def build_child_profile_snapshot(session: Session, child: Child) -> dict[str, str]:
    session.flush()
    session.refresh(child)

    family = session.get(Family, child.family_id) if child.family_id else None
    if family:
        session.refresh(family)
        family_data = family_form_data_from_family(family)
    else:
        guardians_data = guardian_profiles_from_child(child)
        family_data = {
            "family_name": "",
            "home_address": child.home_address or "",
            "home_phone": child.home_phone or "",
            "guardians_data": guardians_data,
        }
        for index in (1, 2):
            guardian = guardians_data[index - 1] if len(guardians_data) >= index else {}
            for key in (
                "last_name",
                "first_name",
                "last_name_kana",
                "first_name_kana",
                "relationship",
                "phone",
                "workplace",
                "workplace_address",
                "workplace_phone",
            ):
                family_data[f"g{index}_{key}"] = _text(guardian.get(key))

    classroom = session.get(Classroom, child.classroom_id) if child.classroom_id else None
    extra_data = child.extra_data if isinstance(child.extra_data, dict) else {}
    allergies = extra_data.get("allergy", [])
    allergy_text = ", ".join(_text(item) for item in allergies) if isinstance(allergies, list) else _text(allergies)

    snapshot = {
        "last_name": _text(child.last_name),
        "first_name": _text(child.first_name),
        "last_name_kana": _text(child.last_name_kana),
        "first_name_kana": _text(child.first_name_kana),
        "birth_date": child.birth_date.isoformat() if child.birth_date else "",
        "enrollment_date": child.enrollment_date.isoformat() if child.enrollment_date else "",
        "withdrawal_date": child.withdrawal_date.isoformat() if child.withdrawal_date else "",
        "status": child.status.label,
        "classroom": classroom.name if classroom else "未設定",
        "allergy": allergy_text,
        "medical_notes": _text(extra_data.get("medical_notes")),
        "family_name": _text(family_data.get("family_name")),
        "home_address": _text(family_data.get("home_address")),
        "home_phone": _text(family_data.get("home_phone")),
    }
    for index in (1, 2):
        for key in (
            "last_name",
            "first_name",
            "last_name_kana",
            "first_name_kana",
            "relationship",
            "phone",
            "workplace",
            "workplace_address",
            "workplace_phone",
        ):
            snapshot[f"g{index}_{key}"] = _text(family_data.get(f"g{index}_{key}"))
    return snapshot


def build_profile_changes(
    previous_snapshot: Optional[dict[str, Any]],
    current_snapshot: dict[str, Any],
    *,
    created: bool = False,
) -> dict[str, dict[str, str]]:
    previous = previous_snapshot or {}
    changes: dict[str, dict[str, str]] = {}
    for key in FIELD_LABELS:
        old_value = _text(previous.get(key))
        new_value = _text(current_snapshot.get(key))
        if old_value != new_value and (not created or new_value):
            changes[key] = {"old": old_value, "new": new_value}
    return changes


def latest_child_profile_history(session: Session, child_id: int) -> Optional[ChildProfileHistory]:
    return session.exec(
        select(ChildProfileHistory)
        .where(ChildProfileHistory.child_id == child_id)
        .order_by(ChildProfileHistory.recorded_at.desc(), ChildProfileHistory.id.desc())
    ).first()


def ensure_initial_child_profile_history(
    session: Session,
    child: Child,
    *,
    actor_name: str = "システム（既存データ）",
    snapshot: Optional[dict[str, str]] = None,
) -> ChildProfileHistory:
    existing = latest_child_profile_history(session, child.id)
    if existing:
        return existing

    current_snapshot = snapshot or build_child_profile_snapshot(session, child)
    history = ChildProfileHistory(
        child_id=child.id,
        action="created",
        actor_name=actor_name,
        snapshot=current_snapshot,
        changes=build_profile_changes(None, current_snapshot, created=True),
        recorded_at=_local_wall_clock(child.created_at),
    )
    session.add(history)
    session.flush()
    return history


def ensure_health_allergy_baseline(
    session: Session,
    child: Child,
    allergy_records: Optional[list[dict[str, Any]]] = None,
) -> Optional[ChildProfileHistory]:
    histories = session.exec(
        select(ChildProfileHistory)
        .where(ChildProfileHistory.child_id == child.id)
        .order_by(ChildProfileHistory.recorded_at.desc(), ChildProfileHistory.id.desc())
    ).all()
    for history in histories:
        if "_allergy_records" in (history.snapshot or {}):
            return None

    snapshot = build_child_profile_snapshot(session, child)
    snapshot["_history_source"] = "health_management"
    snapshot["_allergy_records"] = (
        allergy_records
        if allergy_records is not None
        else build_allergy_records_snapshot(session, child.id)
    )
    history = ChildProfileHistory(
        child_id=child.id,
        action="health_baseline",
        actor_name="システム（既存データ）",
        snapshot=snapshot,
        changes={},
        recorded_at=local_naive_now(),
    )
    session.add(history)
    session.flush()
    return history


def record_child_profile_history(
    session: Session,
    child: Child,
    *,
    actor_name: str,
    action: str = "updated",
    previous_snapshot: Optional[dict[str, Any]] = None,
    recorded_at: Optional[datetime] = None,
    source: str = "staff_edit",
    requester_name: Optional[str] = None,
    allergy_before: Optional[list[dict[str, Any]]] = None,
    allergy_after: Optional[list[dict[str, Any]]] = None,
) -> Optional[ChildProfileHistory]:
    current_snapshot = build_child_profile_snapshot(session, child)
    current_allergy_records = (
        allergy_after
        if allergy_after is not None
        else build_allergy_records_snapshot(session, child.id)
    )
    allergy_changes = (
        build_allergy_record_changes(allergy_before, current_allergy_records)
        if allergy_before is not None
        else []
    )
    if action == "created":
        changes = build_profile_changes(None, current_snapshot, created=True)
    else:
        baseline = previous_snapshot
        if baseline is None:
            latest = latest_child_profile_history(session, child.id)
            baseline = latest.snapshot if latest else {}
        changes = build_profile_changes(baseline, current_snapshot)
        if not changes and not allergy_changes:
            return None

    current_snapshot["_history_source"] = _text(source) or "staff_edit"
    current_snapshot["_allergy_records"] = current_allergy_records
    if allergy_changes:
        current_snapshot["_allergy_changes"] = allergy_changes
    if requester_name:
        current_snapshot["_requester_name"] = _text(requester_name)

    history = ChildProfileHistory(
        child_id=child.id,
        action=action,
        actor_name=_text(actor_name) or "不明",
        snapshot=current_snapshot,
        changes=changes,
        recorded_at=_local_wall_clock(recorded_at),
    )
    session.add(history)
    session.flush()
    return history


def profile_groups_for_history(history: ChildProfileHistory) -> list[dict[str, Any]]:
    snapshot = history.snapshot or {}
    changes = history.changes or {}
    groups: list[dict[str, Any]] = []
    for group in PROFILE_GROUPS:
        fields = []
        for key, label in group["fields"]:
            change = changes.get(key, {}) if isinstance(changes, dict) else {}
            fields.append(
                {
                    "key": key,
                    "label": label,
                    "value": _text(snapshot.get(key)) or "未登録",
                    "changed": key in changes,
                    "old": _text(change.get("old")) or "未登録",
                }
            )
        groups.append({"title": group["title"], "fields": fields})
    return groups


def allergy_items_for_history(history: ChildProfileHistory) -> list[dict[str, Any]]:
    snapshot = history.snapshot or {}
    records = list(snapshot.get("_allergy_records") or [])
    changes = list(snapshot.get("_allergy_changes") or [])
    change_by_id = {str(item.get("allergy_id")): item for item in changes}
    record_by_id = {str(item.get("id")): item for item in records}

    # A hard-deleted record is not expected in the current UI, but preserve it in
    # history if a future workflow removes one.
    for change in changes:
        record_id = str(change.get("allergy_id"))
        if record_id not in record_by_id and change.get("before"):
            record = dict(change["before"])
            records.append(record)
            record_by_id[record_id] = record

    items: list[dict[str, Any]] = []
    for record in records:
        change = change_by_id.get(str(record.get("id")), {})
        changed_fields = {
            field.get("key"): field
            for field in change.get("fields", [])
            if isinstance(field, dict)
        }
        fields = []
        for key, label in ALLERGY_DETAIL_FIELDS:
            field_change = changed_fields.get(key, {})
            fields.append(
                {
                    "key": key,
                    "label": label,
                    "value": _text(record.get(key)) or "未登録",
                    "changed": key in changed_fields,
                    "old": _text(field_change.get("old")) or "未登録",
                }
            )
        items.append(
            {
                "id": record.get("id"),
                "name": _text(record.get("allergen_name")) or "アレルギー",
                "active": record.get("is_active") == "有効",
                "changed": bool(change),
                "event_title": change.get("title", ""),
                "fields": fields,
            }
        )
    return items


def allergy_change_labels(history: ChildProfileHistory) -> list[str]:
    return [
        _text(change.get("title"))
        for change in (history.snapshot or {}).get("_allergy_changes", [])
        if _text(change.get("title"))
    ]


def changed_field_labels(history: ChildProfileHistory) -> list[str]:
    return [FIELD_LABELS.get(key, key) for key in (history.changes or {})]


def annotate_legacy_parent_request_histories(session: Session, child_id: int) -> int:
    """Add request/approver metadata to histories created before source tracking."""
    histories = session.exec(
        select(ChildProfileHistory)
        .where(ChildProfileHistory.child_id == child_id)
        .order_by(ChildProfileHistory.recorded_at.desc(), ChildProfileHistory.id.desc())
    ).all()
    candidates = [
        history
        for history in histories
        if history.action == "updated"
        and (history.snapshot or {}).get("_history_source") in {None, "staff_edit"}
    ]
    if not candidates:
        return 0

    requests = session.exec(
        select(ChildProfileChangeRequest).where(
            ChildProfileChangeRequest.child_id == child_id,
            ChildProfileChangeRequest.status == ChildProfileChangeRequestStatus.approved,
            ChildProfileChangeRequest.reviewed_at.is_not(None),
        )
    ).all()
    annotated = 0
    used_history_ids: set[int] = set()
    for change_request in requests:
        request_keys = set((change_request.change_details or {}).keys())
        if not request_keys or request_keys.issubset({"before", "after"}):
            continue
        reviewed_local = _utc_storage_to_local_wall_clock(change_request.reviewed_at)
        matches = []
        for history in candidates:
            if history.id in used_history_ids:
                continue
            if change_request.reviewed_by and history.actor_name != change_request.reviewed_by:
                continue
            history_keys = set((history.changes or {}).keys())
            if not request_keys.intersection(history_keys):
                continue
            time_gap = abs((history.recorded_at - reviewed_local).total_seconds())
            if time_gap <= 5 * 60:
                matches.append((time_gap, history))
        if not matches:
            continue

        _, history = min(matches, key=lambda item: item[0])
        parent = session.get(ParentAccount, change_request.parent_account_id)
        snapshot = dict(history.snapshot or {})
        snapshot["_history_source"] = "parent_request"
        snapshot["_requester_name"] = parent.display_name if parent else "保護者"
        snapshot["_change_request_id"] = change_request.id
        history.snapshot = snapshot
        session.add(history)
        used_history_ids.add(history.id)
        annotated += 1
    if annotated:
        session.flush()
    return annotated
