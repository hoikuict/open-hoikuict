from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from auth import StaffUser, require_admin, require_can_edit
from calendar_service import get_calendar_context, localize_datetime
from models import (
    CalendarMemberRole,
    Event,
    EventKind,
    EventSeries,
    EventSeriesMember,
    EventSeriesMemberTargetType,
    EventVisibility,
    HighlightCreatedVia,
    HighlightSourceType,
    HighlightStatus,
    InstitutionalRecord,
    InstitutionalRecordLink,
    InstitutionalRecordOrigin,
    InstitutionalRecordReview,
    InstitutionalRecordRevision,
    InstitutionalRecordSeriesLink,
    InstitutionalRecordStatus,
    InstitutionalRecordVisibility,
    MeetingNote,
    Notice,
    RecordHighlight,
    RecordHighlightComment,
    RecordLinkTargetType,
    RecordReviewDecision,
    RecordRevisionKind,
    Survey,
)
from time_utils import local_today, utc_now

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    target_type: RecordLinkTargetType
    target_id: str | None
    label: str


@dataclass(frozen=True, slots=True)
class ResolvedLinkLabel:
    label: str | None
    accessible: bool
    missing_unexpectedly: bool = False


@dataclass(frozen=True, slots=True)
class SeriesRecordView:
    record: InstitutionalRecord
    series_link: InstitutionalRecordSeriesLink
    current_member: EventSeriesMember
    review: InstitutionalRecordReview | None


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="対象が見つかりません")


def _clean_required(value: str, *, field_label: str, max_length: int) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field_label}を入力してください")
    if len(cleaned) > max_length:
        raise HTTPException(
            status_code=400,
            detail=f"{field_label}は{max_length}文字以内で入力してください",
        )
    return cleaned


def _clean_optional(value: str | None, *, field_label: str, max_length: int) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > max_length:
        raise HTTPException(
            status_code=400,
            detail=f"{field_label}は{max_length}文字以内で入力してください",
        )
    return cleaned


def _validate_record_fields(
    *,
    title: str,
    origin: InstitutionalRecordOrigin,
    background: str,
    purpose: str,
    revisit_condition: str | None,
    fiscal_year: int | None,
) -> dict[str, object]:
    if fiscal_year is not None and not 1900 <= fiscal_year <= 2100:
        raise HTTPException(status_code=400, detail="対象年度は1900〜2100で入力してください")
    if origin == InstitutionalRecordOrigin.retrospective and fiscal_year is None:
        raise HTTPException(status_code=400, detail="行事反省には対象年度が必要です")
    return {
        "title": _clean_required(title, field_label="タイトル", max_length=200),
        "origin": origin,
        "background": _clean_required(background, field_label="きっかけ・背景", max_length=10000),
        "purpose": _clean_required(purpose, field_label="目的", max_length=4000),
        "revisit_condition": _clean_optional(
            revisit_condition,
            field_label="見直し条件",
            max_length=4000,
        ),
        "fiscal_year": fiscal_year,
    }


def _actor_values(principal: StaffUser) -> dict[str, object]:
    return {"user_id": principal.user_id, "name": principal.name}


def _revision_from_record(
    record: InstitutionalRecord,
    *,
    kind: RecordRevisionKind,
    principal: StaffUser,
    change_note: str | None,
) -> InstitutionalRecordRevision:
    return InstitutionalRecordRevision(
        record_id=record.id,
        revision_no=record.revision_no,
        kind=kind,
        title=record.title,
        origin=record.origin,
        status=record.status,
        visibility=record.visibility,
        background=record.background,
        purpose=record.purpose,
        revisit_condition=record.revisit_condition,
        occurred_on=record.occurred_on,
        fiscal_year=record.fiscal_year,
        change_note=change_note,
        edited_by_user_id=principal.user_id,
        edited_by=principal.name,
    )


