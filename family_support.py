from __future__ import annotations

from collections import Counter, deque
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from models import Child, Family, Guardian, ParentAccount, ParentChildLink
from time_utils import utc_now

DEFAULT_RELATIONSHIP_1 = "母"
DEFAULT_RELATIONSHIP_2 = "父"
GUARDIAN_FIELD_NAMES = (
    "last_name",
    "first_name",
    "last_name_kana",
    "first_name_kana",
    "relationship",
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
            flattened[f"{prefix}_{field_name}"] = str(guardian.get(field_name, ""))
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
    child_ids = [
        child.id
        for child in session.exec(select(Child).where(Child.family_id == family.id)).all()
        if child.id is not None
    ]
    account_ids = [
        account.id
        for account in session.exec(select(ParentAccount).where(ParentAccount.family_id == family.id)).all()
        if account.id is not None
    ]
    if not child_ids and not account_ids:
        return

    existing_links = session.exec(
        select(ParentChildLink).where(
            or_(
                ParentChildLink.child_id.in_(child_ids) if child_ids else False,
                ParentChildLink.parent_account_id.in_(account_ids) if account_ids else False,
            )
        )
    ).all()

    fallback_label_by_parent: dict[int, str] = {}
    fallback_primary_by_parent: dict[int, bool] = {}
    pair_settings: dict[tuple[int, int], tuple[str, bool]] = {}
    for link in existing_links:
        fallback_label_by_parent.setdefault(link.parent_account_id, link.relationship_label or "保護者")
        fallback_primary_by_parent.setdefault(link.parent_account_id, link.is_primary_contact)
        pair_settings[(link.parent_account_id, link.child_id)] = (
            link.relationship_label or "保護者",
            link.is_primary_contact,
        )
        session.delete(link)
    session.flush()

    if not child_ids or not account_ids:
        return

    primary_parent_id = sorted(account_ids)[0]
    for parent_id in sorted(account_ids):
        default_label = fallback_label_by_parent.get(parent_id, "保護者")
        default_primary = fallback_primary_by_parent.get(parent_id, parent_id == primary_parent_id)
        for child_id in sorted(child_ids):
            label, is_primary = pair_settings.get((parent_id, child_id), (default_label, default_primary))
            session.add(
                ParentChildLink(
                    parent_account_id=parent_id,
                    child_id=child_id,
                    relationship_label=label,
                    is_primary_contact=is_primary,
                )
            )


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
        for guardian in list(child.guardians):
            session.delete(guardian)
        child.guardians.clear()

        child.home_address = family.home_address
        child.home_phone = family.home_phone
        child.updated_at = now
        session.add(child)
        session.flush()

        for profile in guardian_profiles:
            child.guardians.append(
                Guardian(
                    child_id=child.id,
                    last_name=normalized_text(str(profile.get("last_name", ""))),
                    first_name=normalized_text(str(profile.get("first_name", ""))),
                    last_name_kana=normalized_optional_text(str(profile.get("last_name_kana", ""))),
                    first_name_kana=normalized_optional_text(str(profile.get("first_name_kana", ""))),
                    relationship=normalized_text(str(profile.get("relationship", ""))) or "保護者",
                    phone=normalized_optional_text(str(profile.get("phone", ""))),
                    workplace=normalized_optional_text(str(profile.get("workplace", ""))),
                    workplace_address=normalized_optional_text(str(profile.get("workplace_address", ""))),
                    workplace_phone=normalized_optional_text(str(profile.get("workplace_phone", ""))),
                    order=int(profile.get("order", 1)),
                )
            )
        session.add(child)
        session.flush()


def apply_family_shared_data(
    session: Session,
    family: Family,
    payload: dict[str, Any],
    *,
    updated_at: Optional[datetime] = None,
) -> dict[str, Any]:
    normalized = normalize_family_payload(payload)
    family.family_name = normalized["family_name"] or family.family_name
    family.home_address = normalized_optional_text(normalized["home_address"])
    family.home_phone = normalized_optional_text(normalized["home_phone"])
    family.shared_profile = {"guardians": normalized["guardians_data"]}
    family.updated_at = updated_at or utc_now()
    session.add(family)
    session.flush()
    sync_family_to_children(session, family, updated_at=family.updated_at)
    sync_parent_child_links(session, family)
    return normalized


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
        sync_family_to_children(session, family, updated_at=utc_now())
        sync_parent_child_links(session, family)
