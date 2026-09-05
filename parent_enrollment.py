"""Invitation-only enrollment, reviewed before creating or updating the ledger."""

from __future__ import annotations

from datetime import date
import unicodedata

from sqlalchemy import update
from sqlmodel import Session, select

from child_profile_changes import (
    apply_child_profile_payload,
    child_profile_form_data_from_child,
)
from child_profile_history import (
    build_child_profile_snapshot,
    record_child_profile_history,
)
from family_support import (
    apply_family_shared_data,
    create_family_for_child,
    guardian_profiles_from_child,
)
from local_auth import AuthenticationFailed, normalize_login_id
from models import (
    Child,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentChildLinkAudit,
    ParentEnrollment,
    ParentRegistrationRequest,
    PasswordCredential,
)
from time_utils import local_today, utc_now


CHILD_FIELDS = {
    "last_name": "子どもの姓",
    "first_name": "子どもの名",
    "last_name_kana": "子どもの姓（カナ）",
    "first_name_kana": "子どもの名（カナ）",
    "birth_date": "生年月日",
    "enrollment_date": "入園予定日",
    "home_address": "自宅住所",
    "home_phone": "自宅電話",
    "allergy": "アレルギー",
    "medical_notes": "健康面で伝えたいこと",
}
GUARDIAN_FIELDS = {
    "last_name": "姓",
    "first_name": "名",
    "last_name_kana": "姓（カナ）",
    "first_name_kana": "名（カナ）",
    "relationship": "続柄",
    "phone": "電話番号",
    "workplace": "勤務先",
    "workplace_address": "勤務先住所",
    "workplace_phone": "勤務先電話",
}
FIELD_LABELS = {
    **CHILD_FIELDS,
    **{
        f"g{index}_{field}": f"保護者{index}・{label}"
        for index in (1, 2)
        for field, label in GUARDIAN_FIELDS.items()
    },
}


def latest_enrollment(session: Session, account_id: int) -> ParentEnrollment | None:
    return session.exec(
        select(ParentEnrollment)
        .join(ParentRegistrationRequest)
        .where(ParentRegistrationRequest.parent_account_id == account_id)
        .order_by(ParentRegistrationRequest.created_at.desc())
    ).first()


def source_snapshot(child: Child) -> dict:
    return {
        "profile": child_profile_form_data_from_child(child),
        "family_id": child.family_id,
        "child_updated_at": str(child.updated_at),
        "family_updated_at": str(child.family.updated_at) if child.family else None,
    }


def enrollment_target(
    session: Session, child_id: int | None, guardian_order: int | None
) -> tuple[Child | None, int]:
    if child_id is None:
        return None, 1
    child = session.get(Child, child_id)
    if child is None:
        raise ValueError("対象園児が見つかりません")
    profiles = (
        child.family.guardian_profiles()
        if child.family
        else guardian_profiles_from_child(child)
    )
    if guardian_order is None:
        # Choosing a person in an existing family is a staff action, never a name match.
        if profiles:
            raise ValueError("園児詳細の対象保護者から初回入力を依頼してください")
        guardian_order = 1
    target = next((item for item in profiles if item["order"] == guardian_order), None)
    if target and target.get("parent_account_id"):
        raise ValueError(
            "この保護者にはアカウントがあります。既存の認証管理を利用してください"
        )
    if not target and profiles:
        raise ValueError("保護者の紐付け先が変更されています")
    return child, guardian_order


def prepare_enrollment(
    session: Session,
    account: ParentAccount,
    child_name: str,
    child_id: int | None = None,
    guardian_order: int | None = None,
) -> ParentEnrollment:
    child_name = child_name.strip()
    if not child_name or len(child_name) > 200:
        raise ValueError("子どもの名前を200文字以内で入力してください")
    credential = session.exec(
        select(PasswordCredential).where(
            PasswordCredential.parent_account_id == account.id,
            PasswordCredential.principal_type == "parent",
        )
    ).first()
    if account.status != ParentAccountStatus.active or (
        credential and credential.password_hash
    ):
        raise ValueError("利用開始済み・停止中のアカウントには初回入力を依頼できません")
    if session.exec(
        select(ParentChildLink).where(ParentChildLink.parent_account_id == account.id)
    ).first():
        raise ValueError(
            "園児の閲覧権限があるアカウントには既存の登録手続きを利用してください"
        )
    child, order = enrollment_target(session, child_id, guardian_order)
    return ParentEnrollment(
        child_name=child.full_name if child else child_name,
        child_id=child_id,
        guardian_order=order,
        source_snapshot=source_snapshot(child) if child else None,
    )