def assert_target_access(
    session: Session,
    principal: StaffUser,
    target_type: RecordLinkTargetType | EventSeriesMemberTargetType | HighlightSourceType,
    target_id: str | int | UUID | None,
    *,
    action: Literal["view", "edit", "delete"],
    external_label: str | None = None,
) -> TargetSnapshot:
    if not isinstance(target_type, RecordLinkTargetType):
        target_type = RecordLinkTargetType(target_type.value)
    if action != "view" and not principal.can_edit:
        raise _not_found()

    if target_type == RecordLinkTargetType.external:
        if target_id not in (None, ""):
            raise _not_found()
        label = _clean_required(external_label or "", field_label="外部資料名", max_length=255)
        return TargetSnapshot(target_type=target_type, target_id=None, label=label)

    raw_id = str(target_id or "").strip()
    if not raw_id:
        raise _not_found()

    if target_type in {
        RecordLinkTargetType.survey,
        RecordLinkTargetType.notice,
        RecordLinkTargetType.meeting_note,
        RecordLinkTargetType.event_series,
    }:
        try:
            normalized_id = int(raw_id)
        except (TypeError, ValueError):
            raise _not_found() from None
        model = {
            RecordLinkTargetType.survey: Survey,
            RecordLinkTargetType.notice: Notice,
            RecordLinkTargetType.meeting_note: MeetingNote,
            RecordLinkTargetType.event_series: EventSeries,
        }[target_type]
        target = session.get(model, normalized_id)
        if target is None:
            raise _not_found()
        return TargetSnapshot(
            target_type=target_type,
            target_id=str(normalized_id),
            label=target.name if target_type == RecordLinkTargetType.event_series else target.title,
        )

    if target_type != RecordLinkTargetType.event:
        raise _not_found()
    try:
        normalized_uuid = UUID(raw_id)
    except (TypeError, ValueError):
        raise _not_found() from None
    event = session.get(Event, normalized_uuid)
    if event is None or event.is_deleted or principal.user_id is None:
        raise _not_found()
    context = get_calendar_context(session, principal.user_id, event.calendar_id)
    if context is None or context.calendar.is_archived:
        raise _not_found()

    is_owner = context.membership.role == CalendarMemberRole.owner
    is_editor = context.membership.role == CalendarMemberRole.editor
    is_creator = event.created_by_user_id == principal.user_id
    can_view_details = event.visibility == EventVisibility.normal or is_creator
    if not can_view_details:
        raise _not_found()
    if action != "view":
        can_edit = principal.can_edit and (
            is_owner or is_creator or (is_editor and event.visibility == EventVisibility.normal)
        )
        if not can_edit:
            raise _not_found()
    return TargetSnapshot(
        target_type=target_type,
        target_id=str(normalized_uuid),
        label=event.title,
    )


def record_visible_to(session: Session, principal: StaffUser, record: InstitutionalRecord) -> bool:
    if record.visibility == InstitutionalRecordVisibility.staff:
        return True
    if principal.is_admin:
        return True

    links = record.links
    if "links" not in record.__dict__:
        links = session.exec(
            select(InstitutionalRecordLink).where(
                InstitutionalRecordLink.record_id == record.id,
            )
        ).all()
    for link in links:
        if link.removed_at is not None or link.target_deleted_at is not None:
            continue
        if link.target_type == RecordLinkTargetType.external:
            return True
        try:
            assert_target_access(
                session,
                principal,
                link.target_type,
                link.target_id,
                action="view",
            )
        except HTTPException:
            continue
        return True
    return False


def load_record_for_view(
    session: Session,
    principal: StaffUser,
    record_id: int,
) -> InstitutionalRecord:
    record = session.exec(
        select(InstitutionalRecord)
        .options(
            selectinload(InstitutionalRecord.links),
            selectinload(InstitutionalRecord.revisions),
        )
        .where(InstitutionalRecord.id == record_id)
    ).first()
    if record is None or not record_visible_to(session, principal, record):
        raise HTTPException(status_code=404, detail="経緯レコードが見つかりません")
    return record


def list_visible_records(
    session: Session,
    principal: StaffUser,
    *,
    origin: InstitutionalRecordOrigin | None = None,
    status: InstitutionalRecordStatus | None = None,
) -> list[InstitutionalRecord]:
    statement = select(InstitutionalRecord).options(selectinload(InstitutionalRecord.links))
    if origin is not None:
        statement = statement.where(InstitutionalRecord.origin == origin)
    if status is not None:
        statement = statement.where(InstitutionalRecord.status == status)
    statement = statement.order_by(InstitutionalRecord.updated_at.desc(), InstitutionalRecord.id.desc())
    return [
        record
        for record in session.exec(statement).all()
        if record_visible_to(session, principal, record)
    ]


def create_record(
    session: Session,
    principal: StaffUser,
    *,
    title: str,
    origin: InstitutionalRecordOrigin,
    background: str,
    purpose: str,
    visibility: InstitutionalRecordVisibility = InstitutionalRecordVisibility.staff,
    revisit_condition: str | None = None,
    occurred_on: date | None = None,
    fiscal_year: int | None = None,
    review_due_on: date | None = None,
    initial_target_type: RecordLinkTargetType | None = None,
    initial_target_id: str | int | UUID | None = None,
    initial_target_label: str | None = None,
) -> InstitutionalRecord:
    require_can_edit(principal)
    values = _validate_record_fields(
        title=title,
        origin=origin,
        background=background,
        purpose=purpose,
        revisit_condition=revisit_condition,
        fiscal_year=fiscal_year,
    )
    snapshot = None
    if initial_target_type is not None:
        snapshot = assert_target_access(
            session,
            principal,
            initial_target_type,
            initial_target_id,
            action="edit",
            external_label=initial_target_label,
        )
    if visibility == InstitutionalRecordVisibility.linked_targets and snapshot is None:
        raise HTTPException(status_code=400, detail="限定公開にはリンク先が1件以上必要です")

    actor = _actor_values(principal)
    record = InstitutionalRecord(
        **values,
        visibility=visibility,
        occurred_on=occurred_on,
        review_due_on=review_due_on,
        revision_no=1,
        created_by_user_id=actor["user_id"],
        updated_by_user_id=actor["user_id"],
        created_by=actor["name"],
        updated_by=actor["name"],
    )
    session.add(record)
    session.flush()
    session.add(
        _revision_from_record(
            record,
            kind=RecordRevisionKind.created,
            principal=principal,
            change_note=None,
        )
    )
    if snapshot is not None:
        session.add(
            InstitutionalRecordLink(
                record_id=record.id,
                target_type=snapshot.target_type,
                target_id=snapshot.target_id,
                target_label=snapshot.label,
                created_by_user_id=principal.user_id,
                created_by=principal.name,
            )
        )
    session.flush()
    return record


