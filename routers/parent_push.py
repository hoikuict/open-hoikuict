from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
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
from security_config import deployment_environment


router = APIRouter(prefix="/parent-portal/push", tags=["parent_push"])


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