def enrollment_state(session: Session, raw_state: str):
    from parent_auth import _get_registration_session

    state = _get_registration_session(session, raw_state, "identity")
    registration = session.get(ParentRegistrationRequest, state.registration_request_id)
    enrollment = session.get(ParentEnrollment, state.registration_request_id)
    account = session.get(ParentAccount, state.parent_account_id)
    if (
        not registration
        or not enrollment
        or not account
        or registration.status != "invited"
        or enrollment.applied_at
        or account.status != ParentAccountStatus.active
        or registration.email_normalized_snapshot != normalize_login_id(account.email)
    ):
        raise AuthenticationFailed("招待リンクから手続きをやり直してください")
    return state, registration, enrollment, account


def validate_enrollment_data(data: dict, *, existing_child: bool) -> dict[str, str]:
    values = {}
    for key, label in FIELD_LABELS.items():
        value = str(data.get(key, "")).strip()
        limit = 2000 if key in {"medical_notes", "allergy"} else 300
        if len(value) > limit or any(
            0xD800 <= ord(c) <= 0xDFFF or ord(c) == 0 for c in value
        ):
            raise ValueError(f"{label}の入力内容を確認してください")
        values[key] = value
    required = [
        "last_name",
        "first_name",
        "last_name_kana",
        "first_name_kana",
        "birth_date",
        "enrollment_date",
        "home_address",
        "g1_last_name",
        "g1_first_name",
        "g1_last_name_kana",
        "g1_first_name_kana",
        "g1_relationship",
        "g1_phone",
    ]
    if existing_child:
        for key in values:
            if key.startswith("g2_"):
                values[key] = ""
    elif any(values[f"g2_{key}"] for key in GUARDIAN_FIELDS):
        required += [f"g2_{key}" for key in ("last_name", "first_name", "relationship")]
    for key in required:
        if not values[key]:
            raise ValueError(f"{FIELD_LABELS[key]}を入力してください")
    try:
        birth = date.fromisoformat(values["birth_date"])
        enrollment = date.fromisoformat(values["enrollment_date"])
    except ValueError as exc:
        raise ValueError("日付を正しく入力してください") from exc
    if birth > local_today() or enrollment < birth:
        raise ValueError("生年月日と入園予定日の前後関係を確認してください")
    return values


def submit_enrollment(session: Session, raw_state: str, data: dict) -> None:
    state, registration, enrollment, _ = enrollment_state(session, raw_state)
    values = validate_enrollment_data(
        data, existing_child=enrollment.child_id is not None
    )
    if compact_name(values["last_name"] + values["first_name"]) != compact_name(
        enrollment.child_name
    ):
        raise ValueError(
            "子どもの名前が招待内容と異なります。入力内容を確認し、招待の名前に誤りがある場合は園へご連絡ください"
        )
    claimed = session.execute(
        update(ParentRegistrationRequest)
        .where(
            ParentRegistrationRequest.id == registration.id,
            ParentRegistrationRequest.status == "invited",
        )
        .values(status="pending_review", submitted_at=utc_now(), updated_at=utc_now())
    )
    if claimed.rowcount != 1:
        raise AuthenticationFailed("この申請は既に送信されています")
    enrollment.submitted_data = values
    state.consumed_at = utc_now()
    session.add(enrollment)
    session.add(state)
    session.commit()


def compact_name(name: str) -> str:
    return "".join(unicodedata.normalize("NFKC", name).split()).casefold()


