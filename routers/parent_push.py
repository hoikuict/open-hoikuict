from __future__ import annotations

from urllib.parse import urlsplit
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from auth import get_current_parent_account_id
from database import get_session
from models import (
    ParentAccount,
    ParentAccountStatus,
    ParentPushSubscriptionStatus,
    ParentPushSubscription,
    ParentNotification,
    ParentNotificationKind,
    ParentNotificationDelivery,
    NotificationDeliveryChannel,
    ParentPushDeliveryTarget,
    ParentEmailPreference,
)
from parent_push_subscription_service import (
    PARENT_PUSH_DEVICE_COOKIE,
    clear_parent_push_device_cookie,
    disable_parent_push_subscription,
    endpoint_hash,
    get_parent_push_preference,
    read_parent_push_device_cookie,
    register_parent_push_subscription,
    set_parent_push_device_cookie,
    update_parent_push_preference,
)
from parent_push_service import (
    ParentPushReceiptExpiredError,
    ParentPushReceiptNotFoundError,
    ParentPushReceiptStateError,
    record_parent_push_receipt,
)
from security_config import (
    deployment_environment,
    is_public_demo,
    parent_auth_mode,
    parent_push_transport,
    parent_push_vapid_public_key,
)
from parent_push_validation import validate_production_subscription
from template_utils import create_templates
from time_utils import utc_now
from parent_notification_email_service import email_enabled


router = APIRouter(prefix="/parent-portal/push", tags=["parent_push"])
settings_router = APIRouter(prefix="/parent-portal", tags=["parent_push"])
templates = create_templates()


def _push_available() -> bool:
    return bool(parent_push_vapid_public_key()) and (
        (deployment_environment() == "development" or is_public_demo())
        and parent_push_transport() in {"capture", "webpush"}
        or deployment_environment() == "production"
        and parent_auth_mode() == "local_password"
        and parent_push_transport() == "webpush"
    )


def _validate_push_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Push endpointはHTTPS URLで指定してください")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Push endpointの形式が不正です")
    return value


class ParentPushSubscriptionKeysInput(BaseModel):
    p256dh: str = Field(min_length=1, max_length=1024)
    auth: str = Field(min_length=1, max_length=1024)


