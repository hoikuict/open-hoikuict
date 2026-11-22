import base64
import hashlib
import hmac
import json
import os
from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlmodel import select
from attendance_checks_service import sync_attendance_alarm, alarm_reason_labels
from family_emergency import load_orders
from home_care_details import care_display_items, meal_dates
from models import (Child, ChildStatus, Classroom, AttendanceRecord, AttendancePickupHistory,
                    AttendanceVerification, AttendanceVerificationHistory, AttendanceVerificationStatus,
                    DailyContactEntry, AttendanceAlarmState, Message, MessageAttachment)
from parent_contact_fields import contact_field_enabled
from time_utils import local_today, utc_now, format_jst_datetime, format_local_datetime, ensure_utc
from .models import KioskAccount, KioskOperation, KioskAudit, KioskChange, KioskMessageOwner
from .security import Principal, write_lock


LABELS = {"present": "出席", "private_absent": "私用休み", "sick_absent": "病欠", "unknown": "不明"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def audit(session, p, kind, detail):
    session.add(KioskAudit(account_id=p.account_id, device_id=p.device_id, actor_name=p.name, kind=kind, detail=detail))


def operation(session, p, request_id, kind, content):
    try:
        request_id = str(UUID(request_id))
    except (ValueError, TypeError):
        raise HTTPException(422, "送信番号が不正です。")
    previous = session.exec(select(KioskOperation).where(KioskOperation.device_id == p.device_id, KioskOperation.request_id == request_id)).first()
    stamp = fingerprint(content)
    if previous and (previous.kind != kind or previous.digest != stamp):
        raise HTTPException(409, "同じ送信番号で内容が異なります。送信結果を確認してください。")
    return previous, request_id, stamp


def finish_operation(session, p, request_id, kind, stamp, result):
    session.add(KioskOperation(device_id=p.device_id, request_id=request_id, kind=kind, digest=stamp, result=result))
    audit(session, p, kind, {"request_id": request_id, **result})
    session.commit()
    return result


def roster(session, p, day=None):
    day = day or local_today()
    children = session.exec(select(Child).where(Child.classroom_id == p.classroom_id, Child.status == ChildStatus.enrolled).order_by(Child.last_name_kana, Child.first_name_kana, Child.id)).all()
    rows = []
    for child in children:
        check = session.exec(select(AttendanceVerification).where(AttendanceVerification.child_id == child.id, AttendanceVerification.target_date == day)).first()
        record = session.exec(select(AttendanceRecord).where(AttendanceRecord.child_id == child.id, AttendanceRecord.attendance_date == day)).first()
        entry = session.exec(select(DailyContactEntry).where(DailyContactEntry.child_id == child.id, DailyContactEntry.target_date == day)).first()
        emergency = load_orders(session, child, day, legacy=not entry or (entry.extra_data or {}).get("submitted_family_id", child.family_id) == child.family_id)
        version = fingerprint([child.id, child.updated_at, check.model_dump() if check else None, record.model_dump() if record else None,
                               entry.model_dump() if entry else None, emergency["base_revision"], emergency["day_revision"]])
        rows.append({"id": child.id, "name": child.full_name, "status": check.status.value if check else "", "version": version,
                     "parent": entry.contact_type.label if entry else "未提出", "in": format_local_datetime(record.check_in_at, "%H:%M") if record else "",
                     "out": format_local_datetime(record.check_out_at, "%H:%M") if record else "",
                     "pickup": record.planned_pickup_time if record else "", "person": record.pickup_person if record else "",
                     "snack": record.snack_required if record else False})
    return rows


def child_in_class(session, p, child_id):
    child = session.get(Child, child_id)
    if not child or child.classroom_id != p.classroom_id or child.status != ChildStatus.enrolled:
        raise HTTPException(404, "園児が見つかりません。")
    return child


def child_detail(session, p, child_id, day=None):
    day = day or local_today()
    child = child_in_class(session, p, child_id)
    entry = session.exec(select(DailyContactEntry).where(DailyContactEntry.child_id == child_id, DailyContactEntry.target_date == day)).first()
    state = load_orders(session, child, day, legacy=not entry or (entry.extra_data or {}).get("submitted_family_id", child.family_id) == child.family_id)
    answer, usual = state["answer"], state["usual"]
    if answer and answer.mode == "withdraw":
        answer = None
    emergency = [["連絡順", ("この日だけ変更" if answer.mode == "change" else "いつもどおり") if answer else "この日は未回答"]]
    for i, item in enumerate((answer or usual).contacts if (answer or usual) else []):
        emergency.append([f"{i+1}番目", f"{item.get('label', '')} ／ {item.get('phone', '')}"])
    if answer:
        emergency.append(["回答", f"{answer.updated_by} ／ {format_jst_datetime(answer.updated_at)}"])
    fields = []
    if entry:
        fields = [["連絡内容", entry.contact_type.label], ["提出者", entry.parent_account.display_name if entry.parent_account else "—"], ["更新", format_jst_datetime(entry.updated_at)]]
        if entry.is_present_contact:
            for key, label, group in [("temperature", "体温", "temperature"), ("sleep_notes", "睡眠メモ", "sleep"),
                                     ("bowel_movement_status", "排便", "stool"), ("mood", "機嫌", "mood"), ("medication", "服薬", "medication"),
                                     ("cough", "咳", "cough"), ("runny_nose", "鼻水", "runny_nose"), ("condition_note", "体調メモ", "condition")]:
                fields.append([label, (getattr(entry, key) or "未入力") if contact_field_enabled(entry, group) else "対象外"])
            fields += care_display_items(entry.extra_data)
            extra = entry.extra_data or {}
            for meal, label in meal_dates(day):
                fields += [[label + "・" + title, (extra.get(meal + suffix) or "未入力") if contact_field_enabled(entry, meal) else "対象外"] for suffix, title in [("_appetite", "食欲"), ("_contents", "食べたもの")]]
            if entry.breakfast_status:
                fields.append(["以前の記録（朝食・食欲）", entry.breakfast_status])
            fields += [["園への連絡事項", entry.contact_note or "未入力"], ["状態", entry.status.label]]
        else:
            fields += [["欠席理由", entry.absence_reason_label], ["備考", entry.absence_note or "未入力"]]
            if entry.contact_type.value == "absent_sick":
                fields += [[label, getattr(entry, key) or "未入力"] for key, label in [("absence_temperature", "現在の体温"), ("absence_symptoms", "症状"), ("absence_diagnosis", "医師から伝えられた診断名")]]
    history = session.exec(select(AttendanceVerificationHistory).where(AttendanceVerificationHistory.child_id == child_id, AttendanceVerificationHistory.target_date == day).order_by(AttendanceVerificationHistory.id.desc()).limit(30)).all()
    alarm = session.exec(select(AttendanceAlarmState).where(AttendanceAlarmState.child_id == child_id, AttendanceAlarmState.target_date == day)).first()
    current_row = next(r for r in roster(session, p, day) if r["id"] == child_id)
    return {"id": child_id, "name": child.full_name, "day": day.isoformat(), "row": current_row, "fields": fields, "emergency": emergency,
            "alarm": alarm_reason_labels(alarm.reasons) if alarm and alarm.is_active else [],
            "history": [{"status": h.status.value, "previous": h.previous_status, "reason": h.reason, "actor": h.updated_by_name, "time": format_jst_datetime(h.created_at)} for h in history]}


def signing_key():
    key = os.getenv("HOIKUICT_SECRET_KEY", "")
    if len(key) < 32:
        raise HTTPException(503, "署名鍵の設定が必要です。")
    return key.encode()


def review_attendance(session, p, data):
    current = roster(session, p)
    if data["day"] != local_today().isoformat():
        raise HTTPException(409, "日付が変わりました。今日の出欠を開き直してください。")
    submitted = data["rows"]
    if len(submitted) != len(current) or {r["id"] for r in submitted} != {r["id"] for r in current}:
        raise HTTPException(409, "クラス名簿が更新されました。出欠一覧を開き直してください。")
    index = {r["id"]: r for r in submitted}
    errors = {}
    for row in current:
        value = index[row["id"]]
        if value["version"] != row["version"]:
            errors[row["id"]] = "出欠または連絡が更新されました。最新の内容を確認してください。"
        elif value["status"] not in LABELS:
            errors[row["id"]] = "出欠を選んでください。"
        elif row["status"] and value["status"] != row["status"] and not value["reason"].strip():
            errors[row["id"]] = "訂正理由を入力してください。"
    if errors:
        raise HTTPException(409, {"message": "入力内容を確認してください。", "errors": errors, "rows": current})
    changed = sum(index[r["id"]]["status"] != r["status"] for r in current)
    if not changed:
        raise HTTPException(400, "変更はありません。")
    payload = {"device": p.device_id, "day": data["day"], "rows": submitted, "expires": (utc_now() + timedelta(minutes=10)).timestamp()}
    body = base64.urlsafe_b64encode(canonical(payload).encode()).decode()
    token = body + "." + hmac.new(signing_key(), body.encode(), hashlib.sha256).hexdigest()
    return {"token": token, "changed": changed, "before": current, "rows": submitted}


def send_attendance(session, p, request_id, token):
    p = write_lock(session, p)
    previous, request_id, stamp = operation(session, p, request_id, "attendance", token)
    if previous:
        return previous.result
    try:
        body, signature = token.split(".")
        if not hmac.compare_digest(signature, hmac.new(signing_key(), body.encode(), hashlib.sha256).hexdigest()):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(body))
        if data["device"] != p.device_id or data["expires"] < utc_now().timestamp():
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(409, "確認画面の有効期限が切れました。もう一度確認してください。")
    review = review_attendance(session, p, data)
    current = {r["id"]: r for r in review["before"]}
    day = local_today()
    changes = []
    for value in data["rows"]:
        old = current[value["id"]]
        if old["status"] == value["status"]:
            continue
        row = session.exec(select(AttendanceVerification).where(AttendanceVerification.child_id == value["id"], AttendanceVerification.target_date == day)).first()
        if not row:
            row = AttendanceVerification(child_id=value["id"], target_date=day)
        row.status = AttendanceVerificationStatus(value["status"])
        row.updated_by_name, row.updated_at = p.name, utc_now()
        session.add(row)
        session.add(AttendanceVerificationHistory(child_id=row.child_id, target_date=day, status=row.status, previous_status=old["status"] or None,
                                                  reason=value["reason"].strip() or "初回確認", updated_by_name=p.name))
        session.flush()
        sync_attendance_alarm(session, child_id=row.child_id, target_date=day, verification=row)
        changes.append(row.child_id)
    return finish_operation(session, p, request_id, "attendance", stamp, {"saved": len(changes), "child_ids": changes, "actor": p.name, "day": str(day), "time": format_jst_datetime(utc_now())})


