from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from auth import get_optional_current_staff_user
from calendar_service import localize_datetime
from database import get_session
from models import User
from plan_docs.auth_adapter import DEFAULT_NURSERY_REF
from plan_docs.contracts import DOCUMENT_TYPE_LABELS
from plan_docs.services.review_notifications import (
    REVIEW_OUTCOME,
    list_pending_review_documents,
    list_review_notifications,
)
from staff_portal_service import (
    build_attendance_summaries,
    build_schedule_items,
    build_timeline_messages,
    build_unanswered_survey_items,
    classroom_scope,
    format_portal_date,
    greeting_for,
    next_schedule_item,
)
from template_utils import create_templates
from time_utils import local_now, utc_now


router = APIRouter(tags=["staff-portal"])
templates = create_templates()
logger = logging.getLogger(__name__)


def _no_store(response):
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _render_login_prompt(request: Request):
    current = local_now()
    response = templates.TemplateResponse(
        request,
        "portal/login_prompt.html",
        {
            "request": request,
            "current_time": current.strftime("%H:%M"),
            "timezone_name": "Asia/Tokyo",
        },
    )
    return _no_store(response)


def _render_staff_home(
    request: Request,
    *,
    current_user,
    staff_user: User,
    session: Session,
    scope: str,
):
    now = utc_now()
    local_current = localize_datetime(now, staff_user.timezone)
    target_date = local_current.date()
    show_all = staff_user.staff_role == "admin" and scope == "all"

    assignment_views = []
    classrooms = []
    attendance_summaries = []
    schedule_items = []
    timeline_messages = []
    attendance_error = ""
    schedule_error = ""
    attention_error = ""
    timeline_error = ""
    plan_notification_error = ""
    schedule_remaining_count = 0
    survey_pending_count = 0
    plan_notifications = []
    pending_plan_documents = []

    try:
        classrooms, assignment_views = classroom_scope(
            session,
            staff_user,
            target_date,
            show_all=show_all,
        )
        if staff_user.staff_role == "admin" and not assignment_views:
            show_all = True
        attendance_summaries = build_attendance_summaries(
            session,
            classrooms[:3] if not show_all else classrooms,
            target_date,
            attention_limit=0,
        )
    except Exception:
        logger.exception("staff portal attendance load failed", extra={"staff_user_id": str(staff_user.id)})
        attendance_error = "出席情報を取得できませんでした。再読み込みしてください。"

    try:
        schedule_items, schedule_remaining_count = build_schedule_items(
            session,
            staff_user,
            target_date,
            now,
        )
    except Exception:
        logger.exception("staff portal schedule load failed", extra={"staff_user_id": str(staff_user.id)})
        schedule_error = "予定を取得できませんでした。再読み込みしてください。"

    try:
        _survey_items, survey_pending_count = build_unanswered_survey_items(
            session,
            staff_user,
            now,
        )
    except Exception:
        logger.exception("staff portal attention load failed", extra={"staff_user_id": str(staff_user.id)})
        attention_error = "要確認情報を取得できませんでした。再読み込みしてください。"

    try:
        timeline_messages = build_timeline_messages(session)
    except Exception:
        logger.exception("staff portal timeline load failed", extra={"staff_user_id": str(staff_user.id)})
        timeline_error = "タイムラインを取得できませんでした。再読み込みしてください。"

    try:
        nursery_ref = os.getenv("HOIKU_NURSERY_REF", DEFAULT_NURSERY_REF)
        plan_notifications = list_review_notifications(
            session,
            recipient_user_id=staff_user.id,
            nursery_ref=nursery_ref,
        )
        if staff_user.staff_role == "admin":
            pending_plan_documents = list_pending_review_documents(
                session,
                nursery_ref=nursery_ref,
            )
            # Review requests are represented by the authoritative queue above.
            plan_notifications = [
                notification
                for notification in plan_notifications
                if notification.notification_kind == REVIEW_OUTCOME
            ]
    except Exception:
        logger.exception(
            "staff portal plan notification load failed",
            extra={"staff_user_id": str(staff_user.id)},
        )
        plan_notification_error = "帳票通知を取得できませんでした。再読み込みしてください。"

    attendance_attention_count = sum(item.attention_count for item in attendance_summaries)
    attention_count = attendance_attention_count + survey_pending_count
    assignment_names = [item.classroom.name for item in assignment_views]
    display_assignment_names = assignment_names[:3]
    assignment_remaining_count = max(len(assignment_names) - len(display_assignment_names), 0)
    classroom_remaining_count = max(len(classrooms) - len(attendance_summaries), 0)

    response = templates.TemplateResponse(
        request,
        "portal/index.html",
        {
            "request": request,
            "current_user": current_user,
            "staff_record": staff_user,
            "greeting": greeting_for(local_current),
            "portal_date": format_portal_date(target_date),
            "target_date": target_date,
            "updated_time": local_current.strftime("%H:%M"),
            "assignment_names": display_assignment_names,
            "assignment_remaining_count": assignment_remaining_count,
            "attendance_summaries": attendance_summaries,
            "classroom_remaining_count": classroom_remaining_count,
            "attendance_error": attendance_error,
            "schedule_items": schedule_items,
            "schedule_remaining_count": schedule_remaining_count,
            "schedule_error": schedule_error,
            "next_schedule": next_schedule_item(schedule_items),
            "attention_count": attention_count,
            "attention_error": attention_error,
            "attention_url": "/staff/attention?scope=all" if show_all else "/staff/attention",
            "timeline_messages": timeline_messages,
            "timeline_error": timeline_error,
            "plan_notifications": plan_notifications,
            "unread_plan_notification_count": sum(
                1 for notification in plan_notifications if notification.read_at is None
            ),
            "plan_notification_error": plan_notification_error,
            "pending_plan_documents": pending_plan_documents,
            "pending_plan_document_count": len(pending_plan_documents),
            "plan_document_type_labels": {
                document_type.value: label
                for document_type, label in DOCUMENT_TYPE_LABELS.items()
            },
            "present_count": sum(item.present_count for item in attendance_summaries),
            "show_all": show_all,
            "can_show_all": staff_user.staff_role == "admin",
        },
    )
    return _no_store(response)


