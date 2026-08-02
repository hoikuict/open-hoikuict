from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from attendance_checks_service import alarm_reason_labels
from calendar_service import (
    combine_local_date,
    list_calendar_contexts,
    list_occurrences,
    localize_datetime,
    normalize_utc,
)
from models import (
    AttendanceAlarmState,
    AttendanceRecord,
    AttendanceVerification,
    AttendanceVerificationStatus,
    Child,
    ChildStatus,
    Classroom,
    EventLifecycleStatus,
    Message,
    StaffClassroomAssignment,
    Survey,
    SurveyAudienceType,
    SurveyStatus,
    User,
)
from staff_user_service import equivalent_staff_user_ids
from survey_service import survey_is_open, survey_matches_staff_targets
from time_utils import ensure_utc_from_local


WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")
ABSENT_STATUSES = {
    AttendanceVerificationStatus.private_absent,
    AttendanceVerificationStatus.sick_absent,
}


@dataclass(slots=True)
class ScheduleItem:
    title: str
    time_label: str
    calendar_name: str
    calendar_color: str
    state: str
    state_label: str
    location: str | None


@dataclass(slots=True)
class AttentionItem:
    kind: str
    kind_label: str
    title: str
    detail: str
    url: str
    severity: str = "normal"


@dataclass(slots=True)
class ClassroomAttendanceSummary:
    classroom_id: int
    classroom_name: str
    enrolled_count: int = 0
    checked_in_count: int = 0
    present_count: int = 0
    checked_out_count: int = 0
    absent_count: int = 0
    not_checked_in_count: int = 0
    attention_count: int = 0
    attention_items: list[AttentionItem] = field(default_factory=list)

    @property
    def attendance_url(self) -> str:
        return "/attendance?" + urlencode(
            {
                "date": self.target_date.isoformat(),
                "classroom_id": str(self.classroom_id),
            }
        )

    # Filled by build_attendance_summaries after construction. Keeping this
    # out of the constructor makes the count-focused call sites easier to read.
    target_date: date = field(default_factory=date.today)


@dataclass(slots=True)
class AssignmentView:
    assignment: StaffClassroomAssignment
    classroom: Classroom


def format_portal_date(value: date) -> str:
    return f"{value.year}年{value.month}月{value.day}日（{WEEKDAY_LABELS[value.weekday()]}）"


def greeting_for(local_now: datetime) -> str:
    if local_now.hour < 11:
        return "おはようございます"
    if local_now.hour < 18:
        return "おつかれさまです"
    return "こんばんは"


def active_assignments(
    session: Session,
    staff_user_id: UUID,
    target_date: date,
) -> list[AssignmentView]:
    assignments = session.exec(
        select(StaffClassroomAssignment)
        .where(
            StaffClassroomAssignment.staff_user_id == staff_user_id,
            StaffClassroomAssignment.starts_on <= target_date,
            or_(
                StaffClassroomAssignment.ends_on.is_(None),
                StaffClassroomAssignment.ends_on >= target_date,
            ),
        )
        .order_by(
            StaffClassroomAssignment.is_primary.desc(),
            StaffClassroomAssignment.display_order,
            StaffClassroomAssignment.id,
        )
    ).all()
    classrooms = {
        item.id: item
        for item in session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
        if item.id is not None
    }
    return [
        AssignmentView(assignment=item, classroom=classrooms[item.classroom_id])
        for item in assignments
        if item.classroom_id in classrooms
    ]


def classroom_scope(
    session: Session,
    staff_user: User,
    target_date: date,
    *,
    show_all: bool = False,
) -> tuple[list[Classroom], list[AssignmentView]]:
    assignments = active_assignments(session, staff_user.id, target_date)
    if staff_user.staff_role == "admin" and (show_all or not assignments):
        classrooms = session.exec(
            select(Classroom).order_by(Classroom.display_order, Classroom.id)
        ).all()
        return classrooms, assignments
    return [item.classroom for item in assignments], assignments


