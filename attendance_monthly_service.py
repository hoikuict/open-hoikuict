"""Monthly attendance correction; empty-only admin batches share the audited save path."""
from calendar import monthrange
from datetime import date, datetime, time, timedelta
import hashlib
import json
import re
from uuid import uuid4

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from attendance_checks_service import sync_attendance_alarm
from auth import require_admin, require_can_edit
from extended_care_fee_service import charge_status_label, recalculate_attendance_charge
from models import (
    AttendanceCorrection, AttendanceRecord, AttendanceVerification,
    AttendanceVerificationStatus, Child, ChildStatus, DailyContactEntry,
    ExtendedCareCharge, ExtendedCareChargeStatus,
)
from time_utils import format_jst_datetime, local_naive_now, local_today, utc_now


class AttendanceEditError(ValueError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def month_days(value):
    value = value or local_today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise AttendanceEditError("対象月を YYYY-MM で指定してください。")
    try:
        year, month = map(int, value.split("-"))
        first = date(year, month, 1)
        last = date(year, month, monthrange(year, month)[1])
    except ValueError as exc:
        raise AttendanceEditError("対象月が正しくありません。") from exc
    return first, last


def on_roll(child, day):
    if day < child.enrollment_date:
        return False
    if child.withdrawal_date:
        return day <= child.withdrawal_date
    return child.status == ChildStatus.enrolled


def fee_locked(charge):
    return bool(charge and (charge.billing_charge_line_id is not None
                           or charge.status != ExtendedCareChargeStatus.draft))


def revision(child, record, verification, contact, charge):
    # Protect the evidence and billing state shown with the time fields as well.
    payload = [child.id, child.enrollment_date, child.withdrawal_date, child.status]
    for item in (record, verification, contact, charge):
        payload.append(item.model_dump(mode="json") if item else None)
    return hashlib.sha256(json.dumps(payload, default=str, sort_keys=True).encode()).hexdigest()


def day_state(session, child, day):
    record = session.exec(select(AttendanceRecord).where(
        AttendanceRecord.child_id == child.id, AttendanceRecord.attendance_date == day)).first()
    verification = session.exec(select(AttendanceVerification).where(
        AttendanceVerification.child_id == child.id, AttendanceVerification.target_date == day)).first()
    contact = session.exec(select(DailyContactEntry).where(
        DailyContactEntry.child_id == child.id, DailyContactEntry.target_date == day)).first()
    charge = session.exec(select(ExtendedCareCharge).where(
        ExtendedCareCharge.attendance_record_id == record.id)).first() if record else None
    return record, verification, contact, charge


def correction_label(operation):
    return {"time_edit": "時刻の補記・修正", "missing_fill": "管理者の一括補完",
            "check_out": "降園打刻の取消", "all": "登園・降園とお迎え予定の取消"}.get(operation, operation)


def monthly_rows(session, child, month):
    first, last = month_days(month)
    records = {r.attendance_date: r for r in session.exec(select(AttendanceRecord).where(
        AttendanceRecord.child_id == child.id, AttendanceRecord.attendance_date >= first,
        AttendanceRecord.attendance_date <= last)).all()}
    verifications = {r.target_date: r for r in session.exec(select(AttendanceVerification).where(
        AttendanceVerification.child_id == child.id, AttendanceVerification.target_date >= first,
        AttendanceVerification.target_date <= last)).all()}
    contacts = {r.target_date: r for r in session.exec(select(DailyContactEntry).where(
        DailyContactEntry.child_id == child.id, DailyContactEntry.target_date >= first,
        DailyContactEntry.target_date <= last)).all()}
    ids = [r.id for r in records.values()]
    charges, histories = {}, {}
    if ids:
        charges = {r.attendance_record_id: r for r in session.exec(select(ExtendedCareCharge).where(
            ExtendedCareCharge.attendance_record_id.in_(ids))).all()}
        for item in session.exec(select(AttendanceCorrection).where(
                AttendanceCorrection.attendance_record_id.in_(ids)).order_by(AttendanceCorrection.id.desc())).all():
            histories.setdefault(item.attendance_record_id, []).append(item)
    result = []
    for index in range(last.day):
        day = first + timedelta(days=index)
        record, verification, contact = records.get(day), verifications.get(day), contacts.get(day)
        charge = charges.get(record.id) if record else None
        arrival, departure = (record.check_in_at, record.check_out_at) if record else (None, None)
        present = bool(verification and verification.status == AttendanceVerificationStatus.present)
        absent = bool((verification and verification.status.is_absent) or (contact and contact.is_absent_contact))
        missing = bool((present or arrival or departure) and (not arrival or not departure))
        unknown = bool(not (arrival or departure or present or absent) and on_roll(child, day))
        locked = fee_locked(charge)
        allowed = on_roll(child, day) and day <= local_today()
        history = []
        for item in histories.get(record.id, []) if record else []:
            meta = item.previous_values.get("_time_correction", {})
            history.append({"label": correction_label(item.operation), "actor": item.changed_by_name,
                            "at": format_jst_datetime(item.changed_at), "reason": item.reason,
                            "before": {key: item.previous_values.get(key) for key in ("check_in_at", "check_out_at")},
                            "after": meta.get("after"), "batch_id": meta.get("batch_id")})
        result.append({
            "date": day.isoformat(), "weekday": "月火水木金土日"[day.weekday()],
            "arrival": arrival.strftime("%H:%M") if arrival else "",
            "departure": departure.strftime("%H:%M") if departure else "",
            "arrival_date": arrival.date().isoformat() if arrival else "",
            "departure_date": departure.date().isoformat() if departure else "",
            "next_day": bool(departure and departure.date() > day),
            "date_mismatch": bool((arrival and arrival.date() != day)
                                  or (departure and departure.date() not in (day, day + timedelta(days=1)))),
            "visual": verification.status.label if verification else "未確認",
            "contact": contact.contact_type.label if contact else "連絡なし",
            "missing": missing, "unknown": unknown, "absent": absent, "locked": locked,
            "allowed": allowed, "future": day > local_today(),
            "bulk_eligible": allowed and not locked and not absent and missing,
            "bulk_optional": allowed and not locked and not absent and unknown,
            "revision": revision(child, record, verification, contact, charge),
            "planned": record.planned_pickup_time or "" if record else "",
            "person": record.pickup_person or "" if record else "",
            "actual": record.actual_pickup_person or "" if record else "",
            "snack": ("必要" if record.snack_required else "不要") if record and record.pickup_snack_confirmed else "未確認",
            "fee": charge.final_amount if charge else None,
            "fee_minutes": charge.extended_minutes if charge else None,
            "fee_status": charge_status_label(charge) if charge else ("未計算" if departure else "—"),
            "history": history, "record_id": record.id if record else None,
        })
    return result


def _input_time(value):
    if value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
        raise AttendanceEditError("時刻は HH:MM で入力してください。")
    return time.fromisoformat(value)


def save_times(session: Session, *, child_id, month, items, reason, actor, bulk=False):
    """Validate the entire request before changing any row; commit all or none."""
    require_admin(actor) if bulk else require_can_edit(actor)
    if session.get_bind().dialect.name == "sqlite":
        connection = session.connection()
        if not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    first, last = month_days(month)
    reason = reason.strip()
    if not reason or len(reason) > 500:
        raise AttendanceEditError("補記・修正理由を500文字以内で入力してください。")
    if not isinstance(items, list) or not 1 <= len(items) <= (31 if bulk else 1):
        raise AttendanceEditError("補記する日を選択してください（一括は最大31日）。")
    child = session.get(Child, child_id)
    if child is None:
        raise AttendanceEditError("園児が見つかりません。", 404)
    changes, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise AttendanceEditError("入力内容が正しくありません。")
        try:
            day = date.fromisoformat(item.get("date", ""))
        except (ValueError, TypeError) as exc:
            raise AttendanceEditError("対象日が正しくありません。") from exc
        if day in seen or not first <= day <= last:
            raise AttendanceEditError("対象月外の日付、または同じ日の重複があります。")
        seen.add(day)
        if day > local_today() or not on_roll(child, day):
            raise AttendanceEditError(f"{day}: 未来日・在籍期間外の日は補記できません。")
        record, verification, contact, charge = day_state(session, child, day)
        if item.get("revision") != revision(child, record, verification, contact, charge):
            raise AttendanceEditError(f"{day}: 記録が更新されています。保存せず閉じ、最新の一覧から確認してください。", 409)
        if fee_locked(charge):
            raise AttendanceEditError(f"{day}: 確定・調整・対象外・請求転送済みの料金があり、時刻を変更できません。", 409)
        if bulk and ((verification and verification.status.is_absent) or (contact and contact.is_absent_contact)):
            raise AttendanceEditError(f"{day}: 欠席の記録がある日は一括補完できません。出欠を確認してください。")
        old_in, old_out = (record.check_in_at, record.check_out_at) if record else (None, None)
        incoming, outgoing = _input_time(item.get("arrival", "")), _input_time(item.get("departure", ""))
        offset = item.get("next_day", False)
        if type(offset) is not bool:
            raise AttendanceEditError("降園日の指定が正しくありません。")
        new_in = datetime.combine(day, incoming) if incoming else None
        new_out = datetime.combine(day + timedelta(days=int(offset)), outgoing) if outgoing else None
        # An unchanged HH:MM field must retain its existing seconds and date.
        # Date repair is explicit, and bulk mode can never alter an existing punch.
        repair_dates = item.get("repair_dates", False) is True and not bulk
        if old_in and incoming and old_in.strftime("%H:%M") == item.get("arrival") and not repair_dates:
            new_in = old_in
        if old_out and outgoing and old_out.strftime("%H:%M") == item.get("departure") and bool(old_out.date() > day) == offset and not repair_dates:
            new_out = old_out
        if bulk and ((old_in and new_in != old_in) or (old_out and new_out != old_out)):
            raise AttendanceEditError(f"{day}: 一括補完で既存の打刻は変更できません。")
        if (old_in and not new_in) or (old_out and not new_out):
            raise AttendanceEditError("登録済み時刻の削除は「打刻の取消・履歴」から行ってください。")
        if new_in is None and new_out is None:
            raise AttendanceEditError(f"{day}: 少なくとも片方の時刻を入力してください。")
        if new_in and new_in.date() != day:
            raise AttendanceEditError(f"{day}: 登園の記録日が対象日と異なります。個別修正で日付も訂正してください。")
        if new_out and (new_out.date() not in (day, day + timedelta(days=1))
                        or (new_out.date() > day and new_out.time() > time(3))):
            raise AttendanceEditError(f"{day}: 降園は対象日から翌日03:00までを指定してください。")
        if new_in and new_out and new_out <= new_in:
            raise AttendanceEditError(f"{day}: 降園時刻は登園時刻より後にしてください。")
        if any(value and value > local_naive_now() for value in (new_in, new_out)):
            raise AttendanceEditError(f"{day}: 未来の時刻は補記できません。")
        if old_in == new_in and old_out == new_out:
            continue
        changes.append((day, record, verification, contact, charge, new_in, new_out))
    if not changes:
        raise AttendanceEditError("変更する時刻がありません。")
    batch_id = str(uuid4()) if bulk else None
    try:
        for day, record, verification, contact, charge, incoming, outgoing in changes:
            before = record.model_dump(mode="json") if record else {"check_in_at": None, "check_out_at": None}
            before_charge = charge.model_dump(mode="json") if charge else None
            timestamp = utc_now()
            if record:
                result = session.execute(update(AttendanceRecord).where(
                    AttendanceRecord.id == record.id, AttendanceRecord.updated_at == record.updated_at
                ).values(check_in_at=incoming, check_out_at=outgoing, updated_at=timestamp)
                  .execution_options(synchronize_session=False))
                if result.rowcount != 1:
                    raise AttendanceEditError("別の職員が記録を更新しました。一覧を開き直してください。", 409)
                session.refresh(record)
            else:
                record = AttendanceRecord(child_id=child_id, attendance_date=day,
                                          check_in_at=incoming, check_out_at=outgoing, updated_at=timestamp)
                session.add(record)
                session.flush()
            # Protect the current charge with the same conditional deletion as cancellation.
            if charge:
                result = session.execute(delete(ExtendedCareCharge).where(
                    ExtendedCareCharge.id == charge.id,
                    ExtendedCareCharge.updated_at == charge.updated_at,
                    ExtendedCareCharge.status == ExtendedCareChargeStatus.draft,
                    ExtendedCareCharge.billing_charge_line_id.is_(None)
                ).execution_options(synchronize_session=False))
                if result.rowcount != 1:
                    raise AttendanceEditError("料金が更新されています。一覧を開き直してください。", 409)
                session.expunge(charge)
            recalculate_attendance_charge(session, record)
            before["_time_correction"] = {
                "after": {"check_in_at": incoming.isoformat() if incoming else None,
                          "check_out_at": outgoing.isoformat() if outgoing else None},
                "batch_id": batch_id, "source": "admin_bulk" if bulk else "staff",
            }
            session.add(AttendanceCorrection(
                attendance_record_id=record.id, operation="missing_fill" if bulk else "time_edit",
                reason=reason, previous_values=before, previous_charge=before_charge,
                changed_by_user_id=actor.user_id, changed_by_name=actor.name, changed_at=timestamp))
            sync_attendance_alarm(session, child_id=child_id, target_date=day,
                                  record=record, verification=verification, entry=contact)
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise AttendanceEditError("同じ記録が別の操作で更新されました。一覧を開き直してください。", 409) from exc
    except Exception:
        session.rollback()
        raise
    return len(changes)
