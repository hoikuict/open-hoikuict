from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from auth import get_current_parent_account_id
from database import get_session
from models import (
    ParentAccount,
    ParentAccountStatus,
    ParentPushSubscription,
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
    parent_push_vapid_public_key,
)
from template_utils import create_templates


router = APIRouter(prefix="/parent-portal/push", tags=["parent_push"])
settings_router = APIRouter(prefix="/parent-portal", tags=["parent_push"])
templates = create_templates()


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


class ParentPushReceiptInput(BaseModel):
    token: str = Field(min_length=20, max_length=256)


@settings_router.get("/push-settings", response_class=HTMLResponse)
def push_settings(
    request: Request,
    session: Session = Depends(get_session),
):
    parent = _require_parent_account(request, session)
    preference = get_parent_push_preference(session, parent_account_id=parent.id)
    return templates.TemplateResponse(
        request,
        "parent_portal/push_settings.html",
        {
            "current_parent_user": parent,
            "parent_portal_mode": True,
            "preference": preference,
            "vapid_key_available": bool(parent_push_vapid_public_key()),
            "test_device_mode": (
                deployment_environment() == "development" or is_public_demo()
            ),
            "public_demo_mode": is_public_demo(),
        },
    )


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
            '</svg>'
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
    return {"available": bool(public_key), "public_key": public_key or None}


@router.post("/receipts/{target_id}/shown")
def record_shown_receipt(
    target_id: int,
    payload: ParentPushReceiptInput,
    session: Session = Depends(get_session),
):
    return _record_receipt(session, target_id=target_id, event="shown", token=payload.token)


@router.post("/receipts/{target_id}/clicked")
def record_clicked_receipt(
    target_id: int,
    payload: ParentPushReceiptInput,
    session: Session = Depends(get_session),
):
    return _record_receipt(session, target_id=target_id, event="clicked", token=payload.token)


@router.post("/subscriptions")
def register_subscription(
    payload: ParentPushSubscriptionInput,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
):
    parent = _require_parent_account(request, session)
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
    if subscription is not None and subscription.endpoint == payload.endpoint:
        disable_parent_push_subscription(
            session,
            subscription,
            reason="parent_unsubscribed",
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
    }


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
    session.commit()
    session.refresh(preference)
    return {
        "push_enabled": preference.push_enabled,
        "attendance_confirmation_enabled": preference.attendance_confirmation_enabled,
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
        raise HTTPException(status_code=410, detail="Receiptの有効期限が切れています") from exc
    except ParentPushReceiptStateError as exc:
        raise HTTPException(status_code=409, detail="Receiptを記録できない状態です") from exc
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