def _atomic_record_update(
    session: Session,
    *,
    record_id: int,
    expected_revision_no: int,
    values: dict[str, object],
) -> InstitutionalRecord:
    next_revision_no = expected_revision_no + 1
    result = session.exec(
        update(InstitutionalRecord)
        .where(
            InstitutionalRecord.id == record_id,
            InstitutionalRecord.revision_no == expected_revision_no,
        )
        .values(**values, revision_no=next_revision_no, updated_at=utc_now())
    )
    if result.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="別の職員が先に更新しました。画面を再読み込みしてください",
        )
    session.flush()
    session.expire_all()
    record = session.get(InstitutionalRecord, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="経緯レコードが見つかりません")
    return record


def update_record(
    session: Session,
    principal: StaffUser,
    record_id: int,
    *,
    expected_revision_no: int,
    change_note: str,
    title: str,
    origin: InstitutionalRecordOrigin,
    background: str,
    purpose: str,
    revisit_condition: str | None = None,
    occurred_on: date | None = None,
    fiscal_year: int | None = None,
    review_due_on: date | None = None,
) -> InstitutionalRecord:
    require_can_edit(principal)
    current = load_record_for_view(session, principal, record_id)
    if current.status != InstitutionalRecordStatus.active:
        raise HTTPException(status_code=409, detail="退役済みの経緯レコードは改訂できません")
    note = _clean_required(change_note, field_label="変更理由", max_length=1000)
    values = _validate_record_fields(
        title=title,
        origin=origin,
        background=background,
        purpose=purpose,
        revisit_condition=revisit_condition,
        fiscal_year=fiscal_year,
    )
    values.update(
        occurred_on=occurred_on,
        review_due_on=review_due_on,
        updated_by_user_id=principal.user_id,
        updated_by=principal.name,
    )
    record = _atomic_record_update(
        session,
        record_id=record_id,
        expected_revision_no=expected_revision_no,
        values=values,
    )
    session.add(
        _revision_from_record(
            record,
            kind=RecordRevisionKind.revised,
            principal=principal,
            change_note=note,
        )
    )
    session.flush()
    return record


def retire_record(
    session: Session,
    principal: StaffUser,
    record_id: int,
    *,
    expected_revision_no: int,
    change_note: str,
) -> InstitutionalRecord:
    require_can_edit(principal)
    current = load_record_for_view(session, principal, record_id)
    if current.status == InstitutionalRecordStatus.retired:
        return current
    note = _clean_required(change_note, field_label="退役理由", max_length=1000)
    record = _atomic_record_update(
        session,
        record_id=record_id,
        expected_revision_no=expected_revision_no,
        values={
            "status": InstitutionalRecordStatus.retired,
            "review_due_on": None,
            "updated_by_user_id": principal.user_id,
            "updated_by": principal.name,
        },
    )
    session.add(
        _revision_from_record(
            record,
            kind=RecordRevisionKind.retired,
            principal=principal,
            change_note=note,
        )
    )
    session.flush()
    return record


def change_record_visibility(
    session: Session,
    principal: StaffUser,
    record_id: int,
    *,
    new_visibility: InstitutionalRecordVisibility,
    expected_revision_no: int,
    change_note: str,
) -> InstitutionalRecord:
    require_can_edit(principal)
    current = load_record_for_view(session, principal, record_id)
    if current.visibility == new_visibility:
        return current
    if (
        current.visibility == InstitutionalRecordVisibility.linked_targets
        and new_visibility == InstitutionalRecordVisibility.staff
    ):
        require_admin(principal)
    if new_visibility == InstitutionalRecordVisibility.linked_targets:
        active_links = [
            link
            for link in current.links
            if link.removed_at is None and link.target_deleted_at is None
        ]
        if not active_links:
            raise HTTPException(status_code=400, detail="限定公開には有効なリンク先が必要です")
        if not any(
            link.target_type == RecordLinkTargetType.external
            or _link_accessible(session, principal, link)
            for link in active_links
        ):
            raise HTTPException(status_code=400, detail="変更後にこのレコードを閲覧できなくなります")
    note = _clean_required(change_note, field_label="可視性の変更理由", max_length=1000)
    record = _atomic_record_update(
        session,
        record_id=record_id,
        expected_revision_no=expected_revision_no,
        values={
            "visibility": new_visibility,
            "updated_by_user_id": principal.user_id,
            "updated_by": principal.name,
        },
    )
    session.add(
        _revision_from_record(
            record,
            kind=RecordRevisionKind.visibility_changed,
            principal=principal,
            change_note=note,
        )
    )
    session.flush()
    return record


