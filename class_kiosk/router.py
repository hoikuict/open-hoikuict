import os
import base64
from io import BytesIO
import secrets
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4
from typing import Literal
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select
from auth import get_current_staff_user, require_admin
from csrf import verify_csrf
from database import get_session
from models import Classroom, Message, MessageAttachment
from parent_push_validation import validate_production_subscription
from time_utils import ensure_utc, utc_now
from .models import (KioskAccount, KioskDevice, KioskEnrollment, KioskChange, KioskMessageOwner,
                     KioskSubscription, KioskDelivery, KioskOperation, KioskAudit)
from .security import gate, current_device, set_device_cookie, digest, enroll, write_lock
from . import service, push

ROOT = Path(__file__).resolve().parent
router = APIRouter(prefix="/class-kiosk", dependencies=[Depends(gate), Depends(verify_csrf)])
admin_router = APIRouter(prefix="/settings/class-kiosk", dependencies=[Depends(gate), Depends(require_admin), Depends(verify_csrf)])


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EnrollmentInput(StrictBody):
    code: str = Field(min_length=1, max_length=64)


class AttendanceRow(StrictBody):
    id: int
    status: str = Field(max_length=30)
    reason: str = Field(default="", max_length=500)
    version: str = Field(max_length=64)


class AttendanceReview(StrictBody):
    day: str = Field(max_length=10)
    rows: list[AttendanceRow] = Field(max_length=300)


class AttendanceSend(StrictBody):
    request_id: str = Field(max_length=36)
    token: str = Field(max_length=500000)


class Acknowledgement(StrictBody):
    version: str = Field(max_length=64)
    acknowledged: bool


class Registration(StrictBody):
    classroom_id: int
    name: str = Field(min_length=1, max_length=80)


class SubscriptionInput(StrictBody):
    endpoint: str = Field(max_length=4096)
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=200)


def shell(request, admin=False):
    html = (ROOT / "admin.html" if admin else ROOT / "index.html").read_text(encoding="utf-8")
    from html import escape
    return HTMLResponse(html.replace("{{CSRF}}", escape(request.state.csrf_token, quote=True)), headers={"Cache-Control": "no-store",
        "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'",
        "Referrer-Policy": "no-referrer"})


@router.get("/")
def index(request: Request):
    return shell(request)


