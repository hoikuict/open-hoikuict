from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from ..auth_adapter import CurrentUser, require_actor, require_can_edit, require_classroom_access
from ..contracts import DocumentStatus
from ..db_models import PlanReflectionReviewRow as Review, PlanReflectionNotificationRow as Notification
from ..services import reflection_reviews as service
from ..store import DocumentRepositoryDep
from ..templating import render_template

router = APIRouter()


def document_for(repository, user, document_id):
    document = repository.get(document_id)
    if not document or document.nursery_ref != user.nursery_ref:
        raise HTTPException(404, "文書が見つかりません")
    classroom = None
    if document.annual_sheet:
        from models import Classroom
        classroom = repository.session.get(Classroom, document.annual_sheet["classroom_id"])
    require_classroom_access(user, classroom.name if classroom else document.classroom_ref)
    return document


def commit(session):
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(409, "他の操作と競合しました。画面を開き直してください") from exc


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: int = Field(ge=-1, le=3)
    version: int = Field(ge=0)
    values: list[str] = Field(min_length=1, max_length=2)


class SaveReflections(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entries: list[Entry] = Field(min_length=1, max_length=4)


@router.post("/documents/{document_id}/reflections")
def save(document_id: int, payload: SaveReflections, request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    require_can_edit(user, request)
    service.begin(repository.session)
    document = document_for(repository, user, document_id)
    if document.status == DocumentStatus.ARCHIVED:
        raise HTTPException(409, "保管済みの文書は編集できません")
    if len({entry.period for entry in payload.entries}) != len(payload.entries):
        raise HTTPException(422, "同じ期を重複して保存できません")
    try:
        for entry in payload.entries:
            service.save_draft(repository.session, document, entry.period, entry.values, entry.version, user.actor_ref)
        commit(repository.session)
    except (HTTPException, IntegrityError):
        repository.session.rollback()
        raise
    return {str(entry.period): service.state(repository.session, document, entry.period) for entry in payload.entries}


@router.get("/documents/{document_id}/reflections/{period}/confirm")
def confirm(document_id: int, period: int, request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    require_can_edit(user, request)
    document = document_for(repository, user, document_id)
    state = service.state(repository.session, document, period)
    if state["locked"]:
        return RedirectResponse(f"/plans/reflection-reviews/{state['review_id']}", status_code=303)
    return render_template(request, "reflections/review.html", user=user, document=document,
        snapshot=service.snapshot(document, period, state["values"]), state=state, review=None,
        input_url=service.input_url(document_id, period), labels=service.LABELS, error="")


@router.post("/documents/{document_id}/reflections/{period}/request")
def submit(document_id: int, period: int, request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
           version: Annotated[int, Form(ge=0)]):
    require_can_edit(user, request)
    service.begin(repository.session)
    document = document_for(repository, user, document_id)
    service.validate_period(document, period)
    if document.status == DocumentStatus.ARCHIVED:
        raise HTTPException(409, "保管済みの文書は承認を依頼できません")
    review = service.request_review(repository.session, document, period, version, user)
    commit(repository.session)
    return RedirectResponse(f"/plans/reflection-reviews/{review.id}", status_code=303)


def review_for(repository, user, review_id):
    review = repository.session.get(Review, review_id)
    if not review or review.nursery_ref != user.nursery_ref:
        raise HTTPException(404, "承認依頼が見つかりません")
    return review, document_for(repository, user, review.document_id)


def render_review(request, user, repository, review, document, error=""):
    period = review.snapshot["period"]
    return render_template(request, "reflections/review.html", user=user, document=document,
        snapshot=review.snapshot, state=service.state(repository.session, document, period), review=review,
        input_url=service.input_url(document.id, period), labels=service.LABELS, error=error,
        history=repository.session.exec(select(Review).where(Review.draft_id == review.draft_id).order_by(Review.id.desc())).all())


@router.get("/reflection-reviews/{review_id}")
def detail(review_id: int, request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    require_actor(user, request)
    review, document = review_for(repository, user, review_id)
    return render_review(request, user, repository, review, document)


@router.post("/reflection-reviews/{review_id}")
def decide(review_id: int, request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
           action: Annotated[str, Form()], comment: Annotated[str, Form(max_length=4000)] = ""):
    require_can_edit(user, request)
    service.begin(repository.session)
    review, document = review_for(repository, user, review_id)
    if document.status == DocumentStatus.ARCHIVED:
        raise HTTPException(409, "保管済みの文書は変更できません")
    try:
        service.transition(repository.session, review, action, user, comment)
        commit(repository.session)
    except HTTPException as exc:
        repository.session.rollback()
        if exc.status_code != 422:
            raise
        response = render_review(request, user, repository, review, document, str(exc.detail))
        response.status_code = 422
        return response
    target = service.input_url(document.id, review.snapshot["period"]) if action in ("revise", "withdraw") else f"/plans/reflection-reviews/{review.id}"
    return RedirectResponse(target, status_code=303)


@router.post("/reflection-notifications/{notification_id}/{action}")
def notification_action(notification_id: int, action: str, request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    require_actor(user, request)
    notification = repository.session.get(Notification, notification_id)
    if not notification or str(notification.recipient_user_id) != str(user.user_id or user.staff_id):
        raise HTTPException(404, "通知が見つかりません")
    review, _ = review_for(repository, user, notification.review_id)
    if notification.kind == "review_request" and not user.is_admin:
        raise HTTPException(403, "管理者権限が必要です")
    if action not in ("open", "dismiss"):
        raise HTTPException(404, "操作が見つかりません")
    notification.read_at = notification.read_at or service.utc_now()
    if action == "dismiss":
        notification.resolved_at = service.utc_now()
    repository.session.add(notification)
    commit(repository.session)
    return RedirectResponse(f"/plans/reflection-reviews/{review.id}" if action == "open" else "/", status_code=303)
