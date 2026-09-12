"""Audited cancellation of a mistaken punch, with protected billing records."""

import hashlib

from sqlalchemy import delete, update
from sqlmodel import Session, select

from attendance_checks_service import sync_attendance_alarm
from models import (
    AttendanceCorrection,
    AttendanceRecord,
    ExtendedCareCharge,
    ExtendedCareChargeStatus,
)
from time_utils import utc_now


def correction_revision(record):
    return hashlib.sha256(
        repr(
            (record.id, record.updated_at, record.check_in_at, record.check_out_at)
        ).encode()
    ).hexdigest()


def cancel_punch(
    session: Session, record: AttendanceRecord, *, operation, reason, revision, actor
):
    if operation not in {"check_out", "all"}:
        raise ValueError("取り消す打刻を選択してください。")
    reason = reason.strip()
    if not reason or len(reason) > 500:
        raise ValueError("取消理由を500文字以内で入力してください。")
    if revision != correction_revision(record):
        raise ValueError("記録が更新されました。画面を開き直して確認してください。")
    if not record.check_in_at or (operation == "check_out" and not record.check_out_at):
        raise ValueError("取り消せる打刻がありません。")
    charge = session.exec(
        select(ExtendedCareCharge).where(
            ExtendedCareCharge.attendance_record_id == record.id
        )
    ).first()
    if charge and (
        charge.billing_charge_line_id is not None
        or charge.status != ExtendedCareChargeStatus.draft
    ):
        raise ValueError(
            "確定・調整・対象外設定または請求転送された料金があります。料金の設定を解除するか、請求を訂正してから操作してください。"
        )
    history = AttendanceCorrection(
        attendance_record_id=record.id,
        operation=operation,
        reason=reason,
        previous_values=record.model_dump(mode="json"),
        previous_charge=charge.model_dump(mode="json") if charge else None,
        changed_by_user_id=actor.user_id,
        changed_by_name=actor.name,
    )
    values = {"check_out_at": None, "updated_at": utc_now()}
    if operation == "all":
        values.update(
            check_in_at=None,
            planned_pickup_time=None,
            pickup_person=None,
            snack_required=False,
        )
    changed = session.execute(
        update(AttendanceRecord)
        .where(
            AttendanceRecord.id == record.id,
            AttendanceRecord.updated_at == record.updated_at,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise ValueError("別の操作で更新されました。画面を開き直してください。")
    if charge:
        removed = session.execute(
            delete(ExtendedCareCharge)
            .where(
                ExtendedCareCharge.id == charge.id,
                ExtendedCareCharge.status == ExtendedCareChargeStatus.draft,
                ExtendedCareCharge.billing_charge_line_id.is_(None),
                ExtendedCareCharge.updated_at == charge.updated_at,
            )
            .execution_options(synchronize_session=False)
        )
        if removed.rowcount != 1:
            session.rollback()
            raise ValueError("料金が更新されました。画面を開き直してください。")
    session.add(history)
    session.flush()
    session.refresh(record)
    sync_attendance_alarm(
        session,
        child_id=record.child_id,
        target_date=record.attendance_date,
        record=record,
    )
    session.commit()