@router.get("/sw.js")
def service_worker():
    return FileResponse(ROOT / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/class-kiosk/"})


@router.post("/enroll")
def activate(data: EnrollmentInput, request: Request, response: Response, session: Session = Depends(get_session)):
    token, _ = enroll(session, data.code, request.client.host)
    set_device_cookie(response, token)
    return {"registered": True}


@router.get("/api/state")
def state(session: Session = Depends(get_session), p=Depends(current_device)):
    p = write_lock(session, p)
    service.sync_changes(session, p)
    session.commit()
    subscription = session.get(KioskSubscription, p.device_id)
    latest = session.exec(select(KioskDelivery).where(KioskDelivery.device_id == p.device_id).order_by(KioskDelivery.id.desc()).limit(1)).first()
    return {"class_name": p.name, "device_name": p.device_name, "day": str(service.local_today()), "rows": service.roster(session, p),
            "changes": service.changes_list(session, p), "messages": service.timeline(session, p),
            "home_timeline": service.home_timeline(session, p), "push_key": push.public_key(),
            "push_enabled": bool(subscription and subscription.active), "push_status": latest.state if latest else None,
            "time": service.format_jst_datetime(utc_now())}


@router.get("/api/children/{child_id}")
def detail(child_id: int, day: date | None = None, session: Session = Depends(get_session), p=Depends(current_device)):
    return service.child_detail(session, p, child_id, day)


@router.get("/api/history")
def change_history(scope: Literal["class", "all"] = "class", session: Session = Depends(get_session), p=Depends(current_device)):
    p = write_lock(session, p)
    if scope == "all":
        service.sync_all_changes(session)
    else:
        service.sync_changes(session, p)
    changes = service.changes_list(session, p, today_only=True, all_classes=scope == "all")
    session.commit()
    return {"scope": scope, "day": str(service.local_today()), "changes": changes}


@router.post("/api/attendance/review")
def review(data: AttendanceReview, session: Session = Depends(get_session), p=Depends(current_device)):
    return service.review_attendance(session, p, data.model_dump())


@router.post("/api/attendance/send")
def send(data: AttendanceSend, session: Session = Depends(get_session), p=Depends(current_device)):
    return service.send_attendance(session, p, data.request_id, data.token)


@router.get("/api/operations/{request_id}")
def result(request_id: str, session: Session = Depends(get_session), p=Depends(current_device)):
    op = session.exec(select(KioskOperation).where(KioskOperation.device_id == p.device_id, KioskOperation.request_id == request_id)).first()
    return {"saved": bool(op), "result": op.result if op else None}


@router.post("/api/changes/{change_id}/ack")
def acknowledge(change_id: int, data: Acknowledgement, session: Session = Depends(get_session), p=Depends(current_device)):
    p = write_lock(session, p)
    service.sync_changes(session, p)
    change = session.get(KioskChange, change_id)
    if not change or change.account_id != p.account_id:
        raise HTTPException(404)
    service.child_in_class(session, p, change.child_id)
    if change.version != data.version:
        session.commit()  # Preserve the newly discovered version, without acknowledging it.
        raise HTTPException(409, "新しい変更が届いています。最新の内容を確認してください。")
    if change.acknowledged != data.acknowledged:
        change.acknowledged = data.acknowledged
        session.add(change)
        service.audit(session, p, "acknowledgement", {"change_id": change_id, **data.model_dump()})
    session.commit()
    return {"acknowledged": data.acknowledged}


@router.get("/api/messages")
def messages(before: int | None = None, session: Session = Depends(get_session), p=Depends(current_device)):
    return service.timeline(session, p, before)


@router.get("/api/messages/{message_id}")
def thread(message_id: int, session: Session = Depends(get_session), p=Depends(current_device)):
    parent = session.get(Message, message_id)
    if not parent or parent.parent_message_id:
        raise HTTPException(404)
    replies = session.exec(select(Message).where(Message.parent_message_id == message_id).order_by(Message.id)).all()
    return {"parent": service.message_json(session, p, parent), "replies": [service.message_json(session, p, m) for m in replies]}


@router.post("/api/messages")
def post_message(request_id: str = Form(..., max_length=36), body: str = Form("", max_length=10000), parent_id: int | None = Form(None),
                 reply_to_id: int | None = Form(None), files: list[UploadFile] = File(default=[]), session: Session = Depends(get_session), p=Depends(current_device)):
    from routers.staff_rooms import MESSAGE_UPLOAD_ROOT, _safe_filename
    if len(files) > 5:
        raise HTTPException(422, "添付は5個までです。")
    uploads = []
    for f in files:
        if not f.filename:
            continue
        content = f.file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(422, "添付は1個10MBまでです。")
        if content:
            uploads.append((_safe_filename(f.filename), f.content_type, content))
    if not body.strip() and not uploads:
        raise HTTPException(422, "本文または添付を入力してください。")
    p = write_lock(session, p)
    content_stamp = {"body": body, "parent": parent_id, "reply_to": reply_to_id, "files": [(name, kind, service.fingerprint(data.hex())) for name, kind, data in uploads]}
    previous, request_id, stamp = service.operation(session, p, request_id, "message", content_stamp)
    if previous:
        return previous.result
    parent = session.get(Message, parent_id) if parent_id else None
    if parent_id and (not parent or parent.parent_message_id or parent.is_deleted):
        raise HTTPException(409, "返信先が削除されています。")
    if reply_to_id:
        target = session.get(Message, reply_to_id)
        if not target or target.is_deleted or not parent or (target.parent_message_id or target.id) != parent.id:
            raise HTTPException(409, "返信先を確認してください。")
        body = f"{target.author_name}さんへの返信\n\n{body}"
    message = Message(room_id=parent.room_id if parent else p.classroom_id, parent_message_id=parent_id, body=body.strip(), author_name=p.name)
    session.add(message)
    session.flush()
    session.add(KioskMessageOwner(message_id=message.id, account_id=p.account_id, device_id=p.device_id))
    created = []
    try:
        MESSAGE_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        for name, kind, data in uploads:
            storage = uuid4().hex + Path(name).suffix
            path = MESSAGE_UPLOAD_ROOT / storage
            path.write_bytes(data)
            created.append(path)
            session.add(MessageAttachment(message_id=message.id, original_filename=name, storage_path=storage, content_type=kind, file_size=len(data), is_image=False))
        return service.finish_operation(session, p, request_id, "message", stamp, {"message_id": message.id, "parent_id": parent_id})
    except Exception:
        session.rollback()
        for path in created:
            path.unlink(missing_ok=True)
        raise


@router.post("/api/messages/{message_id}/delete")
def delete_message(message_id: int, session: Session = Depends(get_session), p=Depends(current_device)):
    p = write_lock(session, p)
    owner = session.get(KioskMessageOwner, message_id)
    message = session.get(Message, message_id)
    if not owner or owner.account_id != p.account_id or not message:
        raise HTTPException(403, "自クラスの投稿だけ削除できます。")
    if not message.deleted_at:
        message.deleted_at, message.deleted_by, message.updated_at = utc_now(), p.name, utc_now()
        session.add(message)
        service.audit(session, p, "message_delete", {"message_id": message_id})
    session.commit()
    return {"deleted": True}


@router.get("/api/attachments/{attachment_id}")
def attachment(attachment_id: int, session: Session = Depends(get_session), p=Depends(current_device)):
    from routers.staff_rooms import MESSAGE_UPLOAD_ROOT
    item = session.get(MessageAttachment, attachment_id)
    message = session.get(Message, item.message_id) if item else None
    if not item or not message or message.is_deleted:
        raise HTTPException(404)
    root = MESSAGE_UPLOAD_ROOT.resolve()
    path = (root / item.storage_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, filename=item.original_filename, media_type="application/octet-stream", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.post("/api/push/subscribe")
def subscribe(data: SubscriptionInput, session: Session = Depends(get_session), p=Depends(current_device)):
    if not push.public_key() or os.getenv("HOIKUICT_CLASS_KIOSK_PUSH") != "webpush":
        raise HTTPException(503, "通知サービスは準備中です。")
    try:
        validate_production_subscription(data.endpoint, data.p256dh, data.auth)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    p = write_lock(session, p)
    previous = session.exec(select(KioskSubscription).where(KioskSubscription.endpoint == data.endpoint)).first()
    if previous and previous.device_id != p.device_id:
        previous_device = session.get(KioskDevice, previous.device_id)
        if previous_device and previous_device.active:
            raise HTTPException(409, "この通知先は別の登録端末で使用中です。以前の端末登録を停止してください。")
        session.delete(previous)
        session.flush()
    subscription = session.get(KioskSubscription, p.device_id) or KioskSubscription(device_id=p.device_id, endpoint=data.endpoint, p256dh_key=data.p256dh, auth_key=data.auth)
    subscription.endpoint, subscription.p256dh_key, subscription.auth_key, subscription.active = data.endpoint, data.p256dh, data.auth, True
    session.add(subscription)
    session.commit()
    return {"enabled": True}


@router.post("/api/push/test")
def test_push(session: Session = Depends(get_session), p=Depends(current_device)):
    p = write_lock(session, p)
    sub = session.get(KioskSubscription, p.device_id)
    if not sub or not sub.active:
        raise HTTPException(400, "先に通知を有効にしてください。")
    recent = session.exec(select(KioskDelivery).where(KioskDelivery.device_id == p.device_id, KioskDelivery.change_id == None,
                                                    KioskDelivery.created_at > utc_now() - timedelta(seconds=30))).first()
    if recent:
        raise HTTPException(429, "テスト通知は30秒あけてください。")
    session.add(KioskDelivery(device_id=p.device_id, event_key="test:" + uuid4().hex, expires_at=utc_now()+timedelta(minutes=10)))
    session.commit()
    return {"queued": True}


@router.post("/api/push/disable")
def disable_push(session: Session = Depends(get_session), p=Depends(current_device)):
    p = write_lock(session, p)
    sub = session.get(KioskSubscription, p.device_id)
    if sub:
        sub.active = False
        session.add(sub)
    session.commit()
    return {"enabled": False}


@admin_router.get("/")
def admin_page(request: Request):
    return shell(request, admin=True)


@admin_router.get("/api")
def admin_state(session: Session = Depends(get_session)):
    accounts = {a.id: a for a in session.exec(select(KioskAccount)).all()}
    classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
    by_class = {a.classroom_id: a for a in accounts.values()}
    subscriptions = {s.device_id for s in session.exec(select(KioskSubscription).where(KioskSubscription.active == True)).all()}
    devices = []
    for d in session.exec(select(KioskDevice).order_by(KioskDevice.id)).all():
        a = accounts.get(d.account_id)
        if not a:
            continue
        devices.append({"id": d.id, "name": d.name, "classroom_id": a.classroom_id,
                        "active": d.active, "available": d.active and a.active,
                        "push_enabled": d.active and a.active and d.id in subscriptions})
    pending = session.exec(select(KioskEnrollment).where(KioskEnrollment.used_at == None,
                           KioskEnrollment.expires_at > utc_now()-timedelta(days=1))
                           .order_by(KioskEnrollment.id.desc())).all()
    return {"classrooms": [{"id": c.id, "name": c.name,
                            "enabled": c.id not in by_class or by_class[c.id].active} for c in classrooms],
            "devices": devices, "enrollments": [enrollment_state(e, accounts[e.account_id]) for e in pending if e.account_id in accounts],
            "time": utc_now().isoformat()}


def enrollment_state(enrollment, account):
    return {"id": enrollment.id, "classroom_id": account.classroom_id, "name": enrollment.name,
            "expires_at": ensure_utc(enrollment.expires_at).isoformat(),
            "status": "used" if enrollment.used_at else "expired" if ensure_utc(enrollment.expires_at) <= utc_now() else "pending"}


@admin_router.get("/enrollments/{enrollment_id}")
def enrollment_status(enrollment_id: int, session: Session = Depends(get_session)):
    enrollment = session.get(KioskEnrollment, enrollment_id)
    account = session.get(KioskAccount, enrollment.account_id) if enrollment else None
    if not enrollment or not account:
        raise HTTPException(404, "登録コードが見つかりません。")
    return {**enrollment_state(enrollment, account), "time": utc_now().isoformat()}


@admin_router.post("/enrollments")
def issue(data: Registration, request: Request, session: Session = Depends(get_session), user=Depends(get_current_staff_user)):
    write_lock(session)
    if not session.get(Classroom, data.classroom_id) or not data.name.strip():
        raise HTTPException(422, "クラスと端末名を指定してください。")
    account = session.exec(select(KioskAccount).where(KioskAccount.classroom_id == data.classroom_id)).first()
    if not account:
        account = KioskAccount(classroom_id=data.classroom_id)
        session.add(account)
        session.flush()
    if not account.active:
        raise HTTPException(409, "このクラスアカウントは停止されています。")
    code = secrets.token_hex(6).upper()
    expires = utc_now()+timedelta(minutes=10)
    enrollment = KioskEnrollment(account_id=account.id, name=data.name.strip(), code_hash=digest(code), created_by=user.name, expires_at=expires)
    session.add(enrollment)
    session.add(KioskAudit(account_id=account.id, actor_name=user.name, kind="enrollment_issued", detail={"device_name": data.name.strip()}))
    session.commit()
    import qrcode
    origin = os.getenv("HOIKUICT_CLASS_KIOSK_ORIGIN", "").rstrip("/")
    qr = None
    if origin:
        buffer = BytesIO()
        qrcode.make(origin + "/class-kiosk/#enroll=" + code).save(buffer, format="PNG")
        qr = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    return {**enrollment_state(enrollment, account), "code": code, "expires": service.format_jst_datetime(expires), "qr": qr, "time": utc_now().isoformat()}


@admin_router.post("/devices/{device_id}/revoke")
def revoke(device_id: int, session: Session = Depends(get_session), user=Depends(get_current_staff_user)):
    write_lock(session)
    device = session.get(KioskDevice, device_id)
    if not device:
        raise HTTPException(404)
    if device.active:
        device.active = False
        session.add(device)
        session.add(KioskAudit(account_id=device.account_id, device_id=device_id, actor_name=user.name, kind="device_revoked", detail={}))
    subscription = session.get(KioskSubscription, device_id)
    if subscription:
        subscription.active = False
        session.add(subscription)
    for delivery in session.exec(select(KioskDelivery).where(KioskDelivery.device_id == device_id, KioskDelivery.state == "queued")).all():
        delivery.state = "cancelled"
        session.add(delivery)
    session.commit()
    return {"revoked": True}


class KioskResponseHeaders:
    """Never cache authenticated kiosk responses, including errors."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        protected = scope.get("type") == "http" and scope.get("path", "").startswith(("/class-kiosk", "/settings/class-kiosk"))
        async def send_headers(message):
            if protected and message["type"] == "http.response.start":
                message["headers"] = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"] + [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
            await send(message)
        await self.app(scope, receive, send_headers)
