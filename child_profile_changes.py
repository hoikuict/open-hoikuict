from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlmodel import Session

from family_support import (
    DEFAULT_RELATIONSHIP_1,
    DEFAULT_RELATIONSHIP_2,
    apply_family_shared_data,
    create_family_for_child,
    family_form_data_from_child,
    normalize_family_payload,
    normalized_optional_text,
    normalized_text,
)
from models import Child, ChildStatus
from time_utils import utc_now

EMPTY_VALUE_LABEL = "未登録"
RELATIONSHIP_OPTIONS = ["母", "父", "祖母", "祖父", "その他"]

CHILD_PROFILE_FIELD_LABELS = {
    "last_name": "姓",
    "first_name": "名",
    "last_name_kana": "姓（カナ）",
    "first_name_kana": "名（カナ）",
    "birth_date": "生年月日",
    "enrollment_date": "入園日",
    "withdrawal_date": "退園日",
    "status": "在籍状況",
    "home_address": "自宅住所",
    "home_phone": "自宅電話番号",
    "allergy": "アレルギー",
    "medical_notes": "医療メモ",
    "g1_last_name": "保護者1 姓",
    "g1_first_name": "保護者1 名",
    "g1_last_name_kana": "保護者1 姓（カナ）",
    "g1_first_name_kana": "保護者1 名（カナ）",
    "g1_relationship": "保護者1 続柄",
    "g1_phone": "保護者1 電話番号",
    "g1_workplace": "保護者1 勤務先",
    "g1_workplace_address": "保護者1 勤務先住所",
    "g1_workplace_phone": "保護者1 勤務先電話番号",
    "g2_last_name": "保護者2 姓",
    "g2_first_name": "保護者2 名",
    "g2_last_name_kana": "保護者2 姓（カナ）",
    "g2_first_name_kana": "保護者2 名（カナ）",
    "g2_relationship": "保護者2 続柄",
    "g2_phone": "保護者2 電話番号",
    "g2_workplace": "保護者2 勤務先",
    "g2_workplace_address": "保護者2 勤務先住所",
    "g2_workplace_phone": "保護者2 勤務先電話番号",
}

FIELD_ORDER = list(CHILD_PROFILE_FIELD_LABELS.keys())


def _normalized_date_text(value: Optional[str]) -> str:
    cleaned = normalized_text(value)
    if not cleaned:
        return ""
    try:
        return date.fromisoformat(cleaned).isoformat()
    except ValueError:
        return cleaned


def _normalized_allergy_text(value: Optional[str]) -> str:
    items = [item.strip() for item in normalized_text(value).replace("、", ",").split(",") if item.strip()]
    return ",".join(items)


def _normalized_status(value: Optional[str]) -> str:
    try:
        return ChildStatus(normalized_text(value) or ChildStatus.enrolled.value).value
    except ValueError:
        return ChildStatus.enrolled.value


def _status_label(value: Optional[str]) -> str:
    try:
        return ChildStatus(value or ChildStatus.enrolled.value).label
    except ValueError:
        return value or EMPTY_VALUE_LABEL


def _display_value(field_name: str, value: Optional[str]) -> str:
    normalized = normalized_text(value)
    if field_name == "status":
        return _status_label(normalized)
    return normalized or EMPTY_VALUE_LABEL


def child_profile_form_data_from_child(child: Child) -> dict[str, str]:
    extra_data = child.extra_data or {}
    allergies = extra_data.get("allergy", []) if isinstance(extra_data, dict) else []
    medical_notes = extra_data.get("medical_notes", "") if isinstance(extra_data, dict) else ""
    family_data = family_form_data_from_child(child)

    return {
        "last_name": child.last_name,
        "first_name": child.first_name,
        "last_name_kana": child.last_name_kana,
        "first_name_kana": child.first_name_kana,
        "birth_date": child.birth_date.isoformat() if child.birth_date else "",
        "enrollment_date": child.enrollment_date.isoformat() if child.enrollment_date else "",
        "withdrawal_date": child.withdrawal_date.isoformat() if child.withdrawal_date else "",
        "status": child.status.value,
        "home_address": family_data["home_address"],
        "home_phone": family_data["home_phone"],
        "allergy": ",".join(allergies) if allergies else "",
        "medical_notes": str(medical_notes or ""),
        "g1_last_name": family_data["g1_last_name"],
        "g1_first_name": family_data["g1_first_name"],
        "g1_last_name_kana": family_data["g1_last_name_kana"],
        "g1_first_name_kana": family_data["g1_first_name_kana"],
        "g1_relationship": family_data["g1_relationship"],
        "g1_phone": family_data["g1_phone"],
        "g1_workplace": family_data["g1_workplace"],
        "g1_workplace_address": family_data["g1_workplace_address"],
        "g1_workplace_phone": family_data["g1_workplace_phone"],
        "g2_last_name": family_data["g2_last_name"],
        "g2_first_name": family_data["g2_first_name"],
        "g2_last_name_kana": family_data["g2_last_name_kana"],
        "g2_first_name_kana": family_data["g2_first_name_kana"],
        "g2_relationship": family_data["g2_relationship"],
        "g2_phone": family_data["g2_phone"],
        "g2_workplace": family_data["g2_workplace"],
        "g2_workplace_address": family_data["g2_workplace_address"],
        "g2_workplace_phone": family_data["g2_workplace_phone"],
    }


