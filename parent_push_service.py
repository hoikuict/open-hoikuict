from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlmodel import Session, select

from models import (
    NotificationDeliveryChannel,
    NotificationDeliveryStatus,
    ParentAccount,
    ParentAccountStatus,
    ParentNotification,
    ParentNotificationDelivery,
    ParentNotificationKind,
    ParentPushDeliveryAttemptResult,
    ParentPushDeliveryTarget,
    ParentPushDeliveryTargetStatus,
    ParentPushPreference,
    ParentPushSubscription,
    ParentPushSubscriptionStatus,
    ParentPushTransport,
)
from time_utils import ensure_utc, utc_now


PUSH_SCHEMA_VERSION = 1
SAFE_PUSH_TITLE = "保育園から確認のお願い"
SAFE_PUSH_BODY = "確認が必要な連絡があります。保護者ポータルをご確認ください。"
OPEN_TARGET_STATUSES = {
    ParentPushDeliveryTargetStatus.pending,
    ParentPushDeliveryTargetStatus.processing,
    ParentPushDeliveryTargetStatus.retry_wait,
}


@dataclass(frozen=True)
class ParentPushSendResult:
    result: ParentPushDeliveryAttemptResult
    provider_status_code: int | None = None
    provider_request_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class ParentPushTransportProtocol(Protocol):
    name: ParentPushTransport

    def send(
        self,
        *,
        subscription: ParentPushSubscription,
        payload: dict[str, object],
    ) -> ParentPushSendResult: ...


class CaptureParentPushTransport:
    """Development transport that records success without external I/O."""

    name = ParentPushTransport.capture

    def send(
        self,
        *,
        subscription: ParentPushSubscription,
        payload: dict[str, object],
    ) -> ParentPushSendResult:
        del subscription, payload
        return ParentPushSendResult(
            result=ParentPushDeliveryAttemptResult.accepted,
            provider_request_id="capture",
        )


def create_parent_push_transport(name: str) -> ParentPushTransportProtocol:
    if name == ParentPushTransport.capture.value:
        return CaptureParentPushTransport()
    if name == "disabled":
        raise RuntimeError("保護者プッシュ通知transportは無効です")
    if name == ParentPushTransport.webpush.value:
        raise RuntimeError("webpush transportはまだ実装されていません")
    raise RuntimeError(f"未対応の保護者プッシュ通知transportです: {name}")


def generate_receipt_token() -> str:
    return secrets.token_urlsafe(32)


def hash_receipt_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_push_payload(
    *,
    notification: ParentNotification,
    delivery: ParentNotificationDelivery,
    target: ParentPushDeliveryTarget,
    shown_receipt_token: str,
    clicked_receipt_token: str,
) -> dict[str, object]:
    if notification.id is None or target.id is None:
        raise ValueError("保存済みの通知と配送対象が必要です")
    return {
        "schema_version": PUSH_SCHEMA_VERSION,
        "notification_id": notification.id,
        "target_id": target.id,
        "kind": notification.kind.value,
        "title": SAFE_PUSH_TITLE,
        "body": SAFE_PUSH_BODY,
        "action_url": f"/parent-portal/notifications/{notification.id}",
        "shown_receipt_token": shown_receipt_token,
        "clicked_receipt_token": clicked_receipt_token,
        "expires_at": delivery.expires_at.isoformat() if delivery.expires_at else None,
    }


def resolve_delivery_targets(
    session: Session,
    delivery: ParentNotificationDelivery,
    *,
    environment: str,
    now: datetime | None = None,
) -> list[ParentPushDeliveryTarget]:
    if delivery.id is None:
        raise ValueError("保存済みの配送が必要です")
    if delivery.channel != NotificationDeliveryChannel.push:
        raise ValueError("push配送だけがTarget展開の対象です")

    existing = _targets_for_delivery(session, delivery.id)
    if delivery.targets_resolved_at is not None:
        return existing

    resolved_at = now or utc_now()
    notification = session.get(ParentNotification, delivery.notification_id)
    if notification is None:
        raise ValueError("配送元の保護者通知が見つかりません")

    if _is_expired(delivery, resolved_at):
        delivery.status = NotificationDeliveryStatus.expired
        delivery.targets_resolved_at = resolved_at
        delivery.completed_at = resolved_at
        delivery.updated_at = resolved_at
        session.add(delivery)
        return existing

    parent_account = session.get(ParentAccount, notification.parent_account_id)
    preference = session.exec(
        select(ParentPushPreference).where(
            ParentPushPreference.parent_account_id == notification.parent_account_id
        )
    ).first()
    if not _push_allowed(parent_account, preference, notification.kind):
        delivery.status = NotificationDeliveryStatus.suppressed
        delivery.targets_resolved_at = resolved_at
        delivery.completed_at = resolved_at
        delivery.updated_at = resolved_at
        session.add(delivery)
        return existing

    subscriptions = session.exec(
        select(ParentPushSubscription)
        .where(
            ParentPushSubscription.parent_account_id == notification.parent_account_id,
            ParentPushSubscription.status == ParentPushSubscriptionStatus.active,
            ParentPushSubscription.environment == environment,
        )
        .order_by(ParentPushSubscription.id)
    ).all()
    existing_subscription_ids = {target.subscription_id for target in existing}
    for subscription in subscriptions:
        if subscription.id is None or subscription.id in existing_subscription_ids:
            continue
        target = ParentPushDeliveryTarget(
            delivery_id=delivery.id,
            subscription_id=subscription.id,
            created_at=resolved_at,
            updated_at=resolved_at,
        )
        session.add(target)
        existing.append(target)

    session.flush()
    delivery.targets_resolved_at = resolved_at
    delivery.updated_at = resolved_at
    if not existing:
        delivery.status = NotificationDeliveryStatus.suppressed
        delivery.completed_at = resolved_at
    session.add(delivery)
    return existing


