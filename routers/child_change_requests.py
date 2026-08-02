from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from auth import get_current_staff_user, require_child_record_manager
from child_profile_changes import (
    apply_child_profile_payload,
    build_child_profile_change_details,
    merge_child_profile_form_data,
    resolve_child_profile_change_payload,
)
from child_profile_history import (
    build_child_profile_snapshot,
    ensure_initial_child_profile_history,
    record_child_profile_history,
)
from database import get_session, seed_classroom_data
from models import (
    Child,
    ChildProfileChangeRequest,
    ChildProfileChangeRequestStatus,
    Family,
    ParentAccount,
)
from time_utils import utc_now

router = APIRouter(prefix="/child-change-requests", tags=["child_change_requests"])
from template_utils import create_templates

templates = create_templates()


def _display_change_details(change_request: ChildProfileChangeRequest, child: Optional[Child]) -> dict:
    details = change_request.change_details or {}
    if isinstance(details, dict) and details and all(
        isinstance(detail, dict) and {"label", "old", "new"}.issubset(detail)
        for detail in details.values()
    ):
        return details

    if child:
        payload = resolve_child_profile_change_payload(child, change_request.request_data)
        if payload:
            resolved_details = build_child_profile_change_details(child, payload)
            if resolved_details:
                return resolved_details

    if isinstance(details, dict) and ("before" in details or "after" in details):
        return {
            "legacy_phone": {
                "label": "緊急連絡先",
                "old": details.get("before") or "未登録",
                "new": details.get("after") or "未登録",
            }
        }
    return {}


def _parse_status_filter(raw_status: Optional[str]) -> Optional[ChildProfileChangeRequestStatus]:
    if not raw_status or raw_status == "all":
        return None
    try:
        return ChildProfileChangeRequestStatus(raw_status)
    except ValueError:
        return ChildProfileChangeRequestStatus.pending


def _load_change_request(session: Session, request_id: int) -> ChildProfileChangeRequest:
    change_request = session.exec(
        select(ChildProfileChangeRequest)
        .options(
            selectinload(ChildProfileChangeRequest.child).selectinload(Child.guardians),
            selectinload(ChildProfileChangeRequest.child).selectinload(Child.classroom),
            selectinload(ChildProfileChangeRequest.child).selectinload(Child.family).selectinload(Family.children),
            selectinload(ChildProfileChangeRequest.parent_account),
        )
        .where(ChildProfileChangeRequest.id == request_id)
    ).first()
    if not change_request:
        raise HTTPException(status_code=404, detail="変更申請が見つかりません")
    return change_request