def normalize_child_profile_payload(payload: dict[str, Any]) -> dict[str, str]:
    normalized = {field_name: normalized_text(payload.get(field_name)) for field_name in FIELD_ORDER}
    normalized["birth_date"] = _normalized_date_text(payload.get("birth_date"))
    normalized["enrollment_date"] = _normalized_date_text(payload.get("enrollment_date"))
    normalized["withdrawal_date"] = _normalized_date_text(payload.get("withdrawal_date"))
    normalized["status"] = _normalized_status(payload.get("status"))
    normalized["allergy"] = _normalized_allergy_text(payload.get("allergy"))

    normalized.update(
        {
            "home_address": normalize_family_payload(payload)["home_address"],
            "home_phone": normalize_family_payload(payload)["home_phone"],
            "g1_relationship": normalize_family_payload(payload)["g1_relationship"],
            "g2_relationship": normalize_family_payload(payload)["g2_relationship"],
        }
    )
    return normalized


def build_child_profile_payload(
    *,
    last_name: str,
    first_name: str,
    last_name_kana: str,
    first_name_kana: str,
    birth_date: Optional[str],
    enrollment_date: Optional[str],
    withdrawal_date: Optional[str],
    status: str,
    home_address: Optional[str],
    home_phone: Optional[str],
    allergy: str,
    medical_notes: str,
    g1_last_name: str,
    g1_first_name: str,
    g1_last_name_kana: str,
    g1_first_name_kana: str,
    g1_relationship: str,
    g1_phone: str,
    g1_workplace: str,
    g1_workplace_address: str,
    g1_workplace_phone: str,
    g2_last_name: str,
    g2_first_name: str,
    g2_last_name_kana: str,
    g2_first_name_kana: str,
    g2_relationship: str,
    g2_phone: str,
    g2_workplace: str,
    g2_workplace_address: str,
    g2_workplace_phone: str,
) -> dict[str, str]:
    return normalize_child_profile_payload(
        {
            "last_name": last_name,
            "first_name": first_name,
            "last_name_kana": last_name_kana,
            "first_name_kana": first_name_kana,
            "birth_date": birth_date,
            "enrollment_date": enrollment_date,
            "withdrawal_date": withdrawal_date,
            "status": status,
            "home_address": home_address,
            "home_phone": home_phone,
            "allergy": allergy,
            "medical_notes": medical_notes,
            "g1_last_name": g1_last_name,
            "g1_first_name": g1_first_name,
            "g1_last_name_kana": g1_last_name_kana,
            "g1_first_name_kana": g1_first_name_kana,
            "g1_relationship": g1_relationship,
            "g1_phone": g1_phone,
            "g1_workplace": g1_workplace,
            "g1_workplace_address": g1_workplace_address,
            "g1_workplace_phone": g1_workplace_phone,
            "g2_last_name": g2_last_name,
            "g2_first_name": g2_first_name,
            "g2_last_name_kana": g2_last_name_kana,
            "g2_first_name_kana": g2_first_name_kana,
            "g2_relationship": g2_relationship,
            "g2_phone": g2_phone,
            "g2_workplace": g2_workplace,
            "g2_workplace_address": g2_workplace_address,
            "g2_workplace_phone": g2_workplace_phone,
        }
    )


def merge_child_profile_form_data(child: Child, request_data: Optional[dict[str, Any]] = None) -> dict[str, str]:
    form_data = child_profile_form_data_from_child(child)
    if request_data:
        form_data.update(normalize_child_profile_payload(request_data))
    return form_data