def apply_enrollment(
    session: Session,
    registration: ParentRegistrationRequest,
    account: ParentAccount,
    actor,
) -> None:
    enrollment = session.get(ParentEnrollment, registration.id)
    if not enrollment or not enrollment.submitted_data or enrollment.applied_at:
        raise ValueError("初回入力の提出内容を確認してください")
    if registration.email_normalized_snapshot != normalize_login_id(account.email):
        raise ValueError("メールアドレスが変更されています。再招待してください")
    prepare_enrollment(
        session,
        account,
        enrollment.child_name,
        enrollment.child_id,
        enrollment.guardian_order,
    )
    child, order = enrollment_target(
        session, enrollment.child_id, enrollment.guardian_order
    )
    if child and source_snapshot(child) != enrollment.source_snapshot:
        raise ValueError("招待後に園児・家族情報が変更されています。再招待してください")
    values = validate_enrollment_data(
        enrollment.submitted_data, existing_child=child is not None
    )
    if compact_name(values["last_name"] + values["first_name"]) != compact_name(
        enrollment.child_name
    ):
        raise ValueError(
            "子どもの名前が招待内容と異なります。宛先と名前を確認し再招待してください"
        )
    # Claim before creating the child so repeated/concurrent approval cannot duplicate it.
    claimed = session.execute(
        update(ParentRegistrationRequest)
        .where(
            ParentRegistrationRequest.id == registration.id,
            ParentRegistrationRequest.status == "pending_review",
        )
        .values(status="reviewing")
    )
    if claimed.rowcount != 1:
        raise ValueError("この申請は既に処理されています")
    is_new = child is None
    before = build_child_profile_snapshot(session, child) if child else None
    if child is None:
        child = Child(
            **{
                key: values[key]
                for key in (
                    "last_name",
                    "first_name",
                    "last_name_kana",
                    "first_name_kana",
                )
            },
            birth_date=date.fromisoformat(values["birth_date"]),
            enrollment_date=date.fromisoformat(values["enrollment_date"]),
        )
        session.add(child)
        session.flush()
    family = create_family_for_child(session, child)
    payload = child_profile_form_data_from_child(child)
    payload.update({key: values[key] for key in CHILD_FIELDS})
    profiles = [
        dict(item) for item in family.guardian_profiles() if item["order"] != order
    ]
    own = {key: values[f"g1_{key}"] for key in GUARDIAN_FIELDS}
    own.update(order=order, email=account.email, parent_account_id=None)
    profiles.append(own)
    if is_new and values["g2_last_name"]:
        profiles.append(
            {**{key: values[f"g2_{key}"] for key in GUARDIAN_FIELDS}, "order": 2}
        )
    payload["guardians_data"] = profiles
    previous_extra = dict(child.extra_data or {})
    apply_child_profile_payload(session, child, payload)
    child.extra_data = {**previous_extra, **(child.extra_data or {})}
    account.family_id = family.id
    account.display_name = f"{own['last_name']} {own['first_name']}"
    account.registration_verification_name = (
        f"{own['last_name_kana']} {own['first_name_kana']}"
    )
    account.registration_verification_name_type = "kana"
    session.add(account)
    session.flush()
    profiles = [dict(item) for item in family.guardian_profiles()]
    for profile in profiles:
        if profile["order"] == order:
            profile["parent_account_id"] = account.id
    apply_family_shared_data(
        session,
        family,
        {
            "family_name": family.family_name,
            "home_address": values["home_address"],
            "home_phone": values["home_phone"],
            "guardians_data": profiles,
        },
    )
    child.registration_verification_name = (
        f"{values['last_name_kana']} {values['first_name_kana']}"
    )
    child.registration_verification_name_type = "kana"
    session.add(child)
    session.add(
        ParentChildLink(
            parent_account_id=account.id,
            child_id=child.id,
            relationship_label=own["relationship"],
            is_primary_contact=True,
        )
    )
    session.add(
        ParentChildLinkAudit(
            parent_account_id=account.id,
            child_id=child.id,
            operation="link",
            actor_user_id=actor.id,
            actor_name=actor.display_name,
        )
    )
    enrollment.child_id = child.id
    enrollment.applied_at = utc_now()
    registration.matched_child_id = child.id
    session.add(enrollment)
    session.flush()
    record_child_profile_history(
        session,
        child,
        actor_name=actor.display_name,
        action="created" if is_new else "updated",
        previous_snapshot=before,
        source="parent_enrollment",
        requester_name=account.display_name,
    )
