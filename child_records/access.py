from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from models import Child, StaffClassroomAssignment
from time_utils import local_today


PROGRESS_VIEW_ASSIGNED_CLASS = "assigned_class"
PROGRESS_VIEW_ALL_STAFF = "all_staff"
PROGRESS_VIEW_SCOPES = {
    PROGRESS_VIEW_ASSIGNED_CLASS,
    PROGRESS_VIEW_ALL_STAFF,
}


def progress_record_view_scope(config: dict[str, Any]) -> str:
    value = str(
        config.get("access_policy", {}).get(
            "progress_record_view_scope",
            PROGRESS_VIEW_ASSIGNED_CLASS,
        )
    )
    if value not in PROGRESS_VIEW_SCOPES:
        return PROGRESS_VIEW_ASSIGNED_CLASS
    return value


def has_assigned_child_access(session: Session, user: Any, child: Child) -> bool:
    if bool(getattr(user, "is_admin", False)) or bool(
        getattr(user, "can_manage_child_records", False)
    ):
        return True
    staff_id = getattr(user, "user_id", None) or getattr(user, "staff_id", None)
    if staff_id is None or child.classroom_id is None:
        return False
    today = local_today()
    assignment = session.exec(
        select(StaffClassroomAssignment).where(
            StaffClassroomAssignment.staff_user_id == staff_id,
            StaffClassroomAssignment.classroom_id == child.classroom_id,
            StaffClassroomAssignment.starts_on <= today,
            (
                StaffClassroomAssignment.ends_on.is_(None)
                | (StaffClassroomAssignment.ends_on >= today)
            ),
        )
    ).first()
    return assignment is not None


def can_view_observation_records(session: Session, user: Any, child: Child) -> bool:
    return has_assigned_child_access(session, user, child)


def can_view_progress_records(
    session: Session,
    user: Any,
    child: Child,
    config: dict[str, Any],
) -> bool:
    if progress_record_view_scope(config) == PROGRESS_VIEW_ALL_STAFF:
        return True
    return has_assigned_child_access(session, user, child)


def can_create_progress_record(session: Session, user: Any, child: Child) -> bool:
    return bool(getattr(user, "can_edit", False)) and has_assigned_child_access(
        session,
        user,
        child,
    )