def _link_accessible(session: Session, principal: StaffUser, link: InstitutionalRecordLink) -> bool:
    try:
        assert_target_access(
            session,
            principal,
            link.target_type,
            link.target_id,
            action="view",
        )
    except HTTPException:
        return False
    return True


def add_link(
    session: Session,
    principal: StaffUser,
    record_id: int,
    *,
    target_type: RecordLinkTargetType,
    target_id: str | int | UUID | None,
    target_label: str | None = None,
) -> InstitutionalRecordLink:
    require_can_edit(principal)
    load_record_for_view(session, principal, record_id)
    snapshot = assert_target_access(
        session,
        principal,
        target_type,
        target_id,
        action="edit",
        external_label=target_label,
    )
    statement = select(InstitutionalRecordLink).where(
        InstitutionalRecordLink.record_id == record_id,
        InstitutionalRecordLink.target_type == snapshot.target_type,
    )
    if snapshot.target_type != RecordLinkTargetType.external:
        statement = statement.where(InstitutionalRecordLink.target_id == snapshot.target_id)
        existing = session.exec(statement).first()
    else:
        existing = next(
            (
                link
                for link in session.exec(statement).all()
                if link.target_label.strip().casefold() == snapshot.label.strip().casefold()
            ),
            None,
        )
    if existing is not None:
        if existing.removed_at is None:
            raise HTTPException(status_code=409, detail="同じリンク先がすでに登録されています")
        existing.removed_at = None
        existing.removed_by_user_id = None
        existing.removed_by = None
        existing.target_deleted_at = None
        existing.target_label = snapshot.label
        session.add(existing)
        session.flush()
        return existing

    link = InstitutionalRecordLink(
        record_id=record_id,
        target_type=snapshot.target_type,
        target_id=snapshot.target_id,
        target_label=snapshot.label,
        created_by_user_id=principal.user_id,
        created_by=principal.name,
    )
    session.add(link)
    session.flush()
    return link


def remove_link(
    session: Session,
    principal: StaffUser,
    record_id: int,
    link_id: int,
) -> InstitutionalRecordLink:
    require_can_edit(principal)
    load_record_for_view(session, principal, record_id)
    link = session.get(InstitutionalRecordLink, link_id)
    if link is None or link.record_id != record_id:
        raise HTTPException(status_code=404, detail="リンクが見つかりません")
    if link.removed_at is None:
        link.removed_at = utc_now()
        link.removed_by_user_id = principal.user_id
        link.removed_by = principal.name
        session.add(link)
        session.flush()
    return link


def resolve_link_labels(
    session: Session,
    principal: StaffUser,
    links: list[InstitutionalRecordLink],
) -> dict[int, ResolvedLinkLabel]:
    resolved: dict[int, ResolvedLinkLabel] = {}
    for link in links:
        if link.id is None:
            continue
        if link.target_type == RecordLinkTargetType.external or link.target_deleted_at is not None:
            resolved[link.id] = ResolvedLinkLabel(label=link.target_label, accessible=True)
            continue
        try:
            snapshot = assert_target_access(
                session,
                principal,
                link.target_type,
                link.target_id,
                action="view",
            )
        except HTTPException:
            if principal.is_admin:
                logger.warning(
                    "institutional record link target is unavailable: link_id=%s type=%s id=%s",
                    link.id,
                    link.target_type.value,
                    link.target_id,
                )
                resolved[link.id] = ResolvedLinkLabel(
                    label="対象不明（削除処理漏れの可能性）",
                    accessible=False,
                    missing_unexpectedly=True,
                )
            else:
                resolved[link.id] = ResolvedLinkLabel(label=None, accessible=False)
            continue
        resolved[link.id] = ResolvedLinkLabel(label=snapshot.label, accessible=True)
    return resolved


def records_for_target(
    session: Session,
    principal: StaffUser,
    target_type: RecordLinkTargetType,
    target_id: str | int | UUID,
    *,
    include_retired: bool = False,
) -> list[InstitutionalRecord]:
    snapshot = assert_target_access(session, principal, target_type, target_id, action="view")
    statement = (
        select(InstitutionalRecord)
        .join(InstitutionalRecordLink)
        .options(selectinload(InstitutionalRecord.links))
        .where(
            InstitutionalRecordLink.target_type == snapshot.target_type,
            InstitutionalRecordLink.target_id == snapshot.target_id,
            InstitutionalRecordLink.removed_at.is_(None),
            InstitutionalRecordLink.target_deleted_at.is_(None),
        )
    )
    if not include_retired:
        statement = statement.where(InstitutionalRecord.status == InstitutionalRecordStatus.active)
    records = session.exec(statement.order_by(InstitutionalRecord.updated_at.desc())).all()
    return [record for record in records if record_visible_to(session, principal, record)]