def _render_staff_attention(
    request: Request,
    *,
    current_user,
    staff_user: User,
    session: Session,
    scope: str,
):
    now = utc_now()
    local_current = localize_datetime(now, staff_user.timezone)
    target_date = local_current.date()
    show_all = staff_user.staff_role == "admin" and scope == "all"
    error_message = ""
    attendance_items = []
    survey_items = []

    try:
        classrooms, assignment_views = classroom_scope(
            session,
            staff_user,
            target_date,
            show_all=show_all,
        )
        if staff_user.staff_role == "admin" and not assignment_views:
            show_all = True
            classrooms, assignment_views = classroom_scope(
                session,
                staff_user,
                target_date,
                show_all=True,
            )
        summaries = build_attendance_summaries(
            session,
            classrooms,
            target_date,
            attention_limit=None,
        )
        attendance_items = [
            detail
            for summary in summaries
            for detail in summary.attention_items
        ]
        survey_items, _pending_count = build_unanswered_survey_items(
            session,
            staff_user,
            now,
            limit=None,
        )
    except Exception:
        logger.exception("staff attention page load failed", extra={"staff_user_id": str(staff_user.id)})
        error_message = "要確認情報を取得できませんでした。再読み込みしてください。"

    attention_items = attendance_items + survey_items
    response = templates.TemplateResponse(
        request,
        "portal/attention.html",
        {
            "request": request,
            "current_user": current_user,
            "staff_record": staff_user,
            "portal_date": format_portal_date(target_date),
            "attention_items": attention_items,
            "attention_count": len(attention_items),
            "attendance_attention_count": len(attendance_items),
            "survey_attention_count": len(survey_items),
            "attention_error": error_message,
            "show_all": show_all,
            "can_show_all": staff_user.staff_role == "admin",
        },
    )
    return _no_store(response)


def _portal_response(
    request: Request,
    *,
    current_user,
    session: Session,
    scope: str,
):
    if current_user is None or current_user.user_id is None:
        return _render_login_prompt(request)
    staff_user = session.get(User, current_user.user_id)
    if staff_user is None or not staff_user.is_active:
        return _render_login_prompt(request)
    return _render_staff_home(
        request,
        current_user=current_user,
        staff_user=staff_user,
        session=session,
        scope=scope,
    )


@router.get("/", response_class=HTMLResponse)
def portal_home(
    request: Request,
    scope: str = Query(default="assigned"),
    current_user=Depends(get_optional_current_staff_user),
    session: Session = Depends(get_session),
):
    return _portal_response(
        request,
        current_user=current_user,
        session=session,
        scope=scope,
    )


@router.get("/staff/portal", response_class=HTMLResponse)
def staff_portal_alias(
    request: Request,
    scope: str = Query(default="assigned"),
    current_user=Depends(get_optional_current_staff_user),
    session: Session = Depends(get_session),
):
    if current_user is None or current_user.user_id is None:
        return RedirectResponse(url="/staff/login?redirect=/staff/portal", status_code=303)
    return _portal_response(
        request,
        current_user=current_user,
        session=session,
        scope=scope,
    )


@router.get("/staff/attention", response_class=HTMLResponse)
def staff_attention(
    request: Request,
    scope: str = Query(default="assigned"),
    current_user=Depends(get_optional_current_staff_user),
    session: Session = Depends(get_session),
):
    if current_user is None or current_user.user_id is None:
        return RedirectResponse(url="/staff/login?redirect=/staff/attention", status_code=303)
    staff_user = session.get(User, current_user.user_id)
    if staff_user is None or not staff_user.is_active:
        return RedirectResponse(url="/staff/login?redirect=/staff/attention", status_code=303)
    return _render_staff_attention(
        request,
        current_user=current_user,
        staff_user=staff_user,
        session=session,
        scope=scope,
    )
