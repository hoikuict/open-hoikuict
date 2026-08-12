from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from pywebpush import WebPushException, webpush

from sqlalchemy import and_, or_, update
from sqlmodel import Session, select

from models import (
    NotificationDeliveryChannel,
    NotificationDeliveryStatus,
    ParentAccount,
    ParentAccountStatus,
    ParentNotification,
    ParentNotificationDelivery,
    ParentNotificationKind,
    ParentPushDeliveryAttempt,
    ParentPushDeliveryAttemptResult,
    ParentPushDeliveryTarget,
    ParentPushDeliveryTargetStatus,
    ParentPushPreference,
    ParentPushSubscription,
    ParentPushSubscriptionStatus,
    ParentPushTransport,
)
from time_utils import ensure_utc, utc_now
from security_config import parent_push_vapid_private_key, parent_push_vapid_subject


logger = logging.getLogger(__name__)
PUSH_SCHEMA_VERSION = 1
SAFE_PUSH_TITLE = "保育園から確認のお願い"
SAFE_PUSH_BODY = "確認が必要な連絡があります。保護者ポータルをご確認ください。"
OPEN_TARGET_STATUSES = {
    ParentPushDeliveryTargetStatus.pending,
    ParentPushDeliveryTargetStatus.processing,
    ParentPushDeliveryTargetStatus.retry_wait,
}
DEFAULT_LEASE_SECONDS = 120
DEFAULT_PLANNING_LEASE_SECONDS = 30
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_RETRY_DELAYS_SECONDS = (30, 120, 600, 1800)
DEFAULT_WEB_PUSH_TIMEOUT_SECONDS = 10
DEFAULT_WEB_PUSH_TTL_SECONDS = 6 * 60 * 60


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


class WebPushParentPushTransport:
    name = ParentPushTransport.webpush

    def __init__(
        self,
        *,
        vapid_private_key: str,
        vapid_subject: str,
        sender=webpush,
        timeout_seconds: int = DEFAULT_WEB_PUSH_TIMEOUT_SECONDS,
    ):
        if not vapid_private_key or not vapid_subject:
            raise RuntimeError("Web Push transportにはVAPID秘密鍵とsubjectが必要です")
        self._vapid_private_key = vapid_private_key
        self._vapid_subject = vapid_subject
        self._sender = sender
        self._timeout_seconds = timeout_seconds

    def send(
        self,
        *,
        subscription: ParentPushSubscription,
        payload: dict[str, object],
    ) -> ParentPushSendResult:
        try:
            response = self._sender(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh_key,
                        "auth": subscription.auth_key,
                    },
                },
                data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                vapid_private_key=self._vapid_private_key,
                vapid_claims={"sub": self._vapid_subject},
                content_encoding="aes128gcm",
                ttl=_payload_ttl_seconds(payload),
                timeout=self._timeout_seconds,
            )
        except WebPushException as exc:
            response = exc.response
            return classify_web_push_response(
                getattr(response, "status_code", None),
                headers=getattr(response, "headers", None),
            )
        return classify_web_push_response(
            getattr(response, "status_code", None),
            headers=getattr(response, "headers", None),
        )


def create_parent_push_transport(name: str) -> ParentPushTransportProtocol:
    if name == ParentPushTransport.capture.value:
        return CaptureParentPushTransport()
    if name == "disabled":
        raise RuntimeError("保護者プッシュ通知transportは無効です")
    if name == ParentPushTransport.webpush.value:
        return WebPushParentPushTransport(
            vapid_private_key=parent_push_vapid_private_key(),
            vapid_subject=parent_push_vapid_subject(),
        )
    raise RuntimeError(f"未対応の保護者プッシュ通知transportです: {name}")


