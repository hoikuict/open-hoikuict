from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, select

import database
from models import (
    NotificationDeliveryChannel,
    NotificationDeliveryStatus,
    ParentNotification,
    ParentNotificationDelivery,
    ParentPushDeliveryAttempt,
    ParentPushDeliveryTarget,
    ParentPushDeliveryTargetStatus,
    ParentPushSubscription,
    ParentPushSubscriptionStatus,
)
from time_utils import ensure_utc, ensure_utc_from_local, local_today, utc_now


logger = logging.getLogger(__name__)
PARENT_PUSH_RETENTION_DAYS = 90


@dataclass(frozen=True)
class ParentPushDailyMetrics:
    day: date
    notification_count: int
    push_delivery_count: int
    target_count: int
    no_subscription_count: int
    accepted_count: int
    shown_count: int
    clicked_count: int
    terminal_failed_count: int
    subscription_gone_count: int
    vapid_auth_failed_count: int
    retry_wait_count: int
    oldest_retry_at: datetime | None


@dataclass(frozen=True)
class ParentPushRetentionResult:
    deleted_attempt_count: int
    redacted_subscription_count: int


def build_parent_push_daily_metrics(
    session: Session,
    *,
    day: date | None = None,
) -> ParentPushDailyMetrics:
    target_day = day or local_today()
    start_at = ensure_utc_from_local(datetime.combine(target_day, time.min))
    end_at = ensure_utc_from_local(datetime.combine(target_day + timedelta(days=1), time.min))

    notifications = session.exec(
        select(ParentNotification).where(
            ParentNotification.created_at >= start_at,
            ParentNotification.created_at < end_at,
        )
    ).all()
    deliveries = session.exec(
        select(ParentNotificationDelivery).where(
            ParentNotificationDelivery.channel == NotificationDeliveryChannel.push,
            ParentNotificationDelivery.created_at >= start_at,
            ParentNotificationDelivery.created_at < end_at,
        )
    ).all()
    targets = session.exec(
        select(ParentPushDeliveryTarget).where(
            ParentPushDeliveryTarget.created_at >= start_at,
            ParentPushDeliveryTarget.created_at < end_at,
        )
    ).all()
    attempts = session.exec(
        select(ParentPushDeliveryAttempt).where(
            ParentPushDeliveryAttempt.created_at >= start_at,
            ParentPushDeliveryAttempt.created_at < end_at,
        )
    ).all()
    current_retries = session.exec(
        select(ParentPushDeliveryTarget).where(
            ParentPushDeliveryTarget.status == ParentPushDeliveryTargetStatus.retry_wait
        )
    ).all()

    delivery_ids_with_targets = {target.delivery_id for target in targets}
    no_subscription_count = sum(
        1
        for delivery in deliveries
        if delivery.status == NotificationDeliveryStatus.suppressed
        and delivery.id not in delivery_ids_with_targets
    )
    oldest_retry_at = min(
        (
            ensure_utc(target.next_retry_at)
            for target in current_retries
            if target.next_retry_at is not None
        ),
        default=None,
    )
    return ParentPushDailyMetrics(
        day=target_day,
        notification_count=len(notifications),
        push_delivery_count=len(deliveries),
        target_count=len(targets),
        no_subscription_count=no_subscription_count,
        accepted_count=_timestamp_count(targets, "accepted_at", start_at, end_at),
        shown_count=_timestamp_count(targets, "shown_at", start_at, end_at),
        clicked_count=_timestamp_count(targets, "clicked_at", start_at, end_at),
        terminal_failed_count=sum(
            1
            for target in targets
            if target.status == ParentPushDeliveryTargetStatus.failed
        ),
        subscription_gone_count=sum(
            1 for attempt in attempts if attempt.error_code == "subscription_gone"
        ),
        vapid_auth_failed_count=sum(
            1 for attempt in attempts if attempt.error_code == "vapid_auth_failed"
        ),
        retry_wait_count=len(current_retries),
        oldest_retry_at=oldest_retry_at,
    )


def purge_parent_push_operational_data(
    session: Session,
    *,
    now: datetime | None = None,
    retention_days: int = PARENT_PUSH_RETENTION_DAYS,
) -> ParentPushRetentionResult:
    if retention_days < 1:
        raise ValueError("retention_daysは1日以上で指定してください")
    processed_at = ensure_utc(now or utc_now())
    cutoff = processed_at - timedelta(days=retention_days)

    old_attempts = session.exec(
        select(ParentPushDeliveryAttempt).where(
            ParentPushDeliveryAttempt.created_at < cutoff
        )
    ).all()
    for attempt in old_attempts:
        session.delete(attempt)

    disabled_subscriptions = session.exec(
        select(ParentPushSubscription).where(
            ParentPushSubscription.status.in_(
                [
                    ParentPushSubscriptionStatus.revoked,
                    ParentPushSubscriptionStatus.expired,
                ]
            ),
            ParentPushSubscription.disabled_at.is_not(None),
            ParentPushSubscription.disabled_at < cutoff,
        )
    ).all()
    redacted_count = 0
    for subscription in disabled_subscriptions:
        if _subscription_is_redacted(subscription):
            continue
        redacted_marker = f"redacted:{subscription.id}"
        subscription.endpoint = redacted_marker
        subscription.endpoint_hash = hashlib.sha256(
            redacted_marker.encode("utf-8")
        ).hexdigest()
        subscription.p256dh_key = ""
        subscription.auth_key = ""
        subscription.device_label = None
        subscription.user_agent = None
        subscription.is_test_device = False
        subscription.updated_at = processed_at
        session.add(subscription)
        redacted_count += 1

    return ParentPushRetentionResult(
        deleted_attempt_count=len(old_attempts),
        redacted_subscription_count=redacted_count,
    )


def apply_parent_push_retention() -> ParentPushRetentionResult:
    with Session(database.engine) as session:
        result = purge_parent_push_operational_data(session)
        session.commit()
    if result.deleted_attempt_count or result.redacted_subscription_count:
        logger.info(
            "parent push retention applied",
            extra={
                "deleted_attempt_count": result.deleted_attempt_count,
                "redacted_subscription_count": result.redacted_subscription_count,
            },
        )
    return result


def _timestamp_count(
    records: list[ParentPushDeliveryTarget],
    attribute: str,
    start_at: datetime,
    end_at: datetime,
) -> int:
    count = 0
    for record in records:
        value = ensure_utc(getattr(record, attribute))
        if value is not None and start_at <= value < end_at:
            count += 1
    return count


def _subscription_is_redacted(subscription: ParentPushSubscription) -> bool:
    return (
        subscription.endpoint.startswith("redacted:")
        and not subscription.p256dh_key
        and not subscription.auth_key
    )