def persistent_records_for_target(
    session: Session,
    principal: StaffUser,
    target_type: RecordLinkTargetType,
    target_id: str | int | UUID,
) -> list[InstitutionalRecord]:
    return [
        record
        for record in records_for_target(session, principal, target_type, target_id)
        if record.origin.is_persistent
    ]


def fiscal_year_for_datetime(value: datetime, timezone_name: str = "Asia/Tokyo") -> int:
    local_value = localize_datetime(value, timezone_name)
    return local_value.year if local_value.month >= 4 else local_value.year - 1


def _next_year(value: date) -> date:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        return value.replace(year=value.year + 1, day=28)


def create_event_series(
    session: Session,
    principal: StaffUser,
    *,
    name: str,
    description: str | None = None,
) -> EventSeries:
    require_can_edit(principal)
    series = EventSeries(
        name=_clean_required(name, field_label="シリーズ名", max_length=100),
        description=_clean_optional(description, field_label="説明", max_length=4000),
        created_by_user_id=principal.user_id,
        created_by=principal.name,
    )
    session.add(series)
    session.flush()
    return series


def list_event_series(session: Session, *, include_inactive: bool = False) -> list[EventSeries]:
    statement = select(EventSeries)
    if not include_inactive:
        statement = statement.where(EventSeries.is_active.is_(True))
    return session.exec(statement.order_by(EventSeries.name, EventSeries.id)).all()


def load_event_series(session: Session, series_id: int) -> EventSeries:
    series = session.get(EventSeries, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="行事シリーズが見つかりません")
    return series


def add_series_member(
    session: Session,
    principal: StaffUser,
    series_id: int,
    *,
    target_type: EventSeriesMemberTargetType,
    target_id: str | int | UUID,
    fiscal_year: int,
) -> EventSeriesMember:
    require_can_edit(principal)
    series = load_event_series(session, series_id)
    if not series.is_active:
        raise HTTPException(status_code=409, detail="停止中のシリーズには追加できません")
    if not 1900 <= fiscal_year <= 2100:
        raise HTTPException(status_code=400, detail="対象年度は1900〜2100で入力してください")
    snapshot = assert_target_access(session, principal, target_type, target_id, action="edit")
    if target_type == EventSeriesMemberTargetType.event:
        event = session.get(Event, UUID(snapshot.target_id))
        if event is None or event.kind != EventKind.single:
            raise HTTPException(
                status_code=400,
                detail="繰り返し予定は行事シリーズへ登録できません。単発の予定を指定してください",
            )
    existing = session.exec(
        select(EventSeriesMember).where(
            EventSeriesMember.target_type == target_type,
            EventSeriesMember.target_id == snapshot.target_id,
        )
    ).first()
    if existing is not None:
        if existing.series_id == series_id and existing.fiscal_year == fiscal_year:
            return existing
        raise HTTPException(status_code=409, detail="この対象は別の行事シリーズまたは年度に登録済みです")
    member = EventSeriesMember(
        series_id=series_id,
        target_type=target_type,
        target_id=snapshot.target_id,
        fiscal_year=fiscal_year,
        created_by_user_id=principal.user_id,
        created_by=principal.name,
    )
    session.add(member)
    session.flush()
    return member


def series_members(session: Session, series_id: int) -> list[EventSeriesMember]:
    load_event_series(session, series_id)
    return session.exec(
        select(EventSeriesMember)
        .where(EventSeriesMember.series_id == series_id)
        .order_by(EventSeriesMember.fiscal_year.desc(), EventSeriesMember.id.desc())
    ).all()


def records_for_event_series(
    session: Session,
    principal: StaffUser,
    series_id: int,
) -> list[tuple[InstitutionalRecord, InstitutionalRecordSeriesLink]]:
    load_event_series(session, series_id)
    rows = session.exec(
        select(InstitutionalRecord, InstitutionalRecordSeriesLink)
        .join(
            InstitutionalRecordSeriesLink,
            InstitutionalRecordSeriesLink.record_id == InstitutionalRecord.id,
        )
        .options(selectinload(InstitutionalRecord.links))
        .where(InstitutionalRecordSeriesLink.series_id == series_id)
        .order_by(
            InstitutionalRecordSeriesLink.fiscal_year.desc(),
            InstitutionalRecord.updated_at.desc(),
        )
    ).all()
    return [
        (record, link)
        for record, link in rows
        if record_visible_to(session, principal, record)
    ]