def classify_web_push_response(
    status_code: int | None,
    *,
    headers=None,
) -> ParentPushSendResult:
    request_id = _provider_request_id(headers)
    if status_code is not None and 200 <= status_code < 300:
        return ParentPushSendResult(
            result=ParentPushDeliveryAttemptResult.accepted,
            provider_status_code=status_code,
            provider_request_id=request_id,
        )
    if status_code in {404, 410}:
        return ParentPushSendResult(
            result=ParentPushDeliveryAttemptResult.terminal_failed,
            provider_status_code=status_code,
            provider_request_id=request_id,
            error_code="subscription_gone",
            error_message="Push Serviceで購読が無効になっています",
        )
    if status_code in {408, 425, 429} or (
        status_code is not None and status_code >= 500
    ):
        error_code = "rate_limited" if status_code == 429 else "provider_unavailable"
        return ParentPushSendResult(
            result=ParentPushDeliveryAttemptResult.retryable_failed,
            provider_status_code=status_code,
            provider_request_id=request_id,
            error_code=error_code,
            error_message="Push Serviceの一時的なエラーです",
        )
    if status_code in {401, 403}:
        return ParentPushSendResult(
            result=ParentPushDeliveryAttemptResult.terminal_failed,
            provider_status_code=status_code,
            provider_request_id=request_id,
            error_code="vapid_auth_failed",
            error_message="Push ServiceがVAPID認証を拒否しました",
        )
    if status_code is not None and 400 <= status_code < 500:
        error_code = "payload_too_large" if status_code == 413 else "provider_rejected"
        return ParentPushSendResult(
            result=ParentPushDeliveryAttemptResult.terminal_failed,
            provider_status_code=status_code,
            provider_request_id=request_id,
            error_code=error_code,
            error_message="Push Serviceが送信要求を拒否しました",
        )
    return ParentPushSendResult(
        result=ParentPushDeliveryAttemptResult.retryable_failed,
        provider_status_code=status_code,
        provider_request_id=request_id,
        error_code="transport_unavailable",
        error_message="Push Serviceから有効な応答を取得できませんでした",
    )


def _payload_ttl_seconds(payload: dict[str, object]) -> int:
    raw_expires_at = payload.get("expires_at")
    if not isinstance(raw_expires_at, str) or not raw_expires_at:
        return DEFAULT_WEB_PUSH_TTL_SECONDS
    try:
        expires_at = ensure_utc(datetime.fromisoformat(raw_expires_at))
    except ValueError:
        return DEFAULT_WEB_PUSH_TTL_SECONDS
    remaining = int((expires_at - utc_now()).total_seconds())
    return max(0, min(DEFAULT_WEB_PUSH_TTL_SECONDS, remaining))


def _provider_request_id(headers) -> str | None:
    if not headers:
        return None
    accepted_names = {"x-request-id", "x-amzn-requestid"}
    for name, value in headers.items():
        if str(name).lower() in accepted_names and value:
            return str(value)[:255]
    return None


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