def recompute_delivery_summary(
    session: Session,
    delivery: ParentNotificationDelivery,
    *,
    now: datetime | None = None,
) -> ParentNotificationDelivery:
    if delivery.id is None:
        raise ValueError("保存済みの配送が必要です")
    targets = _targets_for_delivery(session, delivery.id)
    statuses = {target.status for target in targets}

    if ParentPushDeliveryTargetStatus.clicked in statuses:
        delivery.status = NotificationDeliveryStatus.clicked
    elif ParentPushDeliveryTargetStatus.shown in statuses:
        delivery.status = NotificationDeliveryStatus.shown
    elif ParentPushDeliveryTargetStatus.accepted in statuses:
        delivery.status = NotificationDeliveryStatus.accepted
    elif ParentPushDeliveryTargetStatus.processing in statuses:
        delivery.status = NotificationDeliveryStatus.processing
    elif statuses & {
        ParentPushDeliveryTargetStatus.pending,
        ParentPushDeliveryTargetStatus.retry_wait,
    }:
        delivery.status = NotificationDeliveryStatus.pending
    elif not targets or statuses == {ParentPushDeliveryTargetStatus.suppressed}:
        delivery.status = NotificationDeliveryStatus.suppressed
    elif statuses == {ParentPushDeliveryTargetStatus.expired}:
        delivery.status = NotificationDeliveryStatus.expired
    else:
        delivery.status = NotificationDeliveryStatus.failed

    delivery.accepted_at = _earliest_timestamp(targets, "accepted_at")
    delivery.shown_at = _earliest_timestamp(targets, "shown_at")
    delivery.clicked_at = _earliest_timestamp(targets, "clicked_at")
    updated_at = now or utc_now()
    delivery.updated_at = updated_at
    if delivery.targets_resolved_at is not None and not any(
        target.status in OPEN_TARGET_STATUSES for target in targets
    ):
        delivery.completed_at = delivery.completed_at or updated_at
    else:
        delivery.completed_at = None
    session.add(delivery)
    return delivery


def _targets_for_delivery(
    session: Session,
    delivery_id: int,
) -> list[ParentPushDeliveryTarget]:
    return list(
        session.exec(
            select(ParentPushDeliveryTarget)
            .where(ParentPushDeliveryTarget.delivery_id == delivery_id)
            .order_by(ParentPushDeliveryTarget.id)
        ).all()
    )


def _push_allowed(
    parent_account: ParentAccount | None,
    preference: ParentPushPreference | None,
    notification_kind: ParentNotificationKind,
) -> bool:
    if parent_account is None or parent_account.status != ParentAccountStatus.active:
        return False
    if preference is not None and not preference.push_enabled:
        return False
    if (
        notification_kind == ParentNotificationKind.attendance_confirmation_request
        and preference is not None
        and not preference.attendance_confirmation_enabled
    ):
        return False
    return True


def _is_expired(delivery: ParentNotificationDelivery, now: datetime) -> bool:
    expires_at = ensure_utc(delivery.expires_at)
    comparable_now = ensure_utc(now)
    return bool(expires_at and comparable_now and expires_at <= comparable_now)


def _earliest_timestamp(
    targets: list[ParentPushDeliveryTarget],
    attribute: str,
) -> datetime | None:
    values = [getattr(target, attribute) for target in targets if getattr(target, attribute) is not None]
    return min(values, key=lambda value: ensure_utc(value)) if values else None