def series_member_for_target(
    session: Session,
    target_type: EventSeriesMemberTargetType,
    target_id: str | int | UUID,
) -> EventSeriesMember | None:
    normalized_id = str(target_id)
    if target_type == EventSeriesMemberTargetType.event:
        try:
            normalized_id = str(UUID(normalized_id))
        except ValueError:
            return None
    elif target_type in {
        EventSeriesMemberTargetType.survey,
        EventSeriesMemberTargetType.meeting_note,
    }:
        try:
            normalized_id = str(int(normalized_id))
        except ValueError:
            return None
    return session.exec(
        select(EventSeriesMember).where(
            EventSeriesMember.target_type == target_type,
            EventSeriesMember.target_id == normalized_id,
        )
    ).first()


def create_highlight(
    session: Session,
    principal: StaffUser,
    *,
    source_type: HighlightSourceType,
    source_id: str | int,
    excerpt: str,
    origin: InstitutionalRecordOrigin,
    series_id: int | None = None,
    fiscal_year: int | None = None,
    comment: str | None = None,
) -> RecordHighlight:
    require_can_edit(principal)
    snapshot = assert_target_access(session, principal, source_type, source_id, action="edit")
    excerpt_value = _clean_required(excerpt, field_label="抜き書き", max_length=4000)
    if series_id is None and fiscal_year is not None:
        raise HTTPException(status_code=400, detail="対象年度を指定する場合は行事シリーズも選んでください")
    if series_id is not None:
        series = load_event_series(session, series_id)
        if not series.is_active:
            raise HTTPException(status_code=409, detail="停止中のシリーズは選べません")
        if fiscal_year is None or not 1900 <= fiscal_year <= 2100:
            raise HTTPException(status_code=400, detail="行事シリーズには対象年度が必要です")
    highlight = RecordHighlight(
        source_type=source_type,
        source_id=snapshot.target_id,
        excerpt=excerpt_value,
        origin=origin,
        series_id=series_id,
        fiscal_year=fiscal_year,
        status=HighlightStatus.active,
        created_via=HighlightCreatedVia.manual,
        created_by_user_id=principal.user_id,
        updated_by_user_id=principal.user_id,
        created_by=principal.name,
        updated_by=principal.name,
    )
    session.add(highlight)
    session.flush()
    comment_value = _clean_optional(comment, field_label="コメント", max_length=2000)
    if comment_value:
        session.add(
            RecordHighlightComment(
                highlight_id=highlight.id,
                body=comment_value,
                author_user_id=principal.user_id,
                author=principal.name,
            )
        )
        session.flush()
    return highlight


def highlights_for_source(
    session: Session,
    principal: StaffUser,
    source_type: HighlightSourceType,
    source_id: str | int,
) -> list[RecordHighlight]:
    snapshot = assert_target_access(session, principal, source_type, source_id, action="view")
    return session.exec(
        select(RecordHighlight)
        .options(selectinload(RecordHighlight.comments))
        .where(
            RecordHighlight.source_type == source_type,
            RecordHighlight.source_id == snapshot.target_id,
            RecordHighlight.status != HighlightStatus.suggested,
        )
        .order_by(RecordHighlight.created_at.desc(), RecordHighlight.id.desc())
    ).all()


def add_highlight_comment(
    session: Session,
    principal: StaffUser,
    highlight_id: int,
    *,
    body: str,
) -> RecordHighlightComment:
    require_can_edit(principal)
    highlight = session.get(RecordHighlight, highlight_id)
    if highlight is None:
        raise HTTPException(status_code=404, detail="マーキングが見つかりません")
    assert_target_access(
        session,
        principal,
        highlight.source_type,
        highlight.source_id,
        action="edit",
    )
    if highlight.status == HighlightStatus.archived:
        raise HTTPException(status_code=409, detail="対応済みのマーキングにはコメントできません")
    comment = RecordHighlightComment(
        highlight_id=highlight.id,
        body=_clean_required(body, field_label="コメント", max_length=2000),
        author_user_id=principal.user_id,
        author=principal.name,
    )
    session.add(comment)
    session.flush()
    return comment