def sync_changes(session, p):
    from .push import queue_change
    day = local_today()
    children = session.exec(select(Child).where(Child.classroom_id == p.classroom_id, Child.status == ChildStatus.enrolled)).all()
    for child in children:
        sources = []
        entry = session.exec(select(DailyContactEntry).where(DailyContactEntry.child_id == child.id, DailyContactEntry.target_date == day)).first()
        if entry:
            sources.append(("contact", fingerprint(entry.model_dump()), entry.updated_at,
                            {"title": "家庭からの連絡", "before": "", "after": entry.contact_type.label, "detail": entry.contact_note or entry.absence_note or "連絡の全文を確認してください。"}))
        emergency = load_orders(session, child, day, legacy=not entry or (entry.extra_data or {}).get("submitted_family_id", child.family_id) == child.family_id)
        answer = emergency["answer"]
        if answer:
            sources.append(("emergency", fingerprint([emergency["base_revision"], emergency["day_revision"], answer.updated_at]), answer.updated_at,
                            {"title": "緊急連絡先の回答", "before": "", "after": {"change": "この日の連絡順に変更があります", "withdraw": "この日の回答が取り消されました"}.get(answer.mode, "いつもどおり"), "detail": "連絡全文で電話してほしい順番を確認してください。"}))
        record = session.exec(select(AttendanceRecord).where(AttendanceRecord.child_id == child.id, AttendanceRecord.attendance_date == day)).first()
        if record:
            latest = session.exec(select(AttendancePickupHistory).where(AttendancePickupHistory.attendance_record_id == record.id).order_by(AttendancePickupHistory.id.desc())).first()
            if latest and latest.source == "parent":
                sources.append(("pickup", str(latest.id), latest.changed_at,
                                {"title": "お迎えの変更", "before": f"{latest.previous_time or '未定'} ／ {latest.previous_person or '未定'} ／ 補食{'あり' if latest.previous_snack_required else 'なし'}",
                                 "after": f"{latest.new_time} ／ {latest.new_person} ／ 補食{'あり' if latest.new_snack_required else 'なし'}", "detail": "保護者から変更が届きました。"}))
        for kind, version, timestamp, payload in sources:
            change = session.exec(select(KioskChange).where(KioskChange.account_id == p.account_id, KioskChange.child_id == child.id, KioskChange.day == day, KioskChange.kind == kind)).first()
            if change and change.version == version:
                continue
            if not change:
                change = KioskChange(account_id=p.account_id, child_id=child.id, day=day, kind=kind, version=version)
            change.version, change.acknowledged, change.updated_at = version, False, timestamp
            change.history = change.history + [{**payload, "version": version, "time": format_jst_datetime(timestamp)}]
            session.add(change)
            session.flush()
            queue_change(session, change, timestamp)


