import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import timedelta
from ipaddress import ip_address, ip_network

from fastapi import Depends, HTTPException, Request, Response
from sqlmodel import Session, select
from database import get_session
from models import Classroom
from security_config import is_production, secure_cookie_enabled, csrf_enforced
from time_utils import ensure_utc, utc_now
from .models import KioskAccount, KioskDevice, KioskEnrollment, KioskAttempt


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def cookie_name():
    return "__Host-class-kiosk" if secure_cookie_enabled() else "class_kiosk_device"


# Browser persistence is renewed on authenticated use; registration itself has
# no time limit. Clearing browser data still requires a new enrollment.
DEVICE_COOKIE_SECONDS = 365 * 86400


def set_device_cookie(response, token):
    response.set_cookie(cookie_name(), token, httponly=True, secure=secure_cookie_enabled(),
                        samesite="strict", path="/", max_age=DEVICE_COOKIE_SECONDS)


def gate(request: Request):
    if os.getenv("HOIKUICT_CLASS_KIOSK_ENABLED") != "1":
        raise HTTPException(404)
    if not csrf_enforced() or len(os.getenv("HOIKUICT_SECRET_KEY", "")) < 32:
        raise HTTPException(503, "クラス端末にはCSRF保護と署名鍵の設定が必要です。")
    # Dedicated ingress must overwrite this header. Never infer trust from X-Forwarded-For.
    marker = os.getenv("HOIKUICT_CLASS_KIOSK_INGRESS_KEY", "")
    if is_production() and (len(marker) < 32 or not hmac.compare_digest(request.headers.get("x-class-kiosk-ingress", ""), marker)):
        raise HTTPException(403, "園内の接続から利用してください。")
    raw = os.getenv("HOIKUICT_CLASS_KIOSK_NETWORKS", "127.0.0.1/32,::1/128")
    try:
        host = ip_address(request.client.host)
        permitted = any(host in ip_network(n.strip()) for n in raw.split(",") if n.strip())
    except ValueError:
        permitted = False
    if not permitted:
        raise HTTPException(403, "この接続ではクラス端末を利用できません。")


@dataclass(frozen=True)
class Principal:
    device_id: int
    account_id: int
    classroom_id: int
    name: str
    device_name: str
    token_hash: str


def authenticate(session, token_hash):
    device = session.exec(select(KioskDevice).where(KioskDevice.token_hash == token_hash)).first()
    account = session.get(KioskAccount, device.account_id) if device else None
    classroom = session.get(Classroom, account.classroom_id) if account else None
    if not device or not device.active or not account or not account.active or not classroom:
        raise HTTPException(401, "端末の登録が必要です。管理者に登録コードを発行してもらってください。")
    return Principal(device.id, account.id, classroom.id, classroom.name, device.name, token_hash)


def current_device(request: Request, response: Response, session: Session = Depends(get_session)):
    gate(request)
    token = request.cookies.get(cookie_name(), "")
    principal = authenticate(session, digest(token))
    set_device_cookie(response, token)
    return principal


def write_lock(session, principal=None):
    # SQLite's writer lock covers the re-check and all mutations in one transaction.
    session.rollback()
    if session.get_bind().dialect.name != "sqlite":
        raise HTTPException(503, "この保存処理はSQLite環境での検証が必要です。")
    session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    return authenticate(session, principal.token_hash) if principal else None


def enroll(session, code, source):
    write_lock(session)
    now = utc_now()
    source_hash = digest(source)
    recent = session.exec(select(KioskAttempt).where(KioskAttempt.source_hash == source_hash, KioskAttempt.created_at > now - timedelta(minutes=10))).all()
    if len(recent) >= 10:
        raise HTTPException(429, "試行回数が多いため、10分後に再試行してください。")
    session.add(KioskAttempt(source_hash=source_hash))
    enrollment = session.exec(select(KioskEnrollment).where(KioskEnrollment.code_hash == digest(code.strip().upper()))).first()
    account = session.get(KioskAccount, enrollment.account_id) if enrollment else None
    if not enrollment or enrollment.used_at or ensure_utc(enrollment.expires_at) <= now or not account or not account.active:
        session.commit()
        raise HTTPException(400, "登録コードが無効、使用済み、または期限切れです。")
    token = secrets.token_urlsafe(48)
    device = KioskDevice(account_id=account.id, name=enrollment.name, token_hash=digest(token))
    enrollment.used_at = now
    session.add(device)
    session.add(enrollment)
    session.commit()
    return token, DEVICE_COOKIE_SECONDS