def plan_pending_deliveries(
    session: Session,
    *,
    environment: str,
    now: datetime | None = None,
    limit: int = 50,
) -> int:
    planned = 0
    planned_at = now or utc_now()
    candidate_ids = session.exec(
        select(ParentNotificationDelivery.id)
        .where(
            ParentNotificationDelivery.channel == NotificationDeliveryChannel.push,
            ParentNotificationDelivery.targets_resolved_at.is_(None),
            or_(
                ParentNotificationDelivery.planning_lease_expires_at.is_(None),
                ParentNotificationDelivery.planning_lease_expires_at < planned_at,
            ),
        )
        .order_by(ParentNotificationDelivery.id)
        .limit(limit)
    ).all()
    for delivery_id in candidate_ids:
        lease_expires_at = planned_at + timedelta(seconds=DEFAULT_PLANNING_LEASE_SECONDS)
        result = session.exec(
            update(ParentNotificationDelivery)
            .where(
                ParentNotificationDelivery.id == delivery_id,
                ParentNotificationDelivery.targets_resolved_at.is_(None),
                or_(
                    ParentNotificationDelivery.planning_lease_expires_at.is_(None),
                    ParentNotificationDelivery.planning_lease_expires_at < planned_at,
                ),
            )
            .values(
                planning_lease_expires_at=lease_expires_at,
                updated_at=planned_at,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            session.rollback()
            continue
        session.commit()
        session.expire_all()
        delivery = session.get(ParentNotificationDelivery, delivery_id)
        if delivery is None:
            continue
        resolve_delivery_targets(
            session,
            delivery,
            environment=environment,
            now=planned_at,
        )
        delivery.planning_lease_expires_at = None
        session.add(delivery)
        session.commit()
        planned += 1
    return planned


def claim_next_delivery_target(
    session: Session,
    *,
    now: datetime | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> ParentPushDeliveryTarget | None:
    claimed_at = now or utc_now()
    eligible = _claimable_target_condition(claimed_at)
    candidate_ids = session.exec(
        select(ParentPushDeliveryTarget.id)
        .where(eligible)
        .order_by(
            ParentPushDeliveryTarget.next_retry_at,
            ParentPushDeliveryTarget.id,
        )
        .limit(50)
    ).all()
    for target_id in candidate_ids:
        result = session.exec(
            update(ParentPushDeliveryTarget)
            .where(
                ParentPushDeliveryTarget.id == target_id,
                _claimable_target_condition(claimed_at),
            )
            .values(
                status=ParentPushDeliveryTargetStatus.processing,
                processing_started_at=claimed_at,
                lease_expires_at=claimed_at + timedelta(seconds=lease_seconds),
                updated_at=claimed_at,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            session.rollback()
            continue
        session.commit()
        session.expire_all()
        return session.get(ParentPushDeliveryTarget, target_id)
    session.rollback()
    return None


def process_claimed_target(
    session: Session,
    target: ParentPushDeliveryTarget,
    *,
    transport: ParentPushTransportProtocol,
    environment: str,
    now: datetime | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> ParentPushDeliveryTarget:
    processed_at = now or utc_now()
    if target.id is None:
        raise ValueError("保存済みの配送対象が必要です")
    session.refresh(target)
    if target.status != ParentPushDeliveryTargetStatus.processing:
        raise ValueError("claim済みの配送対象だけを処理できます")

    delivery = session.get(ParentNotificationDelivery, target.delivery_id)
    subscription = session.get(ParentPushSubscription, target.subscription_id)
    if delivery is None or subscription is None:
        raise ValueError("配送または購読が見つかりません")
    notification = session.get(ParentNotification, delivery.notification_id)
    if notification is None:
        raise ValueError("配送元の保護者通知が見つかりません")

    preference = session.exec(
        select(ParentPushPreference).where(
            ParentPushPreference.parent_account_id == notification.parent_account_id
        )
    ).first()
    parent_account = session.get(ParentAccount, notification.parent_account_id)
    suppression_status = _target_suppression_status(
        delivery=delivery,
        subscription=subscription,
        parent_account=parent_account,
        preference=preference,
        notification_kind=notification.kind,
        environment=environment,
        transport=transport.name,
        now=processed_at,
    )
    if suppression_status is not None:
        target.status = suppression_status
        target.lease_expires_at = None
        target.next_retry_at = None
        target.updated_at = processed_at
        session.add(target)
        recompute_delivery_summary(session, delivery, now=processed_at)
        session.commit()
        session.refresh(target)
        return target

    shown_token = generate_receipt_token()
    clicked_token = generate_receipt_token()
    target.shown_receipt_token_hash = hash_receipt_token(shown_token)
    target.clicked_receipt_token_hash = hash_receipt_token(clicked_token)
    target.attempt_count += 1
    target.attempted_at = processed_at
    target.updated_at = processed_at
    attempt = ParentPushDeliveryAttempt(
        target_id=target.id,
        attempt_no=target.attempt_count,
        transport=transport.name,
        started_at=processed_at,
        created_at=processed_at,
    )
    session.add(target)
    session.add(attempt)
    session.commit()
    session.refresh(attempt)

    payload = build_push_payload(
        notification=notification,
        delivery=delivery,
        target=target,
        shown_receipt_token=shown_token,
        clicked_receipt_token=clicked_token,
    )
    try:
        send_result = transport.send(subscription=subscription, payload=payload)
    except Exception:
        send_result = ParentPushSendResult(
            result=ParentPushDeliveryAttemptResult.retryable_failed,
            error_code="transport_exception",
            error_message="transport送信中に例外が発生しました",
        )

    if send_result.error_code == "vapid_auth_failed":
        logger.error(
            "parent push VAPID authentication failed",
            extra={
                "push_delivery_id": delivery.id,
                "push_target_id": target.id,
                "push_attempt_id": attempt.id,
                "provider_status_code": send_result.provider_status_code,
            },
        )

    attempt.result = send_result.result
    attempt.provider_status_code = send_result.provider_status_code
    attempt.provider_request_id = send_result.provider_request_id
    attempt.error_code = send_result.error_code
    attempt.error_message = send_result.error_message
    attempt.completed_at = processed_at

    target.lease_expires_at = None
    target.processing_started_at = None
    target.last_error_code = send_result.error_code
    target.last_error_message = send_result.error_message
    if send_result.result == ParentPushDeliveryAttemptResult.accepted:
        target.status = ParentPushDeliveryTargetStatus.accepted
        target.accepted_at = processed_at
        target.next_retry_at = None
        target.last_error_code = None
        target.last_error_message = None
    elif send_result.result == ParentPushDeliveryAttemptResult.retryable_failed:
        _schedule_retry_or_finish(
            target,
            delivery=delivery,
            now=processed_at,
            max_attempts=max_attempts,
        )
    else:
        target.status = ParentPushDeliveryTargetStatus.failed
        target.next_retry_at = None
        if send_result.error_code == "subscription_gone":
            subscription.status = ParentPushSubscriptionStatus.expired
            subscription.disabled_at = processed_at
            subscription.disabled_reason = "push_service_gone"
            session.add(subscription)
    target.updated_at = processed_at
    session.add(attempt)
    session.add(target)
    recompute_delivery_summary(session, delivery, now=processed_at)
    session.commit()
    session.refresh(target)
    return target


def run_parent_push_worker_cycle(
    session: Session,
    *,
    transport: ParentPushTransportProtocol,
    environment: str,
    now: datetime | None = None,
    max_targets: int = 50,
) -> int:
    cycle_at = now or utc_now()
    plan_pending_deliveries(
        session,
        environment=environment,
        now=cycle_at,
        limit=max_targets,
    )
    processed = 0
    while processed < max_targets:
        target = claim_next_delivery_target(session, now=cycle_at)
        if target is None:
            break
        process_claimed_target(
            session,
            target,
            transport=transport,
            environment=environment,
            now=cycle_at,
        )
        processed += 1
    return processed


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


def _claimable_target_condition(now: datetime):
    return or_(
        ParentPushDeliveryTarget.status == ParentPushDeliveryTargetStatus.pending,
        and_(
            ParentPushDeliveryTarget.status == ParentPushDeliveryTargetStatus.retry_wait,
            ParentPushDeliveryTarget.next_retry_at.is_not(None),
            ParentPushDeliveryTarget.next_retry_at <= now,
        ),
        and_(
            ParentPushDeliveryTarget.status == ParentPushDeliveryTargetStatus.processing,
            ParentPushDeliveryTarget.lease_expires_at.is_not(None),
            ParentPushDeliveryTarget.lease_expires_at < now,
        ),
    )


def _target_suppression_status(
    *,
    delivery: ParentNotificationDelivery,
    subscription: ParentPushSubscription,
    parent_account: ParentAccount | None,
    preference: ParentPushPreference | None,
    notification_kind: ParentNotificationKind,
    environment: str,
    transport: ParentPushTransport,
    now: datetime,
) -> ParentPushDeliveryTargetStatus | None:
    if _is_expired(delivery, now):
        return ParentPushDeliveryTargetStatus.expired
    if not _push_allowed(parent_account, preference, notification_kind):
        return ParentPushDeliveryTargetStatus.suppressed
    if subscription.status != ParentPushSubscriptionStatus.active:
        return ParentPushDeliveryTargetStatus.suppressed
    if subscription.environment != environment:
        return ParentPushDeliveryTargetStatus.suppressed
    if (
        transport == ParentPushTransport.webpush
        and environment == "development"
        and not subscription.is_test_device
    ):
        return ParentPushDeliveryTargetStatus.suppressed
    return None


def _schedule_retry_or_finish(
    target: ParentPushDeliveryTarget,
    *,
    delivery: ParentNotificationDelivery,
    now: datetime,
    max_attempts: int,
) -> None:
    if target.attempt_count >= max_attempts:
        target.status = ParentPushDeliveryTargetStatus.failed
        target.next_retry_at = None
        return
    delay_index = min(target.attempt_count - 1, len(DEFAULT_RETRY_DELAYS_SECONDS) - 1)
    retry_at = now + timedelta(seconds=DEFAULT_RETRY_DELAYS_SECONDS[delay_index])
    expires_at = ensure_utc(delivery.expires_at)
    comparable_retry_at = ensure_utc(retry_at)
    if expires_at and comparable_retry_at and retry_at >= expires_at:
        target.status = ParentPushDeliveryTargetStatus.expired
        target.next_retry_at = None
        return
    target.status = ParentPushDeliveryTargetStatus.retry_wait
    target.next_retry_at = retry_at


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
