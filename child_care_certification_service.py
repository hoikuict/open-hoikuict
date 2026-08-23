from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from models import (
    CareNeedReason,
    CareTimeCategory,
    Child,
    ChildCareCertification,
    ChildCareCertificationAuditLog,
    ChildCareNeedReason,
)
from time_utils import local_today, utc_now


def list_certifications(session: Session, child_id: int) -> list[ChildCareCertification]:
    return list(
        session.exec(
            select(ChildCareCertification)
            .options(selectinload(ChildCareCertification.reasons))
            .where(ChildCareCertification.child_id == child_id)
            .order_by(ChildCareCertification.effective_from.desc(), ChildCareCertification.id.desc())
        ).all()
    )


def effective_certification(
    session: Session,
    child_id: int,
    target_date: date,
) -> Optional[ChildCareCertification]:
    items = session.exec(
        select(ChildCareCertification)
        .options(selectinload(ChildCareCertification.reasons))
        .where(
            ChildCareCertification.child_id == child_id,
            ChildCareCertification.is_active == True,  # noqa: E712
            ChildCareCertification.effective_from <= target_date,
        )
        .order_by(ChildCareCertification.effective_from.desc(), ChildCareCertification.id.desc())
    ).all()
    matches = [item for item in items if item.effective_to is None or item.effective_to >= target_date]
    return matches[0] if len(matches) == 1 else None


def validate_certification(
    session: Session,
    *,
    child_id: int,
    care_time_category: CareTimeCategory,
    effective_from: date,
    effective_to: Optional[date],
    guardian_reasons: list[dict[str, object]],
    certification_id: Optional[int] = None,
) -> list[str]:
    errors: list[str] = []
    if effective_to is not None and effective_to < effective_from:
        errors.append("適用終了日は適用開始日以降にしてください。")
    if not isinstance(care_time_category, CareTimeCategory):
        errors.append("保育必要量を選択してください。")
    if not guardian_reasons:
        errors.append("少なくとも1人の保護者について、保育を必要とする事由を選択してください。")

    seen_orders: set[int] = set()
    for row in guardian_reasons:
        guardian_order = int(row.get("guardian_order") or 0)
        if guardian_order <= 0 or guardian_order in seen_orders:
            errors.append("保護者の指定が不正です。")
            continue
        seen_orders.add(guardian_order)
        reason = row.get("reason")
        if not isinstance(reason, CareNeedReason):
            errors.append(f"保護者{guardian_order}の事由を選択してください。")
        if reason == CareNeedReason.other_municipal and not str(row.get("other_reason_detail") or "").strip():
            errors.append(f"保護者{guardian_order}のその他事由を入力してください。")

    if errors:
        return errors

    existing = session.exec(
        select(ChildCareCertification).where(
            ChildCareCertification.child_id == child_id,
            ChildCareCertification.is_active == True,  # noqa: E712
        )
    ).all()
    for item in existing:
        if certification_id is not None and item.id == certification_id:
            continue
        if _periods_overlap(effective_from, effective_to, item.effective_from, item.effective_to):
            errors.append("既存の保育認定と適用期間が重複しています。")
            break
    return errors


def create_certification(
    session: Session,
    *,
    child: Child,
    care_time_category: CareTimeCategory,
    effective_from: date,
    effective_to: Optional[date],
    internal_note: str,
    guardian_reasons: list[dict[str, object]],
    actor_user_id,
    actor_name: str,
) -> ChildCareCertification:
    now = utc_now()
    certification = ChildCareCertification(
        child_id=child.id,
        care_time_category=care_time_category,
        effective_from=effective_from,
        effective_to=effective_to,
        internal_note=internal_note.strip() or None,
        created_at=now,
        created_by_user_id=actor_user_id,
        created_by_name=actor_name,
        updated_at=now,
        updated_by_user_id=actor_user_id,
        updated_by_name=actor_name,
    )
    session.add(certification)
    session.flush()
    for row in guardian_reasons:
        session.add(
            ChildCareNeedReason(
                certification_id=certification.id,
                guardian_order=int(row["guardian_order"]),
                guardian_name_snapshot=str(row.get("guardian_name_snapshot") or "").strip(),
                relationship_snapshot=str(row.get("relationship_snapshot") or "").strip(),
                reason=row["reason"],
                other_reason_detail=str(row.get("other_reason_detail") or "").strip() or None,
            )
        )
    session.flush()
    session.refresh(certification)
    session.add(
        ChildCareCertificationAuditLog(
            certification_id=certification.id,
            child_id=child.id,
            action="created",
            after_snapshot=certification_snapshot(certification, guardian_reasons),
            executed_by_user_id=actor_user_id,
            executed_by_name=actor_name,
            executed_at=now,
        )
    )
    return certification


def deactivate_certification(
    session: Session,
    certification: ChildCareCertification,
    *,
    reason: str,
    actor_user_id,
    actor_name: str,
) -> None:
    if not reason.strip():
        raise ValueError("無効化理由を入力してください。")
    before = certification_snapshot(certification)
    certification.is_active = False
    certification.updated_at = utc_now()
    certification.updated_by_user_id = actor_user_id
    certification.updated_by_name = actor_name
    session.add(certification)
    session.add(
        ChildCareCertificationAuditLog(
            certification_id=certification.id,
            child_id=certification.child_id,
            action="deactivated",
            before_snapshot=before,
            after_snapshot=certification_snapshot(certification),
            reason=reason.strip(),
            executed_by_user_id=actor_user_id,
            executed_by_name=actor_name,
        )
    )


def certification_snapshot(
    certification: ChildCareCertification,
    guardian_reasons: Optional[list[dict[str, object]]] = None,
) -> dict[str, object]:
    reason_rows = guardian_reasons
    if reason_rows is None:
        reason_rows = [
            {
                "guardian_order": item.guardian_order,
                "guardian_name_snapshot": item.guardian_name_snapshot,
                "relationship_snapshot": item.relationship_snapshot,
                "reason": item.reason.value,
                "other_reason_detail": item.other_reason_detail or "",
            }
            for item in certification.reasons
        ]
    normalized_reasons = []
    for row in reason_rows:
        reason = row.get("reason")
        normalized_reasons.append(
            {
                "guardian_order": int(row.get("guardian_order") or 0),
                "guardian_name_snapshot": str(row.get("guardian_name_snapshot") or ""),
                "relationship_snapshot": str(row.get("relationship_snapshot") or ""),
                "reason": reason.value if isinstance(reason, CareNeedReason) else str(reason or ""),
                "other_reason_detail": str(row.get("other_reason_detail") or ""),
            }
        )
    return {
        "care_time_category": certification.care_time_category.value,
        "effective_from": certification.effective_from.isoformat(),
        "effective_to": certification.effective_to.isoformat() if certification.effective_to else "",
        "internal_note": certification.internal_note or "",
        "is_active": certification.is_active,
        "reasons": normalized_reasons,
    }


def current_certification(session: Session, child_id: int) -> Optional[ChildCareCertification]:
    return effective_certification(session, child_id, local_today())


def _periods_overlap(
    start_a: date,
    end_a: Optional[date],
    start_b: date,
    end_b: Optional[date],
) -> bool:
    return start_a <= (end_b or date.max) and start_b <= (end_a or date.max)