def sync_all_changes(session):
    """Track every classroom, including those without a registered kiosk device.

    Must run inside the existing SQLite write lock. Creating the class identity
    does not issue an enrollment code/device token or reactivate stopped accounts.
    """
    accounts = {a.classroom_id: a for a in session.exec(select(KioskAccount)).all()}
    for classroom in session.exec(select(Classroom)).all():
        account = accounts.get(classroom.id)
        if account is None:
            account = KioskAccount(classroom_id=classroom.id)
            session.add(account)
            session.flush()
        sync_changes(session, Principal(0, account.id, classroom.id, classroom.name, "history", ""))


def changes_list(session, p, *, today_only=False, all_classes=False):
    query = (select(KioskChange, Child, Classroom)
             .join(Child, Child.id == KioskChange.child_id)
             .join(KioskAccount, KioskAccount.id == KioskChange.account_id)
             .join(Classroom, Classroom.id == KioskAccount.classroom_id)
             .where(Child.classroom_id == Classroom.id, Child.status == ChildStatus.enrolled))
    if not all_classes:
        query = query.where(KioskChange.account_id == p.account_id, Classroom.id == p.classroom_id)
    query = query.where(KioskChange.day == local_today() if today_only else
                        (KioskChange.day == local_today()) | (KioskChange.acknowledged == False))
    rows = session.exec(query.order_by(KioskChange.updated_at.desc(), KioskChange.id.desc())).all()
    # Audit timestamps are retained separately; legacy fixture confirmations may
    # have no audit. Never invent a confirmation time in that case.
    acknowledged_at = {}
    confirmed = {r.id: r.version for r, _, _ in rows if r.acknowledged}
    if confirmed:
        audits = session.exec(select(KioskAudit).where(
            KioskAudit.kind == "acknowledgement",
            KioskAudit.detail["change_id"].as_integer().in_(confirmed),
        ).order_by(KioskAudit.id.desc())).all()
        for item in audits:
            change_id = item.detail.get("change_id")
            if (change_id not in acknowledged_at and item.detail.get("acknowledged")
                    and item.detail.get("version") == confirmed.get(change_id)):
                acknowledged_at[change_id] = format_jst_datetime(item.created_at)
    return [{"id": r.id, "child_id": r.child_id, "name": child.full_name, "day": str(r.day), "kind": r.kind,
             "class_name": classroom.name, "can_ack": r.account_id == p.account_id,
             "version": r.version, "ack": r.acknowledged, "ack_time": acknowledged_at.get(r.id), "history": r.history}
            for r, child, classroom in rows]


