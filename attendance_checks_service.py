from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlmodel import Session, select

from models import (
    AttendanceAlarmHistory,
    AttendanceAlarmState,
    AttendanceRecord,
    AttendanceVerification,
    AttendanceVerificationStatus,
    DailyContactEntry,
    ParentContactType,
)
from time_utils import utc_now

ALARM_REASON_LABELS = {
    "punched_but_not_present": "打刻ありだが目視では来ていない",
    "absence_contact_but_present": "欠席連絡だが実際には来ている",
    "no_contact_and_not_present": "連絡がなく実際にも来ていない",
}


def parent_contact_label(entry: Optional[DailyContactEntry]) -> str:
    if not entry:
        return "なし"
    return entry.contact_type.label


def parent_contact_reason_label(entry: Optional[DailyContactEntry]) -> str:
    if not entry:
        return ""
    return entry.absence_reason_label


def verification_label(verification: Optional[AttendanceVerification]) -> str:
    if not verification:
        return "未確認"
    return verification.status.label


def alarm_reason_labels(reasons: Optional[list[str]]) -> list[str]:
    return [ALARM_REASON_LABELS.get(reason, reason) for reason in (reasons or [])]


def build_alarm_reasons(
    record: Optional[AttendanceRecord],
    entry: Optional[DailyContactEntry],
    verification: Optional[AttendanceVerification],
) -> list[str]:
    if verification is None or verification.status == AttendanceVerificationStatus.unknown:
        return []

    reasons: list[str] = []
    visually_present = verification.status == AttendanceVerificationStatus.present
    visually_absent = verification.status in {
        AttendanceVerificationStatus.private_absent,
        AttendanceVerificationStatus.sick_absent,
    }

    if record and record.check_in_at is not None and visually_absent:
        reasons.append("punched_but_not_present")

    if (
        entry
        and entry.contact_type in {ParentContactType.absent_private, ParentContactType.absent_sick}
        and visually_present
    ):
        reasons.append("absence_contact_but_present")

    if entry is None and visually_absent:
        reasons.append("no_contact_and_not_present")

    return reasons


def sync_attendance_alarm(
    session: Session,
    *,
    child_id: int,
    target_date: date,
    entry: Optional[DailyContactEntry] = None,
    record: Optional[AttendanceRecord] = None,
    verification: Optional[AttendanceVerification] = None,
    now: Optional[datetime] = None,
) -> AttendanceAlarmState:
    timestamp = now or utc_now()
    entry = entry or session.exec(
        select(DailyContactEntry).where(
            DailyContactEntry.child_id == child_id,
            DailyContactEntry.target_date == target_date,
        )
    ).first()
    record = record or session.exec(
        select(AttendanceRecord).where(
            AttendanceRecord.child_id == child_id,
            AttendanceRecord.attendance_date == target_date,
        )
    ).first()
    verification = verification or session.exec(
        select(AttendanceVerification).where(
            AttendanceVerification.child_id == child_id,
            AttendanceVerification.target_date == target_date,
        )
    ).first()

    reasons = build_alarm_reasons(record, entry, verification)
    next_is_active = bool(reasons)
    reasons_payload = reasons or None

    state = session.exec(
        select(AttendanceAlarmState).where(
            AttendanceAlarmState.child_id == child_id,
            AttendanceAlarmState.target_date == target_date,
        )
    ).first()

    should_log = False
    if not state:
        state = AttendanceAlarmState(
            child_id=child_id,
            target_date=target_date,
            is_active=next_is_active,
            reasons=reasons_payload,
            evaluated_at=timestamp,
            updated_at=timestamp,
        )
        should_log = True
    else:
        if state.is_active != next_is_active or (state.reasons or []) != (reasons_payload or []):
            should_log = True
        state.is_active = next_is_active
        state.reasons = reasons_payload
        state.evaluated_at = timestamp
        state.updated_at = timestamp

    session.add(state)
    if should_log:
        session.add(
            AttendanceAlarmHistory(
                child_id=child_id,
                target_date=target_date,
                is_active=next_is_active,
                reasons=reasons_payload,
                evaluated_at=timestamp,
                created_at=timestamp,
            )
        )
    return state