def promote_highlight(
    session: Session,
    principal: StaffUser,
    highlight_id: int,
    *,
    title: str,
    purpose: str,
    fiscal_year: int | None = None,
    revisit_condition: str | None = None,
    review_due_on: date | None = None,
    visibility: InstitutionalRecordVisibility = InstitutionalRecordVisibility.staff,
) -> InstitutionalRecord:
    require_can_edit(principal)
    highlight = session.get(RecordHighlight, highlight_id)
    if highlight is None:
        raise HTTPException(status_code=404, detail="マーキングが見つかりません")
    if highlight.status == HighlightStatus.promoted and highlight.promoted_record_id is not None:
        record = session.get(InstitutionalRecord, highlight.promoted_record_id)
        if record is None:
            raise HTTPException(status_code=409, detail="昇格先レコードとの整合性が失われています")
        return record
    if highlight.status != HighlightStatus.active:
        raise HTTPException(status_code=409, detail="有効なマーキングだけを昇格できます")
    source = assert_target_access(
        session,
        principal,
        highlight.source_type,
        highlight.source_id,
        action="edit",
    )
    effective_fiscal_year = highlight.fiscal_year if highlight.fiscal_year is not None else fiscal_year
    if highlight.series_id is not None and fiscal_year not in (None, highlight.fiscal_year):
        raise HTTPException(status_code=400, detail="マーキングと異なる対象年度には変更できません")
    record = create_record(
        session,
        principal,
        title=title,
        origin=highlight.origin,
        background=highlight.excerpt,
        purpose=purpose,
        visibility=visibility,
        revisit_condition=revisit_condition,
        fiscal_year=effective_fiscal_year,
        review_due_on=review_due_on,
        initial_target_type=RecordLinkTargetType.meeting_note,
        initial_target_id=source.target_id,
    )
    record.source_highlight_id = highlight.id
    session.add(record)
    if highlight.series_id is not None:
        session.add(
            InstitutionalRecordSeriesLink(
                record_id=record.id,
                series_id=highlight.series_id,
                fiscal_year=effective_fiscal_year,
                created_by_user_id=principal.user_id,
                created_by=principal.name,
            )
        )
    highlight.status = HighlightStatus.promoted
    highlight.promoted_record_id = record.id
    highlight.updated_by_user_id = principal.user_id
    highlight.updated_by = principal.name
    highlight.updated_at = utc_now()
    session.add(highlight)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        current = session.get(RecordHighlight, highlight_id)
        if current is not None and current.promoted_record_id is not None:
            existing = session.get(InstitutionalRecord, current.promoted_record_id)
            if existing is not None:
                return existing
        raise HTTPException(status_code=409, detail="マーキングの昇格が競合しました") from None
    return record


def archive_highlight(
    session: Session,
    principal: StaffUser,
    highlight_id: int,
) -> RecordHighlight:
    require_can_edit(principal)
    highlight = session.get(RecordHighlight, highlight_id)
    if highlight is None:
        raise HTTPException(status_code=404, detail="マーキングが見つかりません")
    assert_target_access(
        session,
        principal,
        highlight.source_type,
        highlight.source_id,
        action="edit",
    )
    if highlight.status != HighlightStatus.active:
        raise HTTPException(status_code=409, detail="有効なマーキングだけを対応済みにできます")
    highlight.status = HighlightStatus.archived
    highlight.updated_by_user_id = principal.user_id
    highlight.updated_by = principal.name
    highlight.updated_at = utc_now()
    session.add(highlight)
    session.flush()
    return highlight


def records_for_series_of(
    session: Session,
    principal: StaffUser,
    target_type: EventSeriesMemberTargetType,
    target_id: str | int | UUID,
) -> list[SeriesRecordView]:
    snapshot = assert_target_access(session, principal, target_type, target_id, action="view")
    member = series_member_for_target(session, target_type, snapshot.target_id)
    if member is None:
        return []
    rows = session.exec(
        select(InstitutionalRecord, InstitutionalRecordSeriesLink)
        .join(
            InstitutionalRecordSeriesLink,
            InstitutionalRecordSeriesLink.record_id == InstitutionalRecord.id,
        )
        .options(selectinload(InstitutionalRecord.links))
        .where(
            InstitutionalRecordSeriesLink.series_id == member.series_id,
            InstitutionalRecordSeriesLink.fiscal_year.is_not(None),
            InstitutionalRecordSeriesLink.fiscal_year < member.fiscal_year,
            InstitutionalRecord.origin == InstitutionalRecordOrigin.retrospective,
            InstitutionalRecord.status == InstitutionalRecordStatus.active,
        )
        .order_by(
            InstitutionalRecordSeriesLink.fiscal_year.desc(),
            InstitutionalRecord.updated_at.desc(),
        )
    ).all()
    record_ids = [record.id for record, _link in rows]
    reviews_by_record: dict[int, InstitutionalRecordReview] = {}
    if record_ids:
        reviews_by_record = {
            review.record_id: review
            for review in session.exec(
                select(InstitutionalRecordReview).where(
                    InstitutionalRecordReview.record_id.in_(record_ids),
                    InstitutionalRecordReview.series_member_id == member.id,
                )
            ).all()
        }
    seen: set[int] = set()
    result: list[SeriesRecordView] = []
    for record, series_link in rows:
        if record.id in seen or not record_visible_to(session, principal, record):
            continue
        seen.add(record.id)
        result.append(
            SeriesRecordView(
                record=record,
                series_link=series_link,
                current_member=member,
                review=reviews_by_record.get(record.id),
            )
        )
    return result