def message_json(session, p, message):
    owner = session.get(KioskMessageOwner, message.id)
    files = [] if message.is_deleted else session.exec(select(MessageAttachment).where(MessageAttachment.message_id == message.id)).all()
    return {"id": message.id, "parent_id": message.parent_message_id, "author": message.author_name, "body": message.display_body,
            "time": format_jst_datetime(message.created_at), "deleted": message.is_deleted, "own": bool(owner and owner.account_id == p.account_id),
            "attachments": [{"id": f.id, "name": f.original_filename} for f in files],
            "replies": len(session.exec(select(Message.id).where(Message.parent_message_id == message.id)).all()) if not message.parent_message_id else 0}


def timeline(session, p, before=None):
    query = select(Message).where(Message.parent_message_id == None)
    if before:
        cursor = session.get(Message, before)
        if not cursor or cursor.parent_message_id is not None:
            return []
        query = query.where(or_(Message.created_at < cursor.created_at,
                              and_(Message.created_at == cursor.created_at, Message.id < cursor.id)))
    messages = session.exec(query.order_by(Message.created_at.desc(), Message.id.desc()).limit(30)).all()
    return [message_json(session, p, m) for m in messages]


def home_timeline(session, p):
    """A bounded preview; the full timeline keeps every original post."""
    now = utc_now()
    conditions = (Message.parent_message_id == None,
                  Message.created_at >= now - timedelta(hours=3), Message.created_at <= now)
    total = session.exec(select(func.count()).select_from(Message).where(*conditions)).one()
    messages = session.exec(select(Message).where(*conditions)
                            .order_by(Message.created_at.desc(), Message.id.desc()).limit(5)).all()
    return {"messages": [message_json(session, p, m) for m in messages], "total": total}
