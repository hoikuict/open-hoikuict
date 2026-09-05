from __future__ import annotations

from collections import Counter, deque
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from models import Child, Family, Guardian, ParentAccount
from time_utils import utc_now

DEFAULT_RELATIONSHIP_1 = "母"
DEFAULT_RELATIONSHIP_2 = "父"
GUARDIAN_FIELD_NAMES = (
    "last_name",
    "first_name",
    "last_name_kana",
    "first_name_kana",
    "relationship",
    "parent_account_id",
    "email",
    "phone",
    "workplace",
    "workplace_address",
    "workplace_phone",
)
LEGACY_GUARDIAN_SLOTS = (
    ("g1", DEFAULT_RELATIONSHIP_1),
    ("g2", DEFAULT_RELATIONSHIP_2),
)


def normalized_text(value: Optional[str]) -> str:
    return (value or "").strip()


def normalized_optional_text(value: Optional[str]) -> Optional[str]:
    cleaned = normalized_text(value)
    return cleaned or None


def _identity_key(value: Optional[str]) -> str:
    return "".join(normalized_text(value).split()).casefold()


def _phone_key(value: Optional[str]) -> str:
    return "".join(character for character in normalized_text(value) if character.isdigit())


def _email_key(value: Optional[str]) -> str:
    return normalized_text(value).casefold()


def _default_relationship_for_index(index: int) -> str:
    if index == 0:
        return DEFAULT_RELATIONSHIP_1
    if index == 1:
        return DEFAULT_RELATIONSHIP_2
    return ""