def build_schedule_items(
    session: Session,
    staff_user: User,
    target_date: date,
    now: datetime,
    *,
    limit: int = 6,
) -> tuple[list[ScheduleItem], int]:
    contexts = [
        item
        for item in list_calendar_contexts(session, staff_user.id, include_archived=False)
        if item.is_visible
    ]
    occurrences = list_occurrences(
        session,
        contexts,
        staff_user,
        combine_local_date(target_date, staff_user.timezone),
        combine_local_date(target_date + timedelta(days=1), staff_user.timezone),
        calendar_ids={item.calendar.id for item in contexts},
    )
    current_utc = normalize_utc(now)

    def state_for(item) -> tuple[str, str, int]:
        if item.start_at <= current_utc < item.end_at:
            return "current", "進行中", 0
        if item.start_at > current_utc:
            return "upcoming", "予定", 1
        return "finished", "終了", 2

    active_occurrences = [
        item for item in occurrences if item.status == EventLifecycleStatus.confirmed
    ]
    active_occurrences.sort(
        key=lambda item: (
            state_for(item)[2],
            not item.is_all_day,
            item.start_at,
            item.display_title.lower(),
        )
    )
    result: list[ScheduleItem] = []
    for occurrence in active_occurrences[:limit]:
        local_start = localize_datetime(occurrence.start_at, staff_user.timezone)
        state, state_label, _rank = state_for(occurrence)
        result.append(
            ScheduleItem(
                title=occurrence.display_title,
                time_label="終日" if occurrence.is_all_day else local_start.strftime("%H:%M"),
                calendar_name=occurrence.calendar.name,
                calendar_color=occurrence.calendar.color,
                state=state,
                state_label=state_label,
                location=occurrence.location if occurrence.can_view_details else None,
            )
        )
    return result, max(len(active_occurrences) - limit, 0)


def build_attendance_summaries(
    session: Session,
    classrooms: list[Classroom],
    target_date: date,
    *,
    attention_limit: int | None = 5,
) -> list[ClassroomAttendanceSummary]:
    classroom_ids = [item.id for item in classrooms if item.id is not None]
    if not classroom_ids:
        return []

    children = session.exec(
        select(Child)
        .where(
            Child.classroom_id.in_(classroom_ids),
            Child.status == ChildStatus.enrolled,
            Child.enrollment_date <= target_date,
            or_(Child.withdrawal_date.is_(None), Child.withdrawal_date >= target_date),
        )
        .order_by(Child.last_name_kana, Child.first_name_kana, Child.id)
    ).all()
    child_ids = [item.id for item in children if item.id is not None]

    records = []
    verifications = []
    alarms = []
    if child_ids:
        records = session.exec(
            select(AttendanceRecord).where(
                AttendanceRecord.attendance_date == target_date,
                AttendanceRecord.child_id.in_(child_ids),
            )
        ).all()
        verifications = session.exec(
            select(AttendanceVerification).where(
                AttendanceVerification.target_date == target_date,
                AttendanceVerification.child_id.in_(child_ids),
            )
        ).all()
        alarms = session.exec(
            select(AttendanceAlarmState).where(
                AttendanceAlarmState.target_date == target_date,
                AttendanceAlarmState.child_id.in_(child_ids),
            )
        ).all()

    record_by_child = {item.child_id: item for item in records}
    verification_by_child = {item.child_id: item for item in verifications}
    alarm_by_child = {item.child_id: item for item in alarms}
    summary_by_classroom = {
        item.id: ClassroomAttendanceSummary(
            classroom_id=item.id or 0,
            classroom_name=item.name,
            target_date=target_date,
        )
        for item in classrooms
        if item.id is not None
    }

    for child in children:
        if child.id is None or child.classroom_id not in summary_by_classroom:
            continue
        summary = summary_by_classroom[child.classroom_id]
        record = record_by_child.get(child.id)
        verification = verification_by_child.get(child.id)
        alarm = alarm_by_child.get(child.id)
        is_absent = bool(verification and verification.status in ABSENT_STATUSES)
        is_unknown = verification is None or verification.status == AttendanceVerificationStatus.unknown
        has_check_in = bool(record and record.check_in_at is not None)
        has_check_out = bool(record and record.check_in_at is not None and record.check_out_at is not None)
        needs_attention = bool(alarm and alarm.is_active) or is_unknown

        summary.enrolled_count += 1
        summary.checked_in_count += int(has_check_in)
        summary.checked_out_count += int(has_check_out)
        summary.present_count += int(has_check_in and not has_check_out)
        summary.absent_count += int(is_absent)
        summary.not_checked_in_count += int(not has_check_in and not is_absent)
        summary.attention_count += int(needs_attention)

        if needs_attention and (
            attention_limit is None or len(summary.attention_items) < attention_limit
        ):
            reasons = alarm_reason_labels(alarm.reasons if alarm and alarm.is_active else None)
            if is_unknown:
                reasons.append("出欠確認が未入力です")
            summary.attention_items.append(
                AttentionItem(
                    kind="attendance",
                    kind_label="出欠",
                    title=child.full_name,
                    detail="／".join(dict.fromkeys(reasons)) or "出欠状態を確認してください",
                    url=(
                        "/attendance-checks/?"
                        + urlencode(
                            {
                                "date": target_date.isoformat(),
                                "classroom_id": str(child.classroom_id),
                                "filter": "alarm" if alarm and alarm.is_active else "unknown",
                            }
                        )
                    ),
                    severity="high" if alarm and alarm.is_active else "normal",
                )
            )

    return [
        summary_by_classroom[item.id]
        for item in classrooms
        if item.id in summary_by_classroom
    ]


