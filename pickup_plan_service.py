"""Pickup plans share a record but never create an actual arrival/departure."""
import hashlib
import re

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from models import AttendancePickupHistory, AttendanceRecord
from time_utils import ensure_utc, utc_now


def load_pickup_record(session: Session, child_id: int, day):
    return session.exec(select(AttendanceRecord).where(
        AttendanceRecord.child_id == child_id, AttendanceRecord.attendance_date == day)).first()


def pickup_revision(record: AttendanceRecord | None) -> str:
    if record is None:
        return "new"
    values = (record.id, ensure_utc(record.updated_at).isoformat(), record.planned_pickup_time,
              record.pickup_person, record.snack_required, str(record.check_out_at))
    return hashlib.sha256(repr(values).encode()).hexdigest()


def save_pickup_plan(session: Session, *, child_id: int, day, revision: str, planned_pickup_time: str,
                     pickup_person: str, actor_name: str, source: str, actor_user_id=None,
                     parent_account_id=None, snack_required: bool | None = None):
    record = load_pickup_record(session, child_id, day)
    if record and record.check_out_at:
        raise HTTPException(400, "降園済みのお迎え予定は変更できません")
    if revision != pickup_revision(record):
        raise HTTPException(409, "別の操作で更新されています。画面を開き直して最新の内容を確認してください")
    time, person = planned_pickup_time.strip(), pickup_person.strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time):
        raise HTTPException(400, "お迎え予定時刻を時・分で入力してください")
    if not person or len(person) > 100 or any(ord(c) < 32 for c in person):
        raise HTTPException(400, "お迎え予定者を100文字以内で入力してください")
    old_time = record.planned_pickup_time if record else None
    old_person = record.pickup_person if record else None
    old_snack = bool(record and record.snack_required)
    snack = old_snack if snack_required is None else snack_required
    if record and (old_time, old_person, old_snack) == (time, person, snack):
        return record
    now = utc_now()
    values = dict(planned_pickup_time=time, pickup_person=person, snack_required=snack, updated_at=now)
    if record is None:
        record = AttendanceRecord(child_id=child_id, attendance_date=day, **values)
        session.add(record)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "別の操作で登録されています。画面を開き直してください") from exc
    else:
        result = session.execute(update(AttendanceRecord).where(
            AttendanceRecord.id == record.id, AttendanceRecord.updated_at == record.updated_at,
            AttendanceRecord.check_out_at.is_(None),
        ).values(**values).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "別の操作で更新されています。画面を開き直してください")
        session.refresh(record)
    session.add(AttendancePickupHistory(attendance_record_id=record.id, previous_time=old_time,
        previous_person=old_person, previous_snack_required=old_snack, new_time=time, new_person=person,
        new_snack_required=snack, changed_by_name=actor_name, source=source,
        changed_by_user_id=actor_user_id, changed_by_parent_account_id=parent_account_id, changed_at=now))
    return record