def _normalized_guardian_order(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _normalized_parent_account_id(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def normalize_guardian_profile(
    profile: Optional[dict[str, Any]],
    *,
    default_relationship: str,
    fallback_order: int,
) -> dict[str, Any]:
    source = profile if isinstance(profile, dict) else {}
    return {
        "order": _normalized_guardian_order(source.get("order"), fallback_order),
        "last_name": normalized_text(str(source.get("last_name", ""))),
        "first_name": normalized_text(str(source.get("first_name", ""))),
        "last_name_kana": normalized_text(str(source.get("last_name_kana", ""))),
        "first_name_kana": normalized_text(str(source.get("first_name_kana", ""))),
        "relationship": normalized_text(str(source.get("relationship", ""))) or default_relationship,
        "parent_account_id": _normalized_parent_account_id(source.get("parent_account_id")),
        "email": normalized_text(str(source.get("email", ""))),
        "phone": normalized_text(str(source.get("phone", ""))),
        "workplace": normalized_text(str(source.get("workplace", ""))),
        "workplace_address": normalized_text(str(source.get("workplace_address", ""))),
        "workplace_phone": normalized_text(str(source.get("workplace_phone", ""))),
    }


def normalize_guardians_data(guardians_data: Any) -> list[dict[str, Any]]:
    if not isinstance(guardians_data, list):
        return []

    normalized_guardians: list[dict[str, Any]] = []
    for index, item in enumerate(guardians_data):
        if not isinstance(item, dict):
            continue
        normalized = normalize_guardian_profile(
            item,
            default_relationship=_default_relationship_for_index(index),
            fallback_order=index + 1,
        )
        if not normalized["last_name"] or not normalized["first_name"]:
            continue
        normalized_guardians.append(normalized)

    return sorted(normalized_guardians, key=lambda item: int(item.get("order", 99)))


def flatten_guardians_data(guardians_data: list[dict[str, Any]]) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for index, (prefix, default_relationship) in enumerate(LEGACY_GUARDIAN_SLOTS):
        guardian = normalize_guardian_profile(
            guardians_data[index] if index < len(guardians_data) else None,
            default_relationship=default_relationship,
            fallback_order=index + 1,
        )
        for field_name in GUARDIAN_FIELD_NAMES:
            value = guardian.get(field_name, "")
            flattened[f"{prefix}_{field_name}"] = "" if value is None else str(value)
    return flattened


def guardians_data_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "guardians_data" in payload or "guardians" in payload:
        return normalize_guardians_data(payload.get("guardians_data", payload.get("guardians")))

    profiles: list[dict[str, Any]] = []
    for index, (prefix, default_relationship) in enumerate(LEGACY_GUARDIAN_SLOTS):
        normalized = normalize_guardian_profile(
            {
                field_name: payload.get(f"{prefix}_{field_name}", "")
                for field_name in GUARDIAN_FIELD_NAMES
            },
            default_relationship=default_relationship,
            fallback_order=index + 1,
        )
        if not normalized["last_name"] or not normalized["first_name"]:
            continue
        profiles.append(normalized)
    return profiles


def empty_guardian_form(default_relationship: str) -> dict[str, str]:
    return {
        field_name: (default_relationship if field_name == "relationship" else "")
        for field_name in GUARDIAN_FIELD_NAMES
    }


def guardian_form_from_profile(profile: Optional[dict[str, Any]], default_relationship: str) -> dict[str, str]:
    normalized = normalize_guardian_profile(
        profile,
        default_relationship=default_relationship,
        fallback_order=1,
    )
    return {field_name: str(normalized.get(field_name, "")) for field_name in GUARDIAN_FIELD_NAMES}


def guardian_profiles_from_child(child: Child) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    guardians = sorted(child.guardians, key=lambda guardian: guardian.order)
    for guardian in guardians:
        profiles.append(
            {
                "order": guardian.order,
                "last_name": guardian.last_name,
                "first_name": guardian.first_name,
                "last_name_kana": guardian.last_name_kana or "",
                "first_name_kana": guardian.first_name_kana or "",
                "relationship": guardian.relationship or "",
                "parent_account_id": guardian.parent_account_id,
                "email": guardian.email or "",
                "phone": guardian.phone or "",
                "workplace": guardian.workplace or "",
                "workplace_address": guardian.workplace_address or "",
                "workplace_phone": guardian.workplace_phone or "",
            }
        )
    return profiles


def build_family_form_data(
    *,
    family_name: Optional[str],
    home_address: Optional[str],
    home_phone: Optional[str],
    guardians_data: Any = None,
) -> dict[str, Any]:
    normalized_guardians = normalize_guardians_data(guardians_data)
    form_data: dict[str, Any] = {
        "family_name": normalized_text(family_name),
        "home_address": normalized_text(home_address),
        "home_phone": normalized_text(home_phone),
        "guardians_data": normalized_guardians,
    }
    form_data.update(flatten_guardians_data(normalized_guardians))
    return form_data


def build_family_payload(
    *,
    family_name: Optional[str],
    home_address: Optional[str],
    home_phone: Optional[str],
    guardians_data: Any = None,
) -> dict[str, Any]:
    normalized = normalize_family_payload(
        {
            "family_name": family_name,
            "home_address": home_address,
            "home_phone": home_phone,
            "guardians_data": guardians_data,
        }
    )
    return {
        "family_name": normalized["family_name"],
        "home_address": normalized["home_address"],
        "home_phone": normalized["home_phone"],
        "guardians_data": normalized["guardians_data"],
    }


def family_form_data_from_family(family: Optional[Family]) -> dict[str, Any]:
    return build_family_form_data(
        family_name=family.family_name if family else "",
        home_address=family.home_address if family else "",
        home_phone=family.home_phone if family else "",
        guardians_data=family.guardian_profiles() if family else [],
    )


def family_form_data_from_child(child: Child) -> dict[str, Any]:
    if child.family:
        return family_form_data_from_family(child.family)

    return build_family_form_data(
        family_name=infer_family_name([child], []),
        home_address=child.home_address or "",
        home_phone=child.home_phone or "",
        guardians_data=guardian_profiles_from_child(child),
    )


def normalize_family_payload(payload: dict[str, Any]) -> dict[str, Any]:
    guardians_data = guardians_data_from_payload(payload)
    normalized: dict[str, Any] = {
        "family_name": normalized_text(payload.get("family_name")),
        "home_address": normalized_text(payload.get("home_address")),
        "home_phone": normalized_text(payload.get("home_phone")),
        "guardians_data": guardians_data,
    }
    normalized.update(flatten_guardians_data(guardians_data))
    return normalized


def guardian_profiles_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize_family_payload(payload)["guardians_data"]


def infer_family_name(children: list[Child], parent_accounts: list[ParentAccount]) -> str:
    last_names = [child.last_name.strip() for child in children if child.last_name.strip()]
    if last_names:
        common_last_name = Counter(last_names).most_common(1)[0][0]
        return f"{common_last_name}家"

    parent_last_names = [account.display_name.strip().split()[0] for account in parent_accounts if account.display_name.strip()]
    if parent_last_names:
        common_last_name = Counter(parent_last_names).most_common(1)[0][0]
        return f"{common_last_name}家"

    return "新しい家族"


def sync_parent_child_links(session: Session, family: Family) -> None:
    # family_id is grouping data, not an authorization source. Existing explicit
    # links are intentionally preserved and new links must be created by a
    # dedicated parent-child association operation.
    del session, family


def backfill_family_guardian_account_links(session: Session, family: Family) -> int:
    """Safely link legacy guardian profiles to an account in the same family.

    Existing links are preserved. A missing link is filled only when the
    guardian's full name and at least one contact field identify exactly one
    unused account belonging to the family.
    """
    if family.id is None:
        return 0

    accounts = session.exec(
        select(ParentAccount)
        .where(ParentAccount.family_id == family.id)
        .order_by(ParentAccount.id)
    ).all()
    if not accounts:
        return 0

    # Work on copies so SQLAlchemy can detect the final JSON assignment even
    # when this is an already-persisted legacy record.
    profiles = [dict(profile) for profile in family.guardian_profiles()]
    used_account_ids = {
        account_id
        for profile in profiles
        if (account_id := _normalized_parent_account_id(profile.get("parent_account_id")))
        is not None
    }
    changed = 0

    for profile in profiles:
        if _normalized_parent_account_id(profile.get("parent_account_id")) is not None:
            continue

        guardian_name = _identity_key(
            f"{normalized_text(str(profile.get('last_name', '')))} "
            f"{normalized_text(str(profile.get('first_name', '')))}"
        )
        guardian_phone = _phone_key(str(profile.get("phone", "")))
        guardian_email = _email_key(str(profile.get("email", "")))
        if not guardian_name or (not guardian_phone and not guardian_email):
            continue

        candidates: list[ParentAccount] = []
        for account in accounts:
            if account.id is None or account.id in used_account_ids:
                continue
            if _identity_key(account.display_name) != guardian_name:
                continue
            phone_matches = bool(
                guardian_phone
                and _phone_key(account.phone)
                and guardian_phone == _phone_key(account.phone)
            )
            email_matches = bool(
                guardian_email
                and _email_key(account.email)
                and guardian_email == _email_key(account.email)
            )
            if phone_matches or email_matches:
                candidates.append(account)

        if len(candidates) != 1:
            continue

        account = candidates[0]
        profile["parent_account_id"] = account.id
        if not normalized_text(str(profile.get("email", ""))):
            profile["email"] = account.email
        used_account_ids.add(account.id)
        changed += 1

    if changed:
        family.shared_profile = {"guardians": normalize_guardians_data(profiles)}
        family.updated_at = utc_now()
        session.add(family)
        session.flush()
    return changed


def sync_family_to_children(session: Session, family: Family, *, updated_at: Optional[datetime] = None) -> None:
    now = updated_at or utc_now()
    children = session.exec(
        select(Child)
        .options(selectinload(Child.guardians))
        .where(Child.family_id == family.id)
        .order_by(Child.last_name_kana, Child.first_name_kana)
    ).all()
    guardian_profiles = family.guardian_profiles()

    for child in children:
        child.home_address = family.home_address
        child.home_phone = family.home_phone
        child.updated_at = now
        session.add(child)

        for guardian in list(child.guardians):
            session.delete(guardian)
        session.flush()

        for profile in guardian_profiles:
            session.add(
                Guardian(
                    child_id=child.id,
                    last_name=normalized_text(str(profile.get("last_name", ""))),
                    first_name=normalized_text(str(profile.get("first_name", ""))),
                    last_name_kana=normalized_optional_text(str(profile.get("last_name_kana", ""))),
                    first_name_kana=normalized_optional_text(str(profile.get("first_name_kana", ""))),
                    relationship=normalized_text(str(profile.get("relationship", ""))) or "保護者",
                    parent_account_id=_normalized_parent_account_id(
                        profile.get("parent_account_id")
                    ),
                    email=normalized_optional_text(str(profile.get("email", ""))),
                    phone=normalized_optional_text(str(profile.get("phone", ""))),
                    workplace=normalized_optional_text(str(profile.get("workplace", ""))),
                    workplace_address=normalized_optional_text(str(profile.get("workplace_address", ""))),
                    workplace_phone=normalized_optional_text(str(profile.get("workplace_phone", ""))),
                    order=int(profile.get("order", 1)),
                )
            )
        session.flush()
        session.expire(child, ["guardians"])


def apply_family_shared_data(
    session: Session,
    family: Family,
    payload: dict[str, Any],
    *,
    updated_at: Optional[datetime] = None,
) -> dict[str, Any]:
    normalized = normalize_family_payload(payload)
    previous_address = family.home_address
    previous_account_ids = {item.get("parent_account_id") for item in family.guardian_profiles()}
    family.family_name = normalized["family_name"] or family.family_name
    family.home_address = normalized_optional_text(normalized["home_address"])
    family.home_phone = normalized_optional_text(normalized["home_phone"])
    family.shared_profile = {"guardians": normalized["guardians_data"]}
    family.updated_at = updated_at or utc_now()
    session.add(family)
    session.flush()
    sync_family_to_parent_accounts(session, family, previous_address=previous_address, previous_account_ids=previous_account_ids)
    sync_family_to_children(session, family, updated_at=family.updated_at)
    sync_parent_child_links(session, family)
    return normalized


SHARED_ACCOUNT_FIELDS = ("email", "phone", "workplace", "workplace_address", "workplace_phone")


def validate_parent_contact_email(session: Session, email: str, account_id: int | None = None) -> str:
    email = normalized_text(email)
    if not email or len(email) > 255 or "@" not in email or any(c.isspace() for c in email):
        raise HTTPException(400, "受信可能なメールアドレスを入力してください")
    with session.no_autoflush:
        duplicate = session.exec(select(ParentAccount).where(
            func.lower(ParentAccount.email) == email.lower(),
            ParentAccount.id != account_id if account_id is not None else True,
        )).first()
    if duplicate:
        raise HTTPException(400, "このメールアドレスは別の保護者アカウントで利用されています")
    return email


def guardian_account_values(family: Family, profile: dict[str, Any]) -> dict[str, Any]:
    """Prefill a registration form; this does not create an account or grant access."""
    kana = " ".join(normalized_text(profile.get(key)) for key in ("last_name_kana", "first_name_kana")).strip()
    return {
        "display_name": f"{profile['last_name']} {profile['first_name']}",
        **{key: normalized_text(profile.get(key)) for key in SHARED_ACCOUNT_FIELDS},
        "home_address": family.home_address or "",
        "registration_verification_name": kana,
        "registration_verification_name_type": "kana" if kana else "",
    }


def sync_family_to_parent_accounts(session: Session, family: Family, *, previous_address: str | None, previous_account_ids: set) -> None:
    from parent_auth import cancel_open_parent_registrations

    profiles = [dict(item) for item in family.guardian_profiles()]
    seen: set[int] = set()
    for profile in profiles:
        account_id = _normalized_parent_account_id(profile.get("parent_account_id"))
        if account_id is None:
            continue
        account = session.get(ParentAccount, account_id)
        if account is None or account.family_id != family.id or account_id in seen:
            raise HTTPException(400, "保護者アカウントの紐付けを家族の編集画面で確認してください")
        seen.add(account_id)
        old_email = account.email
        if account.id not in previous_account_ids:
            for key in SHARED_ACCOUNT_FIELDS:
                if not normalized_text(profile.get(key)):
                    profile[key] = getattr(account, key) or ""
        # An empty ledger email must not erase the account's required address.
        profile["email"] = validate_parent_contact_email(session, profile.get("email") or account.email, account.id)
        account.display_name = f"{profile['last_name']} {profile['first_name']}"
        for key in SHARED_ACCOUNT_FIELDS:
            setattr(account, key, normalized_optional_text(profile.get(key)))
        # Preserve an explicitly different address (for example a separate household).
        if not account.home_address or normalized_text(account.home_address) == normalized_text(previous_address):
            account.home_address = family.home_address
        if old_email != account.email:
            cancel_open_parent_registrations(session, account.id)
        account.updated_at = family.updated_at
        session.add(account)
    family.shared_profile = {"guardians": profiles}
    session.add(family)


def sync_parent_account_to_family(session: Session, account: ParentAccount, *, previous_address: str | None = None) -> None:
    family = session.get(Family, account.family_id) if account.family_id else None
    if family is None:
        return
    profiles = [dict(item) for item in family.guardian_profiles()]
    linked = [item for item in profiles if _normalized_parent_account_id(item.get("parent_account_id")) == account.id]
    if len(linked) > 1:
        raise HTTPException(400, "同じアカウントが複数の保護者へ紐付いています。家族の編集画面で確認してください")
    if not linked:
        return
    profile = linked[0]
    parts = account.display_name.split(maxsplit=1)
    if len(parts) == 2:
        profile["last_name"], profile["first_name"] = parts
    elif _identity_key(account.display_name) != _identity_key(f"{profile['last_name']} {profile['first_name']}"):
        raise HTTPException(400, "家族と紐付ける保護者の氏名は、姓と名をスペースで区切ってください")
    profile.update({key: getattr(account, key) or "" for key in SHARED_ACCOUNT_FIELDS})
    family.shared_profile = {"guardians": profiles}
    if normalized_text(previous_address) == normalized_text(family.home_address):
        old_address = family.home_address
        family.home_address = account.home_address
        for other in session.exec(select(ParentAccount).where(ParentAccount.family_id == family.id)).all():
            if other.id != account.id and normalized_text(other.home_address) == normalized_text(old_address):
                other.home_address = family.home_address
                other.updated_at = utc_now()
                session.add(other)
    family.updated_at = utc_now()
    session.add(family)
    session.flush()
    sync_family_to_children(session, family)


def bind_parent_account_guardian(session: Session, account: ParentAccount, link: str | None, *, old_family_id: int | None = None) -> None:
    """Bind only an explicitly selected guardian; never infer child permissions."""
    if link == "none":
        link = ""
    target_order = None
    if link:
        try:
            target_family_id, target_order = map(int, link.split(":"))
        except (ValueError, TypeError):
            raise HTTPException(400, "紐付ける家族の保護者を選び直してください") from None
        if target_family_id != account.family_id:
            raise HTTPException(400, "所属家族と紐付ける保護者の家族が一致していません")
        family = session.get(Family, target_family_id)
        matches = [item for item in family.guardian_profiles() if item.get("order") == target_order] if family else []
        if len(matches) != 1 or matches[0].get("parent_account_id") not in (None, account.id):
            raise HTTPException(400, "この保護者は既に別のアカウントと紐付いているか、変更されています")
    for family_id in {value for value in (old_family_id, account.family_id) if value is not None}:
        family = session.get(Family, family_id)
        if not family:
            raise HTTPException(400, "所属家族が見つかりません")
        profiles = [dict(item) for item in family.guardian_profiles()]
        for profile in profiles:
            if profile.get("parent_account_id") == account.id and (link is not None or family_id != account.family_id):
                profile["parent_account_id"] = None
            if family_id == account.family_id and target_order == profile.get("order"):
                profile["parent_account_id"] = account.id
        family.shared_profile = {"guardians": profiles}
        session.add(family)
        session.flush()
        sync_family_to_children(session, family)


def create_family_for_child(
    session: Session,
    child: Child,
    *,
    family_name: Optional[str] = None,
    parent_accounts: Optional[list[ParentAccount]] = None,
) -> Family:
    current_family = session.get(Family, child.family_id) if child.family_id else None
    if current_family:
        return current_family

    accounts = parent_accounts or []
    family = Family(
        family_name=family_name or infer_family_name([child], accounts),
        home_address=child.home_address,
        home_phone=child.home_phone,
        shared_profile={"guardians": guardian_profiles_from_child(child)},
    )
    session.add(family)
    session.flush()

    child.family_id = family.id
    child.updated_at = utc_now()
    session.add(child)

    for account in accounts:
        account.family_id = family.id
        account.updated_at = utc_now()
        session.add(account)

    session.flush()
    sync_family_to_children(session, family, updated_at=family.updated_at)
    sync_parent_child_links(session, family)
    return family


def move_child_to_family(session: Session, child: Child, family: Family) -> None:
    if child.family_id == family.id:
        return
    child.family_id = family.id
    child.updated_at = utc_now()
    session.add(child)
    session.flush()
    sync_family_to_children(session, family, updated_at=child.updated_at)
    sync_parent_child_links(session, family)


def _new_family_from_members(session: Session, children: list[Child], parent_accounts: list[ParentAccount]) -> Family:
    base_child = children[0] if children else None
    family = Family(
        family_name=infer_family_name(children, parent_accounts),
        home_address=base_child.home_address if base_child and base_child.home_address else None,
        home_phone=base_child.home_phone if base_child and base_child.home_phone else None,
        shared_profile={"guardians": guardian_profiles_from_child(base_child)} if base_child else {"guardians": []},
    )
    session.add(family)
    session.flush()
    return family


def bootstrap_family_data(session: Session) -> None:
    children = session.exec(
        select(Child)
        .options(selectinload(Child.guardians), selectinload(Child.parent_links))
        .order_by(Child.id)
    ).all()
    accounts = session.exec(
        select(ParentAccount)
        .options(selectinload(ParentAccount.child_links))
        .order_by(ParentAccount.id)
    ).all()
    if not children and not accounts:
        return

    children_by_id = {child.id: child for child in children if child.id is not None}
    accounts_by_id = {account.id: account for account in accounts if account.id is not None}
    visited_children: set[int] = set()
    visited_accounts: set[int] = set()
    touched_family_ids: set[int] = set()

    def explore(start_child_id: Optional[int], start_account_id: Optional[int]) -> tuple[list[Child], list[ParentAccount]]:
        queue: deque[tuple[str, int]] = deque()
        if start_child_id is not None:
            queue.append(("child", start_child_id))
        if start_account_id is not None:
            queue.append(("account", start_account_id))
        component_children: list[Child] = []
        component_accounts: list[ParentAccount] = []

        while queue:
            kind, item_id = queue.popleft()
            if kind == "child":
                if item_id in visited_children:
                    continue
                visited_children.add(item_id)
                child = children_by_id.get(item_id)
                if not child:
                    continue
                component_children.append(child)
                for link in child.parent_links:
                    if link.parent_account_id is not None:
                        queue.append(("account", link.parent_account_id))
            else:
                if item_id in visited_accounts:
                    continue
                visited_accounts.add(item_id)
                account = accounts_by_id.get(item_id)
                if not account:
                    continue
                component_accounts.append(account)
                for link in account.child_links:
                    if link.child_id is not None:
                        queue.append(("child", link.child_id))

        return component_children, component_accounts

    for child in children:
        if child.id in visited_children:
            continue
        component_children, component_accounts = explore(child.id, None)
        if not component_children and not component_accounts:
            continue

        existing_family_ids = sorted(
            {
                item.family_id
                for item in [*component_children, *component_accounts]
                if getattr(item, "family_id", None) is not None
            }
        )
        family = session.get(Family, existing_family_ids[0]) if existing_family_ids else None
        if not family:
            family = _new_family_from_members(session, component_children, component_accounts)

        if not family.family_name:
            family.family_name = infer_family_name(component_children, component_accounts)
        if not family.home_address:
            family.home_address = next((child.home_address for child in component_children if child.home_address), None)
        if not family.home_phone:
            family.home_phone = next((child.home_phone for child in component_children if child.home_phone), None)
        if not isinstance(family.shared_profile, dict) or "guardians" not in family.shared_profile:
            base_child = component_children[0] if component_children else None
            family.shared_profile = {"guardians": guardian_profiles_from_child(base_child)} if base_child else {"guardians": []}

        family.updated_at = utc_now()
        session.add(family)
        session.flush()

        for component_child in component_children:
            if component_child.family_id != family.id:
                component_child.family_id = family.id
                component_child.updated_at = utc_now()
                session.add(component_child)
        for component_account in component_accounts:
            if component_account.family_id != family.id:
                component_account.family_id = family.id
                component_account.updated_at = utc_now()
                session.add(component_account)

        touched_family_ids.add(family.id)

    for account in accounts:
        if account.id in visited_accounts:
            continue
        component_children, component_accounts = explore(None, account.id)
        if not component_children and not component_accounts:
            continue
        existing_family_ids = sorted(
            {
                item.family_id
                for item in [*component_children, *component_accounts]
                if getattr(item, "family_id", None) is not None
            }
        )
        family = session.get(Family, existing_family_ids[0]) if existing_family_ids else None
        if not family:
            family = _new_family_from_members(session, component_children, component_accounts)
        for component_account in component_accounts:
            if component_account.family_id != family.id:
                component_account.family_id = family.id
                component_account.updated_at = utc_now()
                session.add(component_account)
        for component_child in component_children:
            if component_child.family_id != family.id:
                component_child.family_id = family.id
                component_child.updated_at = utc_now()
                session.add(component_child)
        touched_family_ids.add(family.id)

    for family_id in sorted(touched_family_ids):
        family = session.exec(
            select(Family)
            .options(selectinload(Family.children), selectinload(Family.parent_accounts))
            .where(Family.id == family_id)
        ).first()
        if not family:
            continue
        backfill_family_guardian_account_links(session, family)
        sync_family_to_children(session, family, updated_at=utc_now())
        sync_parent_child_links(session, family)
