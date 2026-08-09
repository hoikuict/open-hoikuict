from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..auth_adapter import CurrentUser, require_admin
from ..services.review_notifications import (
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
    review_notifications = (
        list_review_notifications(
            repository.session,
            recipient_user_id=user.staff_id,
            nursery_ref=user.nursery_ref,
        )
        if user.is_admin
        else []
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
    )


@router.post("/notifications/{notification_id}/open")
def open_review_notification(
    notification_id: int,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
):
    require_admin(user, request)
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
