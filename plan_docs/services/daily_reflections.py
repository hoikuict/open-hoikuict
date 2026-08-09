from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, time
from typing import Iterable

from sqlmodel import Session, select

from time_utils import local_now, utc_now

from ..contracts import DocumentStatus, DocumentType
from ..db_models import PlanDailyReflectionRow
from ..models import PlanDocument


REFLECTION_STATUS_DRAFT = "draft"
REFLECTION_STATUS_SUBMITTED = "submitted"
DEFAULT_REMINDER_TIME = time(16, 30)


class DailyReflectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReflectionReminder:
    document_id: int
    document_title: str
    target_date: str
    classroom_ref: str
    owner_name: str
    kind: str
    message: str


def reminder_time() -> time:
    raw_value = os.getenv("HOIKU_DAILY_REFLECTION_REMINDER_TIME", "16:30").strip()
    try:
        hour_text, minute_text = raw_value.split(":", 1)
        return time(int(hour_text), int(minute_text))
    except (TypeError, ValueError):
        return DEFAULT_REMINDER_TIME


def reflection_for_document(
    session: Session,
    document_id: int,
) -> PlanDailyReflectionRow | None:
    return session.exec(
        select(PlanDailyReflectionRow).where(
            PlanDailyReflectionRow.document_id == document_id
        )
    ).first()


def reflections_by_document_id(
    session: Session,
    document_ids: Iterable[int],
) -> dict[int, PlanDailyReflectionRow]:
    ids = [int(document_id) for document_id in document_ids]
    if not ids:
        return {}
    rows = session.exec(
        select(PlanDailyReflectionRow).where(
            PlanDailyReflectionRow.document_id.in_(ids)
        )
    ).all()
    return {row.document_id: row for row in rows}


def reflection_state(reflection: PlanDailyReflectionRow | None) -> str:
    if reflection and reflection.status == REFLECTION_STATUS_SUBMITTED:
        return REFLECTION_STATUS_SUBMITTED
    if reflection and reflection.body.strip():
        return REFLECTION_STATUS_DRAFT
    return "missing"


def reflection_state_label(reflection: PlanDailyReflectionRow | None) -> str:
    return {
        "missing": "振り返り未入力",
        REFLECTION_STATUS_DRAFT: "振り返り下書き",
        REFLECTION_STATUS_SUBMITTED: "振り返り提出済み",
    }[reflection_state(reflection)]


def save_daily_reflection(
    session: Session,
    *,
    document_id: int,
    body: str,
    actor_ref: str,
    submit: bool,
) -> PlanDailyReflectionRow:
    cleaned_body = body.strip()
    if submit and not cleaned_body:
        raise DailyReflectionError("振り返りを入力してください")
    reflection = reflection_for_document(session, document_id)
    if reflection is None:
        reflection = PlanDailyReflectionRow(
            document_id=document_id,
            body=cleaned_body,
            updated_by=actor_ref,
        )
    reflection.body = cleaned_body
    reflection.updated_by = actor_ref
    reflection.updated_at = utc_now()
    if submit:
        reflection.status = REFLECTION_STATUS_SUBMITTED
        reflection.submitted_by = actor_ref
        reflection.submitted_at = reflection.updated_at
    else:
        reflection.status = REFLECTION_STATUS_DRAFT
        reflection.submitted_by = None
        reflection.submitted_at = None
    session.add(reflection)
    session.commit()
    session.refresh(reflection)
    return reflection


def list_reflection_reminders(
    *,
    documents: Iterable[PlanDocument],
    reflections: dict[int, PlanDailyReflectionRow],
    actor_ref: str | None,
    is_admin: bool,
    now: datetime | None = None,
) -> list[ReflectionReminder]:
    current = now or local_now()
    current_date = current.date()
    deadline_time = reminder_time()
    reminders: list[ReflectionReminder] = []
    for document in documents:
        if (
            document.id is None
            or document.document_type != DocumentType.DAILY_PLAN
            or document.status == DocumentStatus.ARCHIVED
            or not document.target_date
            or reflection_state(reflections.get(document.id)) == REFLECTION_STATUS_SUBMITTED
        ):
            continue
        try:
            target_date = datetime.fromisoformat(document.target_date).date()
        except ValueError:
            continue
        if target_date.weekday() >= 5:
            continue
        is_owner_due = (
            actor_ref is not None
            and actor_ref == document.actor_ref
            and current_date == target_date
            and current.time().replace(tzinfo=None) >= deadline_time
        )
        is_admin_overdue = is_admin and current_date > target_date
        if not is_owner_due and not is_admin_overdue:
            continue
        kind = "overdue_admin" if is_admin_overdue else "due_owner"
        message = (
            f"{document.owner_name}さんの振り返りが未提出です。"
            if is_admin_overdue
            else f"本日{deadline_time.strftime('%H:%M')}締切の振り返りが未提出です。"
        )
        reminders.append(
            ReflectionReminder(
                document_id=document.id,
                document_title=document.title,
                target_date=document.target_date,
                classroom_ref=document.classroom_ref,
                owner_name=document.owner_name,
                kind=kind,
                message=message,
            )
        )
    return sorted(reminders, key=lambda item: (item.target_date, item.classroom_ref))
