from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, select

from models import User
from time_utils import utc_now

from ..contracts import DocumentStatus
from ..db_models import PlanDocumentRow, PlanReviewNotificationRow
from ..models import PlanDocument


REVIEW_REQUEST = "review_request"
REVIEW_OUTCOME = "review_outcome"


def list_pending_review_documents(
    session: Session,
    *,
    nursery_ref: str,
    limit: int = 50,
) -> list[PlanDocumentRow]:
    """Return the authoritative approval queue, independent of notification rows."""
    return list(
        session.exec(
            select(PlanDocumentRow)
            .where(
                PlanDocumentRow.nursery_ref == nursery_ref,
                PlanDocumentRow.status == DocumentStatus.IN_REVIEW.value,
            )
            .order_by(PlanDocumentRow.updated_at.desc(), PlanDocumentRow.id.desc())
            .limit(limit)
        ).all()
    )


def _user_id_from_actor_ref(actor_ref: str) -> UUID | None:
    if not actor_ref.startswith("staff:"):
        return None
    try:
        return UUID(actor_ref.removeprefix("staff:"))
    except ValueError:
        return None


def create_review_notifications(
    session: Session,
    *,
    document: PlanDocument,
    review_revision_id: int,
    requested_by_ref: str,
    requested_by_name: str,
) -> list[PlanReviewNotificationRow]:
    """Create one in-app notification for each active plan approver."""
    requester_id = _user_id_from_actor_ref(requested_by_ref)
    recipients = session.exec(
        select(User)
        .where(User.is_active.is_(True), User.staff_role == "admin")
        .order_by(User.staff_sort_order, User.display_name, User.id)
    ).all()
    existing_recipient_ids = set(
        session.exec(
            select(PlanReviewNotificationRow.recipient_user_id).where(
                PlanReviewNotificationRow.review_revision_id == review_revision_id
            )
        ).all()
    )
    notifications: list[PlanReviewNotificationRow] = []
    for recipient in recipients:
        if recipient.id == requester_id or recipient.id in existing_recipient_ids:
            continue
        notification = PlanReviewNotificationRow(
            document_id=int(document.id or 0),
            review_revision_id=review_revision_id,
            recipient_user_id=recipient.id,
            nursery_ref=document.nursery_ref,
            document_title=document.title,
            notification_kind=REVIEW_REQUEST,
            requested_by_ref=requested_by_ref,
            requested_by_name=requested_by_name,
        )
        session.add(notification)
        notifications.append(notification)
    return notifications


def create_review_outcome_notification(
    session: Session,
    *,
    document: PlanDocument,
    review_revision_id: int,
    decision_status: str,
    decided_by_ref: str,
    decided_by_name: str,
    decision_comment: str | None = None,
) -> PlanReviewNotificationRow | None:
    """Notify the original document creator when a review is decided."""
    creator_id = _user_id_from_actor_ref(document.actor_ref or "")
    if creator_id is None:
        return None
    creator = session.get(User, creator_id)
    if creator is None or not creator.is_active:
        return None
    notification = session.exec(
        select(PlanReviewNotificationRow).where(
            PlanReviewNotificationRow.review_revision_id == review_revision_id,
            PlanReviewNotificationRow.recipient_user_id == creator_id,
        )
    ).first()
    if notification is None:
        notification = PlanReviewNotificationRow(
            document_id=int(document.id or 0),
            review_revision_id=review_revision_id,
            recipient_user_id=creator_id,
            nursery_ref=document.nursery_ref,
            document_title=document.title,
            requested_by_ref=decided_by_ref,
            requested_by_name=decided_by_name,
        )
    notification.notification_kind = REVIEW_OUTCOME
    notification.decision_status = decision_status
    notification.decided_by_name = decided_by_name
    notification.decision_comment = (decision_comment or "").strip() or None
    notification.requested_by_ref = decided_by_ref
    notification.requested_by_name = decided_by_name
    notification.created_at = utc_now()
    notification.read_at = None
    notification.resolved_at = None
    session.add(notification)
    return notification


def resolve_review_notifications(
    session: Session,
    *,
    document_id: int,
    review_revision_id: int | None = None,
) -> None:
    statement = select(PlanReviewNotificationRow).where(
        PlanReviewNotificationRow.document_id == document_id,
        PlanReviewNotificationRow.resolved_at.is_(None),
    )
    if review_revision_id is not None:
        statement = statement.where(
            PlanReviewNotificationRow.review_revision_id == review_revision_id
        )
    now = utc_now()
    for notification in session.exec(statement).all():
        notification.resolved_at = now
        session.add(notification)


def list_review_notifications(
    session: Session,
    *,
    recipient_user_id: str | UUID | None,
    nursery_ref: str,
    include_resolved: bool = False,
) -> list[PlanReviewNotificationRow]:
    try:
        recipient_id = UUID(str(recipient_user_id))
    except (TypeError, ValueError):
        return []
    statement = select(PlanReviewNotificationRow).where(
        PlanReviewNotificationRow.recipient_user_id == recipient_id,
        PlanReviewNotificationRow.nursery_ref == nursery_ref,
    )
    if not include_resolved:
        statement = statement.where(PlanReviewNotificationRow.resolved_at.is_(None))
    return list(
        session.exec(
            statement.order_by(
                PlanReviewNotificationRow.read_at.is_not(None),
                PlanReviewNotificationRow.created_at.desc(),
                PlanReviewNotificationRow.id.desc(),
            )
        ).all()
    )


def get_review_notification(
    session: Session,
    *,
    notification_id: int,
    recipient_user_id: str | UUID | None,
    nursery_ref: str,
) -> PlanReviewNotificationRow | None:
    try:
        recipient_id = UUID(str(recipient_user_id))
    except (TypeError, ValueError):
        return None
    return session.exec(
        select(PlanReviewNotificationRow).where(
            PlanReviewNotificationRow.id == notification_id,
            PlanReviewNotificationRow.recipient_user_id == recipient_id,
            PlanReviewNotificationRow.nursery_ref == nursery_ref,
        )
    ).first()


def mark_review_notification_read(
    session: Session,
    notification: PlanReviewNotificationRow,
) -> None:
    if notification.read_at is None:
        notification.read_at = utc_now()
        session.add(notification)
        session.commit()