def validate_child_profile_payload(payload: dict[str, Any]) -> Optional[str]:
    normalized = normalize_child_profile_payload(payload)
    if not normalized["birth_date"] or not normalized["enrollment_date"]:
        return "生年月日と入園日は必須です。"
    try:
        date.fromisoformat(normalized["birth_date"])
        date.fromisoformat(normalized["enrollment_date"])
    except ValueError:
        return "生年月日と入園日は YYYY-MM-DD 形式で入力してください。"
    if normalized["withdrawal_date"]:
        try:
            date.fromisoformat(normalized["withdrawal_date"])
        except ValueError:
            return "退園日は YYYY-MM-DD 形式で入力してください。"
    return None


def build_child_profile_change_details(child: Child, payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    current = child_profile_form_data_from_child(child)
    updated = normalize_child_profile_payload(payload)
    details: dict[str, dict[str, str]] = {}
    for field_name in FIELD_ORDER:
        old_value = current.get(field_name, "")
        new_value = updated.get(field_name, "")
        if old_value != new_value:
            details[field_name] = {
                "label": CHILD_PROFILE_FIELD_LABELS[field_name],
                "old": _display_value(field_name, old_value),
                "new": _display_value(field_name, new_value),
            }
    return details


def build_child_profile_change_summary(parent_name: str, child_name: str, change_details: dict[str, dict[str, str]]) -> str:
    changed_labels = [detail["label"] for detail in change_details.values()]
    return f"{parent_name} が {child_name} の情報変更を申請: {', '.join(changed_labels)}"


def apply_child_profile_payload(
    session: Session,
    child: Child,
    payload: dict[str, Any],
    *,
    applied_at: Optional[datetime] = None,
) -> dict[str, str]:
    normalized = normalize_child_profile_payload(payload)
    validation_error = validate_child_profile_payload(normalized)
    if validation_error:
        raise ValueError(validation_error)

    now = applied_at or utc_now()
    child.birth_date = date.fromisoformat(normalized["birth_date"])
    child.enrollment_date = date.fromisoformat(normalized["enrollment_date"])
    child.withdrawal_date = date.fromisoformat(normalized["withdrawal_date"]) if normalized["withdrawal_date"] else None
    child.status = ChildStatus(normalized["status"])
    child.last_name = normalized["last_name"]
    child.first_name = normalized["first_name"]
    child.last_name_kana = normalized["last_name_kana"]
    child.first_name_kana = normalized["first_name_kana"]
    child.extra_data = {
        "allergy": [item for item in normalized["allergy"].split(",") if item],
        "medical_notes": normalized["medical_notes"],
    }
    child.updated_at = now
    session.add(child)
    session.flush()

    family = create_family_for_child(session, child, family_name=f"{child.last_name}家")
    apply_family_shared_data(
        session,
        family,
        {
            "family_name": family.family_name,
            "home_address": normalized["home_address"],
            "home_phone": normalized["home_phone"],
            "g1_last_name": normalized["g1_last_name"],
            "g1_first_name": normalized["g1_first_name"],
            "g1_last_name_kana": normalized["g1_last_name_kana"],
            "g1_first_name_kana": normalized["g1_first_name_kana"],
            "g1_relationship": normalized["g1_relationship"] or DEFAULT_RELATIONSHIP_1,
            "g1_phone": normalized["g1_phone"],
            "g1_workplace": normalized["g1_workplace"],
            "g1_workplace_address": normalized["g1_workplace_address"],
            "g1_workplace_phone": normalized["g1_workplace_phone"],
            "g2_last_name": normalized["g2_last_name"],
            "g2_first_name": normalized["g2_first_name"],
            "g2_last_name_kana": normalized["g2_last_name_kana"],
            "g2_first_name_kana": normalized["g2_first_name_kana"],
            "g2_relationship": normalized["g2_relationship"] or DEFAULT_RELATIONSHIP_2,
            "g2_phone": normalized["g2_phone"],
            "g2_workplace": normalized["g2_workplace"],
            "g2_workplace_address": normalized["g2_workplace_address"],
            "g2_workplace_phone": normalized["g2_workplace_phone"],
        },
        updated_at=now,
    )

    child.home_address = normalized_optional_text(normalized["home_address"])
    child.home_phone = normalized_optional_text(normalized["home_phone"])
    return normalized
