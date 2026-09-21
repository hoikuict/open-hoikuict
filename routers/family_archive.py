from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from auth import get_current_staff_user
from csrf import verify_csrf
from database import get_session
from family_archive import (
    REASONS,
    FamilyArchiveError,
    archive_blockers,
    issue_archive_review,
    require_archive_manager,
    transition_family,
)
from family_deletion import dependency_counts
from models import (
    Child,
    Family,
    FamilyArchiveLog,
    ParentEnrollment,
    ParentRegistrationRequest,
    SurveyAnswer,
)
from template_utils import create_templates

router = APIRouter()
templates = create_templates()


def _return_url(q, scope, preview):
    if preview:
        from uuid import UUID

        try:
            if UUID(preview).hex != preview:
                raise ValueError
        except ValueError:
            raise HTTPException(400, "確認データの指定が不正です。")
        return "/data-transfers/?" + urlencode(
            {"dataset": "families", "preview": preview}
        )
    return "/families/?" + urlencode(
        {"scope": scope if scope in {"active", "archived", "all"} else "active", "q": q}
    )


def _render(
    request,
    session,
    actor,
    family_id,
    action,
    *,
    q="",
    scope="active",
    preview="",
    error="",
    status=200,
    reason="",
    note="",
):
    family = session.get(Family, family_id)
    if family is None:
        raise HTTPException(404, "家族が見つかりません。")
    history = session.exec(
        select(FamilyArchiveLog)
        .where(FamilyArchiveLog.family_id == family.id)
        .order_by(FamilyArchiveLog.created_at.desc(), FamilyArchiveLog.id.desc())
    ).all()
    blockers = archive_blockers(session, family) if action == "archive" else []
    valid_state = family.is_archived == (action == "restore")
    review_token = (
        issue_archive_review(request, actor, family, action)
        if action in {"archive", "restore"} and valid_state and not blockers
        else ""
    )
    answers = (
        session.exec(
            select(SurveyAnswer).where(SurveyAnswer.family_id == family.id)
        ).all()
        if action == "records"
        else []
    )
    child_ids = session.exec(select(Child.id).where(Child.family_id == family.id)).all()
    enrollments = (
        [
            (enrollment, registration)
            for enrollment, registration in session.exec(
                select(ParentEnrollment, ParentRegistrationRequest).join(
                    ParentRegistrationRequest,
                    ParentRegistrationRequest.id
                    == ParentEnrollment.registration_request_id,
                )
            ).all()
            if str((enrollment.source_snapshot or {}).get("family_id"))
            == str(family.id)
            or enrollment.child_id in child_ids
        ]
        if action == "records"
        else []
    )
    return templates.TemplateResponse(
        request,
        "families/archive.html",
        {
            "current_user": actor,
            "family": family,
            "action": action,
            "dependencies": dependency_counts(session, family),
            "history": history,
            "blockers": blockers,
            "review_token": review_token,
            "error": error,
            "reason": reason,
            "note": note,
            "reasons": REASONS,
            "q": q,
            "scope": scope,
            "preview": preview,
            "list_url": _return_url(q, scope, preview),
            "answers": answers,
            "enrollments": enrollments,
        },
        status_code=status,
        headers={
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "same-origin",
        },
    )


@router.get("/{family_id}/records")
def family_records(
    request: Request,
    family_id: int,
    q: str = "",
    scope: str = "archived",
    session: Session = Depends(get_session),
    actor=Depends(get_current_staff_user),
):
    return _render(request, session, actor, family_id, "records", q=q, scope=scope)


@router.get("/{family_id}/archive")
def archive_review(
    request: Request,
    family_id: int,
    q: str = "",
    scope: str = "active",
    preview: str = "",
    session: Session = Depends(get_session),
    actor=Depends(get_current_staff_user),
):
    require_archive_manager(session, actor)
    return _render(
        request, session, actor, family_id, "archive", q=q, scope=scope, preview=preview
    )


@router.get("/{family_id}/restore")
def restore_review(
    request: Request,
    family_id: int,
    q: str = "",
    scope: str = "archived",
    preview: str = "",
    session: Session = Depends(get_session),
    actor=Depends(get_current_staff_user),
):
    require_archive_manager(session, actor)
    return _render(
        request, session, actor, family_id, "restore", q=q, scope=scope, preview=preview
    )


@router.post("/{family_id}/archive", dependencies=[Depends(verify_csrf)])
@router.post("/{family_id}/restore", dependencies=[Depends(verify_csrf)])
def change_archive(
    request: Request,
    family_id: int,
    review_token: str = Form(""),
    reason: str = Form(""),
    note: str = Form(""),
    q: str = Form(""),
    scope: str = Form("active"),
    preview: str = Form(""),
    session: Session = Depends(get_session),
    actor=Depends(get_current_staff_user),
):
    action = request.url.path.rsplit("/", 1)[-1]
    require_archive_manager(session, actor)
    _return_url(q, scope, preview)  # validate before saving
    try:
        transition_family(
            session,
            request=request,
            actor=actor,
            family_id=family_id,
            action=action,
            review_token=review_token,
            reason=reason,
            note=note,
        )
    except FamilyArchiveError as exc:
        return _render(
            request,
            session,
            actor,
            family_id,
            action,
            q=q,
            scope=scope,
            preview=preview,
            reason=reason,
            note=note,
            error=str(exc),
            status=exc.status,
        )
    if preview:
        return RedirectResponse(_return_url(q, scope, preview), status_code=303)
    return RedirectResponse(
        _return_url(q, "archived" if action == "archive" else "active", "")
        + "&archive_notice="
        + action,
        status_code=303,
    )