@router.get("/", response_class=HTMLResponse)
def child_change_request_list(
    request: Request,
    status: str = Query(default="pending"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_child_record_manager(current_user)
    status_filter = _parse_status_filter(status)

    statement = (
        select(ChildProfileChangeRequest)
        .options(
            selectinload(ChildProfileChangeRequest.child).selectinload(Child.classroom),
            selectinload(ChildProfileChangeRequest.child).selectinload(Child.family).selectinload(Family.children),
            selectinload(ChildProfileChangeRequest.parent_account),
        )
        .order_by(ChildProfileChangeRequest.submitted_at.desc())
    )
    if status_filter:
        statement = statement.where(ChildProfileChangeRequest.status == status_filter)

    change_requests = session.exec(statement).all()
    pending_count = session.exec(
        select(ChildProfileChangeRequest).where(
            ChildProfileChangeRequest.status == ChildProfileChangeRequestStatus.pending
        )
    ).all()

    return templates.TemplateResponse(
        request,
        "child_change_requests/list.html",
        {
            "request": request,
            "current_user": current_user,
            "change_requests": change_requests,
            "current_status": status,
            "pending_count": len(pending_count),
            "status_options": [
                ("pending", "承認待ち"),
                ("approved", "承認済み"),
                ("rejected", "差し戻し"),
                ("all", "すべて"),
            ],
        },
    )


@router.get("/{request_id}", response_class=HTMLResponse)
def child_change_request_detail(
    request: Request,
    request_id: int,
    notice: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_child_record_manager(current_user)
    change_request = _load_change_request(session, request_id)
    child = change_request.child
    current_form_data = merge_child_profile_form_data(child) if child else {}
    display_change_details = _display_change_details(change_request, child)
    approvable_details = {}
    if child:
        approval_payload = resolve_child_profile_change_payload(child, change_request.request_data)
        if approval_payload:
            approvable_details = build_child_profile_change_details(child, approval_payload)
    notice_message = {
        "approved": "変更申請を承認し、園児情報へ反映しました。",
        "rejected": "変更申請を差し戻しました。",
        "invalid": "変更内容が空のため承認できません。内容を確認して差し戻してください。",
    }.get(notice or "", "")

    return templates.TemplateResponse(
        request,
        "child_change_requests/detail.html",
        {
            "request": request,
            "current_user": current_user,
            "change_request": change_request,
            "current_form_data": current_form_data,
            "display_change_details": display_change_details,
            "can_approve": bool(approvable_details),
            "notice": notice_message,
            "notice_is_error": notice == "invalid",
        },
    )


@router.post("/{request_id}/approve")
def approve_child_change_request(
    request_id: int,
    review_note: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_child_record_manager(current_user)
    change_request = _load_change_request(session, request_id)
    if change_request.status != ChildProfileChangeRequestStatus.pending:
        return RedirectResponse(url=f"/child-change-requests/{request_id}", status_code=303)

    child = session.exec(
        select(Child)
        .options(selectinload(Child.guardians), selectinload(Child.family))
        .where(Child.id == change_request.child_id)
    ).first()
    if not child:
        raise HTTPException(status_code=404, detail="園児が見つかりません")

    previous_snapshot = build_child_profile_snapshot(session, child)
    ensure_initial_child_profile_history(session, child, snapshot=previous_snapshot)

    payload = resolve_child_profile_change_payload(child, change_request.request_data)
    if not payload:
        return RedirectResponse(
            url=f"/child-change-requests/{request_id}?notice=invalid",
            status_code=303,
        )

    change_details = build_child_profile_change_details(child, payload)
    if not change_details:
        return RedirectResponse(
            url=f"/child-change-requests/{request_id}?notice=invalid",
            status_code=303,
        )

    try:
        apply_child_profile_payload(
            session,
            child,
            payload,
            applied_at=utc_now(),
        )
    except ValueError:
        return RedirectResponse(
            url=f"/child-change-requests/{request_id}?notice=invalid",
            status_code=303,
        )

    change_request.request_data = payload
    change_request.change_details = change_details
    change_request.status = ChildProfileChangeRequestStatus.approved
    change_request.review_note = (review_note or "").strip() or None
    change_request.reviewed_at = utc_now()
    change_request.reviewed_by = current_user.name
    change_request.updated_at = utc_now()
    session.add(change_request)
    record_child_profile_history(
        session,
        child,
        actor_name=current_user.name,
        previous_snapshot=previous_snapshot,
        source="parent_request",
        requester_name=(
            change_request.parent_account.display_name
            if change_request.parent_account
            else "保護者"
        ),
    )
    session.commit()
    seed_classroom_data(session.get_bind())

    return RedirectResponse(url=f"/child-change-requests/{request_id}?notice=approved", status_code=303)


@router.post("/{request_id}/reject")
def reject_child_change_request(
    request_id: int,
    review_note: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_child_record_manager(current_user)
    change_request = _load_change_request(session, request_id)
    if change_request.status != ChildProfileChangeRequestStatus.pending:
        return RedirectResponse(url=f"/child-change-requests/{request_id}", status_code=303)

    change_request.status = ChildProfileChangeRequestStatus.rejected
    change_request.review_note = (review_note or "").strip() or None
    change_request.reviewed_at = utc_now()
    change_request.reviewed_by = current_user.name
    change_request.updated_at = utc_now()
    session.add(change_request)
    session.commit()

    return RedirectResponse(url=f"/child-change-requests/{request_id}?notice=rejected", status_code=303)
