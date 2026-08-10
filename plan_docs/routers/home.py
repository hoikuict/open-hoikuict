from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from time_utils import local_now
from url_utils import safe_internal_redirect

from ..auth_adapter import CurrentUser, require_actor
from ..contracts import DocumentType
from ..services.daily_reflections import (
    list_reflection_reminders,
    reflections_by_document_id,
)
from ..services.review_notifications import (
    REVIEW_OUTCOME,
    dismiss_review_notification,
    get_review_notification,
    list_review_notifications,
    mark_review_notification_read,
)
from ..store import DocumentRepositoryDep
from ..templating import render_template


router = APIRouter(tags=["home"])


@router.get("/")
def home(request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    classroom_refs = None if user.is_admin else user.classroom_refs
    documents = repository.list(nursery_ref=user.nursery_ref, classroom_refs=classroom_refs)
    daily_documents = [
        document for document in documents if document.document_type == DocumentType.DAILY_PLAN
    ]
    daily_reflections = reflections_by_document_id(
        repository.session,
        [document.id for document in daily_documents if document.id is not None],
    )
    reflection_reminders = list_reflection_reminders(
        documents=daily_documents,
        reflections=daily_reflections,
        actor_ref=user.actor_ref,
        is_admin=user.is_admin,
        now=local_now(),
    )
    review_notifications = list_review_notifications(
        repository.session,
        recipient_user_id=user.staff_id,
        nursery_ref=user.nursery_ref,
    )
    return render_template(
        request,
        "home.html",
        user=user,
        documents=documents[:8],
        review_notifications=review_notifications,
        unread_review_notification_count=sum(
            1 for notification in review_notifications if notification.read_at is None
        ),
        reflection_reminders=reflection_reminders,
    )


@router.post("/notifications/{notification_id}/open")
def open_review_notification(
    notification_id: int,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
):
    require_actor(user, request)
    notification = get_review_notification(
        repository.session,
        notification_id=notification_id,
        recipient_user_id=user.staff_id,
        nursery_ref=user.nursery_ref,
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="通知が見つかりません")
    document = repository.get(notification.document_id)
    if document is None or document.nursery_ref != user.nursery_ref:
        raise HTTPException(status_code=404, detail="文書が見つかりません")
    mark_review_notification_read(repository.session, notification)
    return RedirectResponse(
        url=f"/plans/documents/{notification.document_id}",
        status_code=303,
    )


@router.post("/notifications/{notification_id}/dismiss")
def dismiss_review_outcome_notification(
    notification_id: int,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    redirect_to: Annotated[str, Form()] = "/",
):
    require_actor(user, request)
    notification = get_review_notification(
        repository.session,
        notification_id=notification_id,
        recipient_user_id=user.staff_id,
        nursery_ref=user.nursery_ref,
    )
    if notification is None or notification.notification_kind != REVIEW_OUTCOME:
        raise HTTPException(status_code=404, detail="通知が見つかりません")
    dismiss_review_notification(repository.session, notification)
    return RedirectResponse(
        url=safe_internal_redirect(redirect_to, "/"),
        status_code=303,
    )
