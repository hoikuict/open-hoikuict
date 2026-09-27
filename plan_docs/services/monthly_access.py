"""Monthly body editing requires an assignment overlapping the target month."""
import calendar
from datetime import date

from fastapi import HTTPException
from sqlmodel import select

from models import Classroom, StaffClassroomAssignment, User
from .monthly_library import month_date

EDIT_REASON = "閲覧のみ：対象月の担当クラスの割当が必要です。管理者も同じ条件です。"


def can_edit_monthly(session, user, classroom_id, target_month):
    if not user.can_edit or not user.user_id or not user.actor_ref:
        return False
    staff = session.get(User, user.user_id, populate_existing=True)
    if not staff or not staff.is_active or staff.staff_role not in {"admin", "can_edit"}:
        return False
    start = month_date(target_month)
    end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
    return session.exec(select(StaffClassroomAssignment.id).where(
        StaffClassroomAssignment.staff_user_id == user.user_id,
        StaffClassroomAssignment.classroom_id == classroom_id,
        StaffClassroomAssignment.starts_on <= end,
        (StaffClassroomAssignment.ends_on.is_(None) | (StaffClassroomAssignment.ends_on >= start)),
    ).limit(1)).first() is not None


def classroom_id_for_ref(session, classroom_ref):
    matches = session.exec(select(Classroom.id).where(Classroom.name == classroom_ref)).all()
    return matches[0] if len(matches) == 1 else None


def require_monthly_edit(session, user, classroom_id, target_month):
    if not can_edit_monthly(session, user, classroom_id, target_month):
        raise HTTPException(403, EDIT_REASON + " 入力内容は保持されています。")


def can_edit_monthly_document(session, user, document):
    classroom_id = (document.monthly_sheet["classroom_id"] if document.monthly_sheet
                    else classroom_id_for_ref(session, document.classroom_ref))
    return bool(classroom_id and document.target_month and
                can_edit_monthly(session, user, classroom_id, document.target_month))
