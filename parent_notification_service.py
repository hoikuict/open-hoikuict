from __future__ import annotations

from datetime import date, datetime

from sqlmodel import Session, select

from models import (
    Child,
    NotificationDeliveryChannel,
    NotificationDeliveryStatus,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentNotification,
    ParentNotificationDelivery,
    ParentNotificationKind,
)
from time_utils import utc_now


ATTENDANCE_CONFIRMATION_TITLE = "本日の出欠確認のお願い"
ATTENDANCE_CONFIRMATION_BODY = "本日の連絡をいただいておりません。出席か欠席かお知らせください。"


def notify_attendance_confirmation_needed(
    session: Session,
    *,
    child: Child,
    target_date: date,
    source_id: str,
    created_by_name: str,
    now: datetime | None = None,
) -> list[ParentNotification]:
    """Create in-app notifications for every active guardian linked to a child.

    Notifications are independent from delivery records. A future push worker can
    add a ``push`` delivery to the same notification without changing attendance
    check logic.
    """
    if child.id is None:
        return []

    created_at = now or utc_now()
    parent_accounts = session.exec(
        select(ParentAccount)
        .join(ParentChildLink, ParentChildLink.parent_account_id == ParentAccount.id)
        .where(
            ParentChildLink.child_id == child.id,
            ParentAccount.status == ParentAccountStatus.active,
        )
        .order_by(ParentChildLink.is_primary_contact.desc(), ParentAccount.id)
    ).all()

    notifications: list[ParentNotification] = []
    for parent_account in parent_accounts:
        if parent_account.id is None:
            continue
        notification = ParentNotification(
            parent_account_id=parent_account.id,
            child_id=child.id,
            kind=ParentNotificationKind.attendance_confirmation_request,
            title=ATTENDANCE_CONFIRMATION_TITLE,
            body=ATTENDANCE_CONFIRMATION_BODY,
            action_url=f"/parent-portal/children/{child.id}/contact?date={target_date.isoformat()}",
            target_date=target_date,
            source_type="attendance_verification_history",
            source_id=source_id,
            created_by_name=created_by_name,
            created_at=created_at,
        )
        session.add(notification)
        session.flush()
        session.add(
            ParentNotificationDelivery(
                notification_id=notification.id,
                channel=NotificationDeliveryChannel.in_app,
                status=NotificationDeliveryStatus.delivered,
                attempted_at=created_at,
                delivered_at=created_at,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        notifications.append(notification)
    return notifications


def queue_push_delivery(
    session: Session,
    notification: ParentNotification,
    *,
    now: datetime | None = None,
) -> ParentNotificationDelivery | None:
    """Queue a push delivery for a future push-notification worker."""
    if notification.id is None:
        return None
    existing = session.exec(
        select(ParentNotificationDelivery).where(
            ParentNotificationDelivery.notification_id == notification.id,
            ParentNotificationDelivery.channel == NotificationDeliveryChannel.push,
        )
    ).first()
    if existing:
        return existing

    created_at = now or utc_now()
    delivery = ParentNotificationDelivery(
        notification_id=notification.id,
        channel=NotificationDeliveryChannel.push,
        status=NotificationDeliveryStatus.pending,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(delivery)
    return delivery