class ParentPushSubscriptionInput(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: ParentPushSubscriptionKeysInput
    device_label: str | None = Field(default=None, max_length=100)
    is_test_device: bool = False

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        return _validate_push_endpoint(value)


class ParentPushEndpointInput(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        return _validate_push_endpoint(value)


class ParentPushPreferenceInput(BaseModel):
    push_enabled: bool
    attendance_confirmation_enabled: bool
    email_enabled: bool | None = None


class ParentPushReceiptInput(BaseModel):
    token: str = Field(min_length=20, max_length=256)


@settings_router.get("/push-settings", response_class=HTMLResponse)
def push_settings(
    request: Request,
    session: Session = Depends(get_session),
):
    parent = _require_parent_account(request, session)
    preference = get_parent_push_preference(session, parent_account_id=parent.id)
    public_demo_mode = is_public_demo()
    browser_subscription_owner_mismatch = False
    if public_demo_mode:
        subscription_id = read_parent_push_device_cookie(
            request.cookies.get(PARENT_PUSH_DEVICE_COOKIE)
        )
        browser_subscription = (
            session.get(ParentPushSubscription, subscription_id)
            if subscription_id is not None
            else None
        )
        browser_subscription_owner_mismatch = bool(
            browser_subscription is not None
            and browser_subscription.parent_account_id != parent.id
        )
    active_subscriptions = session.exec(
        select(ParentPushSubscription).where(
            ParentPushSubscription.parent_account_id == parent.id,
            ParentPushSubscription.status == ParentPushSubscriptionStatus.active,
            ParentPushSubscription.environment == deployment_environment(),
        )
    ).all()
    response = templates.TemplateResponse(
        request,
        "parent_portal/push_settings.html",
        {
            "current_parent_user": parent,
            "parent_portal_mode": True,
            "preference": preference,
            "email_preference": session.get(ParentEmailPreference, parent.id),
            "active_subscriptions": active_subscriptions,
            "vapid_key_available": bool(parent_push_vapid_public_key()),
            "test_device_mode": (
                deployment_environment() == "development" or is_public_demo()
            ),
            "public_demo_mode": public_demo_mode,
            "browser_subscription_owner_mismatch": (
                browser_subscription_owner_mismatch
            ),
            "push_available": _push_available(),
            "development_mode": deployment_environment() == "development",
        },
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@settings_router.get("/manifest.webmanifest")
def parent_portal_manifest():
    return Response(
        content=(
            '{"name":"open-hoikuict 保護者ポータル",'
            '"short_name":"保護者ポータル",'
            '"start_url":"/parent-portal/",'
            '"scope":"/parent-portal/",'
            '"display":"standalone",'
            '"background_color":"#f8fafc",'
            '"theme_color":"#4338ca",'
            '"icons":[{"src":"/parent-portal/push-icon.svg",'
            '"sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]}'
        ),
        media_type="application/manifest+json",
    )


@settings_router.get("/push-icon.svg")
def parent_push_icon():
    return Response(
        content=(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
            '<rect width="512" height="512" rx="96" fill="#4338ca"/>'
            '<path d="M128 176c0-70 57-128 128-128s128 58 128 128v74l42 66H86l42-66z" '
            'fill="#fff"/><circle cx="256" cy="382" r="54" fill="#a5b4fc"/>'
            "</svg>"
        ),
        media_type="image/svg+xml",
    )


@settings_router.get("/push-service-worker.js")
def parent_push_service_worker():
    return Response(
        content=templates.get_template("parent_portal/push_service_worker.js").render(),
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Service-Worker-Allowed": "/parent-portal/",
        },
    )


@router.get("/public-key")
def get_public_key(
    request: Request,
    session: Session = Depends(get_session),
):
    _require_parent_account(request, session)
    public_key = parent_push_vapid_public_key()
    return {
        "available": _push_available(),
        "public_key": public_key if _push_available() else None,
    }


@router.post("/receipts/{target_id}/shown")
def record_shown_receipt(
    target_id: int,
    payload: ParentPushReceiptInput,
    session: Session = Depends(get_session),
):
    return _record_receipt(
        session, target_id=target_id, event="shown", token=payload.token
    )


@router.post("/receipts/{target_id}/clicked")
def record_clicked_receipt(
    target_id: int,
    payload: ParentPushReceiptInput,
    session: Session = Depends(get_session),
):
    return _record_receipt(
        session, target_id=target_id, event="clicked", token=payload.token
    )


@router.post("/subscriptions")
def register_subscription(
    payload: ParentPushSubscriptionInput,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    parent = _require_parent_account(request, session)
    if deployment_environment() == "production" and not is_public_demo():
        if not _push_available():
            raise HTTPException(503, "園側の通知設定は準備中です")
        try:
            validate_production_subscription(
                payload.endpoint, payload.keys.p256dh, payload.keys.auth
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
    previous_subscription_id = read_parent_push_device_cookie(
        request.cookies.get(PARENT_PUSH_DEVICE_COOKIE)
    )
    try:
        subscription = register_parent_push_subscription(
            session,
            parent_account_id=parent.id,
            endpoint=payload.endpoint,
            p256dh_key=payload.keys.p256dh,
            auth_key=payload.keys.auth,
            environment=deployment_environment(),
            is_test_device=(
                payload.is_test_device
                and (deployment_environment() == "development" or is_public_demo())
            ),
            device_label=(payload.device_label or "").strip() or None,
            user_agent=(request.headers.get("user-agent") or "")[:512] or None,
            previous_subscription_id=previous_subscription_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.commit()
    session.refresh(subscription)
    set_parent_push_device_cookie(response, subscription.id)
    return _subscription_response(subscription)


@router.delete("/subscriptions/current")
def delete_current_subscription(
    payload: ParentPushEndpointInput,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    parent = _require_parent_account(request, session)
    subscription = session.exec(
        select(ParentPushSubscription).where(
            ParentPushSubscription.parent_account_id == parent.id,
            ParentPushSubscription.endpoint_hash == endpoint_hash(payload.endpoint),
        )
    ).first()
    disabled_reason = "parent_unsubscribed"
    if subscription is None and is_public_demo():
        subscription_id = read_parent_push_device_cookie(
            request.cookies.get(PARENT_PUSH_DEVICE_COOKIE)
        )
        previous_parent_subscription = (
            session.get(ParentPushSubscription, subscription_id)
            if subscription_id is not None
            else None
        )
        if (
            previous_parent_subscription is not None
            and previous_parent_subscription.endpoint == payload.endpoint
        ):
            subscription = previous_parent_subscription
            disabled_reason = "demo_parent_switch"
    if subscription is not None and subscription.endpoint == payload.endpoint:
        disable_parent_push_subscription(
            session,
            subscription,
            reason=disabled_reason,
        )
        session.commit()
    clear_parent_push_device_cookie(response)
    return {"status": "revoked" if subscription is not None else "not_found"}


@router.get("/preferences")
def get_preferences(
    request: Request,
    session: Session = Depends(get_session),
):
    parent = _require_parent_account(request, session)
    preference = get_parent_push_preference(session, parent_account_id=parent.id)
    return {
        "push_enabled": preference.push_enabled if preference else True,
        "attendance_confirmation_enabled": (
            preference.attendance_confirmation_enabled if preference else True
        ),
        "email_enabled": email_enabled(session, parent.id),
    }


@router.get("/subscriptions/current")
def current_subscription(request: Request, session: Session = Depends(get_session)):
    parent = _require_parent_account(request, session)
    subscription = _current_subscription(request, session, parent.id)
    devices = session.exec(
        select(ParentPushSubscription).where(
            ParentPushSubscription.parent_account_id == parent.id,
            ParentPushSubscription.status == ParentPushSubscriptionStatus.active,
            ParentPushSubscription.environment == deployment_environment(),
        )
    ).all()
    return {
        "registered": subscription is not None,
        "devices": [
            {"device_label": device.device_label or "名称未設定の端末"}
            for device in devices
        ],
    }


def _current_subscription(request, session, parent_id):
    subscription_id = read_parent_push_device_cookie(
        request.cookies.get(PARENT_PUSH_DEVICE_COOKIE)
    )
    subscription = (
        session.get(ParentPushSubscription, subscription_id)
        if subscription_id
        else None
    )
    if (
        subscription
        and subscription.parent_account_id == parent_id
        and subscription.status == ParentPushSubscriptionStatus.active
        and subscription.environment == deployment_environment()
    ):
        return subscription
    return None


@router.post("/test")
def send_test_notification(request: Request, session: Session = Depends(get_session)):
    parent = _require_parent_account(request, session)
    if not _push_available() or parent_push_transport() != "webpush":
        raise HTTPException(503, "園側の通知設定は準備中です")
    subscription = _current_subscription(request, session, parent.id)
    if subscription is None:
        raise HTTPException(409, "先にこの端末で通知を受け取る設定をしてください")
    preference = get_parent_push_preference(session, parent_account_id=parent.id)
    if preference and not preference.push_enabled:
        raise HTTPException(
            409, "「プッシュ通知を利用する」を保存してからお試しください"
        )
    now = utc_now()
    recent = select(ParentNotification).where(
        ParentNotification.parent_account_id == parent.id,
        ParentNotification.kind == ParentNotificationKind.push_test,
    )
    if session.exec(
        recent.where(ParentNotification.created_at > now - timedelta(seconds=60))
    ).first():
        raise HTTPException(429, "テスト通知は60秒以上あけてお試しください")
    count = session.exec(
        select(func.count())
        .select_from(ParentNotification)
        .where(
            ParentNotification.parent_account_id == parent.id,
            ParentNotification.kind == ParentNotificationKind.push_test,
            ParentNotification.created_at > now - timedelta(days=1),
        )
    ).one()
    if count >= 10:
        raise HTTPException(429, "テスト通知は1日10回までです")
    notification = ParentNotification(
        parent_account_id=parent.id,
        kind=ParentNotificationKind.push_test,
        title="通知のテスト",
        body="この端末で通知を受け取れるか確認するための通知です。",
        action_url="/parent-portal/push-settings",
        source_type="push_test",
        source_id=str(int(now.timestamp()) // 60),
        created_at=now,
    )
    try:
        session.add(notification)
        session.flush()
        delivery = ParentNotificationDelivery(
            notification_id=notification.id,
            channel=NotificationDeliveryChannel.push,
            expires_at=now + timedelta(minutes=5),
            targets_resolved_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(delivery)
        session.flush()
        session.add(
            ParentPushDeliveryTarget(
                delivery_id=delivery.id, subscription_id=subscription.id
            )
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(429, "テスト通知は60秒以上あけてお試しください") from None
    return {"notification_id": notification.id, "status": "pending"}


@router.get("/test/{notification_id}")
def test_notification_status(
    notification_id: int, request: Request, session: Session = Depends(get_session)
):
    parent = _require_parent_account(request, session)
    target = session.exec(
        select(ParentPushDeliveryTarget)
        .join(
            ParentNotificationDelivery,
            ParentNotificationDelivery.id == ParentPushDeliveryTarget.delivery_id,
        )
        .join(
            ParentNotification,
            ParentNotification.id == ParentNotificationDelivery.notification_id,
        )
        .where(
            ParentNotification.id == notification_id,
            ParentNotification.parent_account_id == parent.id,
            ParentNotification.kind == ParentNotificationKind.push_test,
        )
    ).first()
    if target is None:
        raise HTTPException(404, "テスト通知が見つかりません")
    return {"status": target.status.value}


@router.post("/preferences")
def save_preferences(
    payload: ParentPushPreferenceInput,
    request: Request,
    session: Session = Depends(get_session),
):
    parent = _require_parent_account(request, session)
    preference = update_parent_push_preference(
        session,
        parent_account_id=parent.id,
        push_enabled=payload.push_enabled,
        attendance_confirmation_enabled=payload.attendance_confirmation_enabled,
    )
    if payload.email_enabled is not None:
        email_preference = session.get(ParentEmailPreference, parent.id) or ParentEmailPreference(parent_account_id=parent.id)
        email_preference.attendance_confirmation_enabled = payload.email_enabled
        email_preference.updated_at = utc_now()
        session.add(email_preference)
    session.commit()
    session.refresh(preference)
    return {
        "push_enabled": preference.push_enabled,
        "attendance_confirmation_enabled": preference.attendance_confirmation_enabled,
        "email_enabled": email_enabled(session, parent.id),
    }


def _record_receipt(
    session: Session,
    *,
    target_id: int,
    event: str,
    token: str,
):
    try:
        target = record_parent_push_receipt(
            session,
            target_id=target_id,
            event=event,
            token=token,
        )
    except ParentPushReceiptNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Receiptが見つかりません") from exc
    except ParentPushReceiptExpiredError as exc:
        raise HTTPException(
            status_code=410, detail="Receiptの有効期限が切れています"
        ) from exc
    except ParentPushReceiptStateError as exc:
        raise HTTPException(
            status_code=409, detail="Receiptを記録できない状態です"
        ) from exc
    session.commit()
    session.refresh(target)
    return {"status": "recorded", "event": event}


def _require_parent_account(request: Request, session: Session) -> ParentAccount:
    parent_account_id = get_current_parent_account_id(request)
    if not parent_account_id:
        raise HTTPException(status_code=401, detail="保護者ログインが必要です")
    parent = session.get(ParentAccount, parent_account_id)
    if parent is None or parent.status != ParentAccountStatus.active:
        raise HTTPException(status_code=401, detail="有効な保護者ログインが必要です")
    return parent


def _subscription_response(subscription: ParentPushSubscription) -> dict[str, object]:
    return {
        "id": subscription.id,
        "status": subscription.status.value,
        "device_label": subscription.device_label,
        "environment": subscription.environment,
        "created_at": subscription.created_at,
        "last_seen_at": subscription.last_seen_at,
    }
