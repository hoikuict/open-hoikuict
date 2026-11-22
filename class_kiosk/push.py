"""Durable change detection and private, generic Web Push notifications."""
import asyncio
import logging
import os
import base64
from pathlib import Path
from datetime import timedelta
from types import SimpleNamespace
from sqlmodel import Session, select
from database import engine
from models import Child, ChildStatus
from parent_push_service import WebPushParentPushTransport
from time_utils import utc_now, ensure_utc
from .models import KioskAccount, KioskDevice, KioskChange, KioskSubscription, KioskDelivery
from .security import write_lock

log = logging.getLogger(__name__)


def enabled():
    return os.getenv("HOIKUICT_CLASS_KIOSK_ENABLED") == "1" and os.getenv("HOIKUICT_CLASS_KIOSK_WORKER") == "1"


def public_key():
    return os.getenv("HOIKUICT_CLASS_KIOSK_VAPID_PUBLIC_KEY", "")


def validate_configuration():
    if not enabled() or os.getenv("HOIKUICT_CLASS_KIOSK_PUSH") != "webpush":
        return
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization
    private = os.getenv("HOIKUICT_CLASS_KIOSK_VAPID_PRIVATE_KEY", "")
    subject = os.getenv("HOIKUICT_CLASS_KIOSK_VAPID_SUBJECT", "")
    try:
        key = Vapid.from_file(private) if Path(private).is_file() else Vapid.from_string(private)
        key.sign({"sub": subject, "aud": "https://fcm.googleapis.com"})
        expected = base64.urlsafe_b64encode(key.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).rstrip(b"=").decode()
        if expected != public_key():
            raise ValueError("key mismatch")
    except Exception as exc:
        raise RuntimeError("クラス端末の通知鍵・公開鍵・連絡先URIの設定を確認してください。") from exc


def queue_change(session, change, timestamp):
    devices = session.exec(select(KioskDevice).where(KioskDevice.account_id == change.account_id, KioskDevice.active == True)).all()
    for device in devices:
        subscription = session.get(KioskSubscription, device.id)
        if not subscription or not subscription.active or ensure_utc(subscription.created_at) > ensure_utc(timestamp):
            continue
        key = f"{change.id}:{change.version}"
        if session.exec(select(KioskDelivery).where(KioskDelivery.device_id == device.id, KioskDelivery.event_key == key)).first():
            continue
        session.add(KioskDelivery(device_id=device.id, event_key=key, change_id=change.id, version=change.version, expires_at=utc_now()+timedelta(hours=2)))


def scan():
    from .service import sync_all_changes
    with Session(engine) as session:
        write_lock(session)
        sync_all_changes(session)
        session.commit()


def delivery_valid(session, item):
    device = session.get(KioskDevice, item.device_id)
    account = session.get(KioskAccount, device.account_id) if device else None
    subscription = session.get(KioskSubscription, item.device_id)
    valid = device and device.active and account and account.active and subscription and subscription.active and ensure_utc(item.expires_at) > utc_now()
    if valid and item.change_id:
        change = session.get(KioskChange, item.change_id)
        child = session.get(Child, change.child_id) if change else None
        valid = change and change.account_id == account.id and change.version == item.version and not change.acknowledged and child and child.classroom_id == account.classroom_id and child.status == ChildStatus.enrolled
    return subscription if valid else None


def deliver_one(transport=None):
    if transport is None:
        if os.getenv("HOIKUICT_CLASS_KIOSK_PUSH") != "webpush":
            return False
        transport = WebPushParentPushTransport(vapid_private_key=os.getenv("HOIKUICT_CLASS_KIOSK_VAPID_PRIVATE_KEY", ""), vapid_subject=os.getenv("HOIKUICT_CLASS_KIOSK_VAPID_SUBJECT", ""))
    with Session(engine) as session:
        write_lock(session)
        item = session.exec(select(KioskDelivery).where(KioskDelivery.state == "queued", KioskDelivery.next_at <= utc_now()).order_by(KioskDelivery.id).limit(1)).first()
        if not item:
            return False
        subscription = delivery_valid(session, item)
        if not subscription:
            item.state = "cancelled"
            session.add(item)
            session.commit()
            return True
        # Lease prevents concurrent workers from sending simultaneously; expiry allows crash recovery.
        item.attempts += 1
        item.next_at = utc_now() + timedelta(minutes=2)
        session.add(item)
        session.commit()
        data = SimpleNamespace(endpoint=subscription.endpoint, p256dh_key=subscription.p256dh_key, auth_key=subscription.auth_key, environment="production")
        payload = {"title": "クラスへの連絡", "body": "新しい連絡があります。内容を確認してください。" if item.change_id else "通知のテストです。",
                   "tag": f"class-kiosk-{item.change_id or item.event_key}", "url": "/class-kiosk/", "expires_at": ensure_utc(item.expires_at).isoformat()}
        try:
            result = transport.send(subscription=data, payload=payload)
            code = result.provider_status_code
            state = "accepted" if result.result.value == "accepted" else "queued" if result.result.value == "retryable_failed" else "failed"
        except Exception as exc:
            code, state = None, "queued"
            log.warning("Class kiosk push transport unavailable (delivery %s, %s)", item.id, type(exc).__name__)
        session.refresh(item)
        item.state = "failed" if item.attempts >= 6 and state == "queued" else state
        item.provider_code = code
        item.next_at = utc_now() + timedelta(seconds=min(900, 15 * 2 ** item.attempts))
        session.add(item)
        if code in {404, 410}:
            # Do not invalidate a subscription refreshed while this request was in flight.
            session.refresh(subscription)
            if subscription.endpoint == data.endpoint:
                subscription.active = False
                session.add(subscription)
        session.commit()
    return True


async def worker_loop():
    while True:
        try:
            await asyncio.to_thread(scan)
            for _ in range(10):
                if not await asyncio.to_thread(deliver_one):
                    break
        except Exception:
            log.exception("Class kiosk worker failed")
        await asyncio.sleep(5)