def build_unanswered_survey_items(
    session: Session,
    staff_user: User,
    now: datetime,
    *,
    limit: int | None = 5,
) -> tuple[list[AttentionItem], int]:
    surveys = session.exec(
        select(Survey)
        .options(selectinload(Survey.targets), selectinload(Survey.answers))
        .where(
            Survey.audience_type == SurveyAudienceType.staff,
            Survey.status == SurveyStatus.published,
        )
        .order_by(Survey.closes_at, Survey.updated_at.desc())
    ).all()
    equivalent_ids = equivalent_staff_user_ids(session, staff_user.id)
    equivalent_id_strings = {str(item) for item in equivalent_ids}
    pending: list[Survey] = []
    for survey in surveys:
        if not survey_is_open(survey, now):
            continue
        if not survey_matches_staff_targets(survey, staff_user, equivalent_id_strings):
            continue
        if any(answer.staff_user_id in equivalent_ids for answer in survey.answers):
            continue
        pending.append(survey)

    def deadline_key(item: Survey):
        deadline = ensure_utc_from_local(item.closes_at)
        return (deadline is None, deadline or datetime.max.replace(tzinfo=now.tzinfo))

    pending.sort(key=deadline_key)
    items: list[AttentionItem] = []
    visible_surveys = pending if limit is None else pending[:limit]
    for survey in visible_surveys:
        deadline = ensure_utc_from_local(survey.closes_at)
        closes_soon = bool(deadline and deadline <= normalize_utc(now) + timedelta(hours=24))
        if survey.closes_at:
            detail = f"回答期限 {survey.closes_at:%Y-%m-%d %H:%M}"
        else:
            detail = "回答期限なし"
        items.append(
            AttentionItem(
                kind="survey",
                kind_label="アンケート",
                title=survey.title,
                detail=detail,
                url=f"/staff-surveys/{survey.id}",
                severity="high" if closes_soon else "normal",
            )
        )
    return items, len(pending)


def build_timeline_messages(
    session: Session,
    *,
    limit: int = 5,
) -> list[Message]:
    return session.exec(
        select(Message)
        .options(selectinload(Message.room))
        .where(Message.parent_message_id.is_(None))
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    ).all()


def next_schedule_item(items: list[ScheduleItem]) -> ScheduleItem | None:
    return next((item for item in items if item.state in {"current", "upcoming"}), None)
