from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime

from fastapi import Response
from sqlmodel import Session, select

from models import (
    ParentPushPreference,
    ParentPushSubscription,
    ParentPushSubscriptionStatus,
)
from security_config import secure_cookie_enabled
from time_utils import utc_now


PARENT_PUSH_DEVICE_COOKIE = "parent_push_device"
PARENT_PUSH_DEVICE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def register_parent_push_subscription(
    session: Session,
    *,
    parent_account_id: int,
    endpoint: str,
    p256dh_key: str,
    auth_key: str,
    environment: str,
    is_test_device: bool,
    device_label: str | None,
    user_agent: str | None,
    previous_subscription_id: int | None = None,
    now: datetime | None = None,
) -> ParentPushSubscription:
    registered_at = now or utc_now()
    digest = endpoint_hash(endpoint)
    subscription = session.exec(
        select(ParentPushSubscription).where(
            ParentPushSubscription.endpoint_hash == digest
        )
    ).first()
    if subscription is not None:
        if subscription.endpoint != endpoint:
            raise ValueError("endpointハッシュが既存購読と競合しています")
        if subscription.parent_account_id != parent_account_id:
            raise PermissionError("このブラウザ購読は別の保護者に登録されています")
        subscription.p256dh_key = p256dh_key
        subscription.auth_key = auth_key
        subscription.environment = environment
        subscription.is_test_device = is_test_device
        subscription.device_label = device_label
        subscription.user_agent = user_agent
        subscription.status = ParentPushSubscriptionStatus.active
        subscription.failure_count = 0
        subscription.disabled_at = None
        subscription.disabled_reason = None
        subscription.last_seen_at = registered_at
        subscription.updated_at = registered_at
    else:
        subscription = ParentPushSubscription(
            parent_account_id=parent_account_id,
            endpoint=endpoint,
            endpoint_hash=digest,
            p256dh_key=p256dh_key,
            auth_key=auth_key,
            environment=environment,
            is_test_device=is_test_device,
            device_label=device_label,
            user_agent=user_agent,
            last_seen_at=registered_at,
            created_at=registered_at,
            updated_at=registered_at,
        )
        session.add(subscription)
        session.flush()

    if previous_subscription_id and previous_subscription_id != subscription.id:
        previous = session.get(ParentPushSubscription, previous_subscription_id)
        if previous is not None and previous.parent_account_id == parent_account_id:
            disable_parent_push_subscription(
                session,
                previous,
                reason="replaced_on_browser",
                now=registered_at,
            )
    session.add(subscription)
    return subscription


def disable_parent_push_subscription(
    session: Session,
    subscription: ParentPushSubscription,
    *,
    reason: str,
    now: datetime | None = None,
) -> None:
    disabled_at = now or utc_now()
    subscription.status = ParentPushSubscriptionStatus.revoked
    subscription.disabled_at = disabled_at
    subscription.disabled_reason = reason
    subscription.updated_at = disabled_at
    session.add(subscription)


def disable_parent_push_subscription_for_browser(
    session: Session,
    *,
    parent_account_id: int,
    raw_device_cookie: str | None,
    reason: str,
    now: datetime | None = None,
) -> ParentPushSubscription | None:
    subscription_id = read_parent_push_device_cookie(raw_device_cookie)
    if subscription_id is None:
        return None
    subscription = session.get(ParentPushSubscription, subscription_id)
    if subscription is None or subscription.parent_account_id != parent_account_id:
        return None
    disable_parent_push_subscription(
        session,
        subscription,
        reason=reason,
        now=now,
    )
    return subscription


def get_parent_push_preference(
    session: Session,
    *,
    parent_account_id: int,
) -> ParentPushPreference | None:
    return session.exec(
        select(ParentPushPreference).where(
            ParentPushPreference.parent_account_id == parent_account_id
        )
    ).first()


def update_parent_push_preference(
    session: Session,
    *,
    parent_account_id: int,
    push_enabled: bool,
    attendance_confirmation_enabled: bool,
    now: datetime | None = None,
) -> ParentPushPreference:
    updated_at = now or utc_now()
    preference = get_parent_push_preference(
        session,
        parent_account_id=parent_account_id,
    )
    if preference is None:
        preference = ParentPushPreference(
            parent_account_id=parent_account_id,
            push_enabled=push_enabled,
            attendance_confirmation_enabled=attendance_confirmation_enabled,
            created_at=updated_at,
            updated_at=updated_at,
        )
    else:
        preference.push_enabled = push_enabled
        preference.attendance_confirmation_enabled = attendance_confirmation_enabled
        preference.updated_at = updated_at
    session.add(preference)
    return preference


def set_parent_push_device_cookie(response: Response, subscription_id: int) -> None:
    response.set_cookie(
        PARENT_PUSH_DEVICE_COOKIE,
        _signed_subscription_id(subscription_id),
        max_age=PARENT_PUSH_DEVICE_COOKIE_MAX_AGE,
        httponly=True,
        secure=secure_cookie_enabled(),
        samesite="lax",
        path="/parent-portal",
    )


def clear_parent_push_device_cookie(response: Response) -> None:
    response.delete_cookie(PARENT_PUSH_DEVICE_COOKIE, path="/parent-portal")


def read_parent_push_device_cookie(raw_value: str | None) -> int | None:
    if not raw_value or "." not in raw_value:
        return None
    raw_id, signature = raw_value.rsplit(".", 1)
    if not raw_id.isdigit() or not signature:
        return None
    expected = _device_cookie_signature(raw_id)
    if not hmac.compare_digest(signature, expected):
        return None
    return int(raw_id)


def _signed_subscription_id(subscription_id: int) -> str:
    raw_id = str(subscription_id)
    return f"{raw_id}.{_device_cookie_signature(raw_id)}"


def _device_cookie_signature(raw_id: str) -> str:
    secret = os.getenv("HOIKUICT_SECRET_KEY") or "open-hoikuict-development-push-device-key"
    return hmac.new(
        secret.encode("utf-8"),
        raw_id.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