def highlights_for_series(
    session: Session,
    principal: StaffUser,
    series_id: int,
    *,
    before_fiscal_year: int,
    status: HighlightStatus = HighlightStatus.active,
) -> list[RecordHighlight]:
    load_event_series(session, series_id)
    highlights = session.exec(
        select(RecordHighlight)
        .options(selectinload(RecordHighlight.comments))
        .where(
            RecordHighlight.series_id == series_id,
            RecordHighlight.fiscal_year < before_fiscal_year,
            RecordHighlight.status == status,
        )
        .order_by(RecordHighlight.fiscal_year.desc(), RecordHighlight.created_at.desc())
    ).all()
    visible: list[RecordHighlight] = []
    for highlight in highlights:
        try:
            assert_target_access(
                session,
                principal,
                highlight.source_type,
                highlight.source_id,
                action="view",
            )
        except HTTPException:
            continue
        visible.append(highlight)
    return visible


def add_review(
    session: Session,
    principal: StaffUser,
    record_id: int,
    *,
    series_member_id: int,
    review_cycle_fiscal_year: int,
    decision: RecordReviewDecision = RecordReviewDecision.keep,
    note: str | None = None,
    next_review_due_on: date | None = None,
    expected_revision_no: int | None = None,
    revised_title: str | None = None,
    revised_background: str | None = None,
    revised_purpose: str | None = None,
) -> InstitutionalRecordReview:
    require_can_edit(principal)
    record = load_record_for_view(session, principal, record_id)
    member = session.get(EventSeriesMember, series_member_id)
    if member is None or member.fiscal_year != review_cycle_fiscal_year:
        raise HTTPException(status_code=404, detail="対象年度のシリーズメンバーが見つかりません")
    assert_target_access(
        session,
        principal,
        member.target_type,
        member.target_id,
        action="edit",
    )
    series_link = session.exec(
        select(InstitutionalRecordSeriesLink).where(
            InstitutionalRecordSeriesLink.record_id == record_id,
            InstitutionalRecordSeriesLink.series_id == member.series_id,
        )
    ).first()
    if series_link is None:
        raise HTTPException(status_code=404, detail="経緯レコードと行事シリーズが一致しません")
    existing = session.exec(
        select(InstitutionalRecordReview).where(
            InstitutionalRecordReview.record_id == record_id,
            InstitutionalRecordReview.series_member_id == series_member_id,
        )
    ).first()
    if existing is not None:
        return existing

    resulting_revision_id = None
    if decision == RecordReviewDecision.keep:
        record.review_due_on = next_review_due_on or _next_year(local_today())
        record.updated_by_user_id = principal.user_id
        record.updated_by = principal.name
        record.updated_at = utc_now()
        session.add(record)
    elif decision == RecordReviewDecision.revise:
        if expected_revision_no is None:
            raise HTTPException(status_code=400, detail="改訂番号が必要です")
        revised = update_record(
            session,
            principal,
            record_id,
            expected_revision_no=expected_revision_no,
            change_note=_clean_required(note or "", field_label="変更理由", max_length=1000),
            title=revised_title or record.title,
            origin=record.origin,
            background=revised_background or record.background,
            purpose=revised_purpose or record.purpose,
            revisit_condition=record.revisit_condition,
            occurred_on=record.occurred_on,
            fiscal_year=record.fiscal_year,
            review_due_on=next_review_due_on or _next_year(local_today()),
        )
        revision = session.exec(
            select(InstitutionalRecordRevision).where(
                InstitutionalRecordRevision.record_id == revised.id,
                InstitutionalRecordRevision.revision_no == revised.revision_no,
            )
        ).one()
        resulting_revision_id = revision.id
    else:
        if expected_revision_no is None:
            raise HTTPException(status_code=400, detail="改訂番号が必要です")
        retired = retire_record(
            session,
            principal,
            record_id,
            expected_revision_no=expected_revision_no,
            change_note=_clean_required(note or "", field_label="退役理由", max_length=1000),
        )
        revision = session.exec(
            select(InstitutionalRecordRevision).where(
                InstitutionalRecordRevision.record_id == retired.id,
                InstitutionalRecordRevision.revision_no == retired.revision_no,
            )
        ).one()
        resulting_revision_id = revision.id

    review = InstitutionalRecordReview(
        record_id=record_id,
        series_member_id=series_member_id,
        review_cycle_fiscal_year=review_cycle_fiscal_year,
        decision=decision,
        note=_clean_optional(note, field_label="確認メモ", max_length=4000),
        next_review_due_on=(record.review_due_on if decision == RecordReviewDecision.keep else next_review_due_on),
        resulting_revision_id=resulting_revision_id,
        reviewed_by_user_id=principal.user_id,
        reviewed_by=principal.name,
    )
    session.add(review)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        duplicate = session.exec(
            select(InstitutionalRecordReview).where(
                InstitutionalRecordReview.record_id == record_id,
                InstitutionalRecordReview.series_member_id == series_member_id,
            )
        ).first()
        if duplicate is not None:
            return duplicate
        raise
    return review
