from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from fastapi import HTTPException
from sqlmodel import Session

from auth import StaffUser
from models import StaffPermissionChangeLog, User


@dataclass(frozen=True, slots=True)
class StaffPermissionDefinition:
    key: str
    label: str
    description: str


STAFF_PERMISSION_DEFINITIONS = (
    StaffPermissionDefinition(
        key="can_manage_child_records",
        label="園児台帳管理",
        description="園児・家族・保護者アカウントの追加と編集を許可します。",
    ),
    StaffPermissionDefinition(
        key="can_manage_billing_accounts",
        label="請求・口座情報管理",
        description="家族の支払方法、口座振替状態、銀行・支店・口座情報の閲覧と編集を許可します。",
    ),
)


def get_live_staff_user(session: Session, current_user: StaffUser) -> User | None:
    if current_user.user_id is None:
        return None
    user = session.get(User, current_user.user_id)
    if user is None or not user.is_active:
        return None
    return user


def require_live_admin(session: Session, current_user: StaffUser) -> User:
    user = get_live_staff_user(session, current_user)
    if user is None or user.staff_role != "admin":
        raise HTTPException(status_code=403, detail="管理者権限が必要です")
    return user


def can_manage_billing_accounts(session: Session, current_user: StaffUser) -> bool:
    user = get_live_staff_user(session, current_user)
    return bool(user and user.can_manage_billing_accounts_effective)


def require_billing_account_manager(session: Session, current_user: StaffUser) -> User:
    user = get_live_staff_user(session, current_user)
    if user is None or not user.can_manage_billing_accounts_effective:
        raise HTTPException(status_code=403, detail="請求・口座情報管理権限が必要です")
    return user


def add_permission_change_logs(
    session: Session,
    *,
    target_user: User,
    actor: User,
    changes: Iterable[tuple[str, object, object]],
) -> None:
    for permission_key, old_value, new_value in changes:
        if old_value == new_value:
            continue
        session.add(
            StaffPermissionChangeLog(
                target_user_id=target_user.id,
                permission_key=permission_key,
                old_value=_audit_value(old_value),
                new_value=_audit_value(new_value),
                changed_by_user_id=actor.id,
                changed_by_name_snapshot=actor.display_name,
            )
        )


def _audit_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)
