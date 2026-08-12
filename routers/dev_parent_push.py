from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from auth import StaffUser, get_current_staff_user
from database import get_session
from models import (
    NotificationDeliveryChannel,
    ParentNotification,
    ParentNotificationDelivery,
    ParentPushDeliveryAttempt,
    ParentPushDeliveryTarget,
    ParentPushSubscription,
)
from parent_push_service import PUSH_SCHEMA_VERSION, SAFE_PUSH_BODY, SAFE_PUSH_TITLE
from parent_push_operations import build_parent_push_daily_metrics
from security_config import deployment_environment, parent_push_transport
from template_utils import create_templates


router = APIRouter(prefix="/dev/push-notifications", tags=["dev_parent_push"])
templates = create_templates()


@router.get("", response_class=HTMLResponse)
def capture_dashboard(
    request: Request,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    if deployment_environment() != "development":
        raise HTTPException(status_code=404, detail="Not Found")

    deliveries = session.exec(
        select(ParentNotificationDelivery)
        .where(ParentNotificationDelivery.channel == NotificationDeliveryChannel.push)
        .order_by(ParentNotificationDelivery.created_at.desc())
        .limit(100)
    ).all()
    items = [_dashboard_item(session, delivery) for delivery in deliveries]
    metrics = build_parent_push_daily_metrics(session)
    return templates.TemplateResponse(
        request,
        "dev/parent_push_capture.html",
        {
            "current_user": current_user,
            "transport": parent_push_transport(),
            "metrics": metrics,
            "items": items,
        },
    )


def _dashboard_item(
    session: Session,
    delivery: ParentNotificationDelivery,
) -> dict[str, object]:
    notification = session.get(ParentNotification, delivery.notification_id)
    targets = session.exec(
        select(ParentPushDeliveryTarget)
        .where(ParentPushDeliveryTarget.delivery_id == delivery.id)
        .order_by(ParentPushDeliveryTarget.id)
    ).all()
    target_items = [_target_item(session, notification, delivery, target) for target in targets]
    return {
        "delivery": delivery,
        "notification": notification,
        "parent_label": (
            f"保護者 #{notification.parent_account_id}" if notification else "保護者不明"
        ),
        "targets": target_items,
    }


def _target_item(
    session: Session,
    notification: ParentNotification | None,
    delivery: ParentNotificationDelivery,
    target: ParentPushDeliveryTarget,
) -> dict[str, object]:
    subscription = session.get(ParentPushSubscription, target.subscription_id)
    attempt = session.exec(
        select(ParentPushDeliveryAttempt)
        .where(ParentPushDeliveryAttempt.target_id == target.id)
        .order_by(ParentPushDeliveryAttempt.attempt_no.desc())
    ).first()
    payload_preview = None
    if notification is not None:
        payload_preview = {
            "schema_version": PUSH_SCHEMA_VERSION,
            "notification_id": notification.id,
            "target_id": target.id,
            "kind": notification.kind.value,
            "title": SAFE_PUSH_TITLE,
            "body": SAFE_PUSH_BODY,
            "action_url": f"/parent-portal/notifications/{notification.id}",
            "expires_at": delivery.expires_at.isoformat() if delivery.expires_at else None,
        }
    return {
        "target": target,
        "device_label": subscription.device_label if subscription else None,
        "subscription_status": subscription.status.value if subscription else "missing",
        "attempt": attempt,
        "payload_preview": payload_preview,
        "payload_preview_json": (
            json.dumps(payload_preview, ensure_ascii=False, indent=2)
            if payload_preview is not None
            else None
        ),
    }
