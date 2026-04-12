from __future__ import annotations

import calendar as calendar_lib
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from models import (
    Calendar,
    CalendarMember,
    CalendarMemberRole,
    CalendarType,
    CalendarUserPreference,
    Event,
    EventKind,
    EventLifecycleStatus,
    EventOverride,
    EventVisibility,
    NotificationJob,
    NotificationJobStatus,
    RecurrenceFrequency,
    RecurrenceRule,
    Reminder,
    ReminderMethod,
    User,
)
from time_utils import ensure_utc, utc_now

NOTIFICATION_WINDOW_DAYS = 120
WEEKDAY_MAP = {
    "MO": 0,
    "TU": 1,
    "WE": 2,
    "TH": 3,
    "FR": 4,
    "SA": 5,
    "SU": 6,
}


@dataclass(slots=True)
class CalendarContext:
    calendar: Calendar
    membership: CalendarMember
    preference: CalendarUserPreference | None
    user_can_edit: bool = True

    @property
    def is_visible(self) -> bool:
        return True if self.preference is None else self.preference.is_visible

    @property
    def display_order(self) -> int:
        return 0 if self.preference is None else self.preference.display_order

    @property
    def can_create_events(self) -> bool:
        return self.user_can_edit and self.membership.role in {CalendarMemberRole.owner, CalendarMemberRole.editor}

    @property
    def can_manage_sharing(self) -> bool:
        return self.user_can_edit and self.membership.role == CalendarMemberRole.owner

    @property
    def is_staff_personal(self) -> bool:
        return self.calendar.calendar_type == CalendarType.staff_personal

    @property
    def is_facility_shared(self) -> bool:
        return self.calendar.calendar_type == CalendarType.facility_shared


@dataclass(slots=True)
class OccurrenceRecord:
    source_event: Event
    original_start_at: datetime
    start_at: datetime
    end_at: datetime
    title: str
    description: str | None
    location: str | None
    timezone: str
    is_all_day: bool
    visibility: EventVisibility
    status: EventLifecycleStatus


@dataclass(slots=True)
class EventOccurrence:
    calendar: Calendar
    membership_role: CalendarMemberRole
    source_event: Event
    original_start_at: datetime
    start_at: datetime
    end_at: datetime
    title: str
    description: str | None
    location: str | None
    timezone: str
    is_all_day: bool
    visibility: EventVisibility
    status: EventLifecycleStatus
    can_view_details: bool
    can_edit: bool
    can_delete: bool

    @property
    def is_private_hidden(self) -> bool:
        return self.visibility == EventVisibility.private and not self.can_view_details

    @property
    def display_title(self) -> str:
        return self.title if self.can_view_details else "予定あり"

    @property
    def source_event_id(self) -> UUID:
        return self.source_event.id


FALLBACK_TIMEZONES: dict[str, tzinfo] = {
    "UTC": timezone.utc,
    "Etc/UTC": timezone.utc,
    "Asia/Tokyo": timezone(timedelta(hours=9), name="Asia/Tokyo"),
    "JST": timezone(timedelta(hours=9), name="JST"),
}


def get_zoneinfo(name: str | None) -> tzinfo:
    zone_name = (name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(zone_name)
    except Exception:
        return FALLBACK_TIMEZONES.get(zone_name, timezone.utc)


def normalize_utc(value: datetime) -> datetime:
    normalized = ensure_utc(value)
    if normalized is None:
        raise ValueError("datetime is required")
    return normalized


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        return normalize_utc(datetime.fromisoformat(raw))
    except ValueError:
        return None


def parse_iso_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def to_utc_from_local(value: datetime, timezone_name: str) -> datetime:
    if value.tzinfo is not None:
        return normalize_utc(value)
    localized = value.replace(tzinfo=get_zoneinfo(timezone_name))
    return normalize_utc(localized)


def combine_local_date(value: date, timezone_name: str) -> datetime:
    return to_utc_from_local(datetime.combine(value, time.min), timezone_name)


def localize_datetime(value: datetime, timezone_name: str) -> datetime:
    return normalize_utc(value).astimezone(get_zoneinfo(timezone_name))


def local_today(timezone_name: str) -> date:
    return localize_datetime(utc_now(), timezone_name).date()


def list_calendar_contexts(
    session: Session,
    user_id: UUID,
    *,
    include_archived: bool = True,
) -> list[CalendarContext]:
    current_user = session.get(User, user_id)
    user_can_edit = True if current_user is None else current_user.can_edit_calendar
    memberships = session.exec(
        select(CalendarMember).where(CalendarMember.user_id == user_id)
    ).all()
    if not memberships:
        return []

    calendar_ids = [item.calendar_id for item in memberships]
    calendars_stmt = select(Calendar).where(Calendar.id.in_(calendar_ids))
    if not include_archived:
        calendars_stmt = calendars_stmt.where(Calendar.is_archived.is_(False))
    calendars = session.exec(calendars_stmt).all()
    if not calendars:
        return []

    calendar_map = {item.id: item for item in calendars}
    preferences = session.exec(
        select(CalendarUserPreference).where(
            CalendarUserPreference.user_id == user_id,
            CalendarUserPreference.calendar_id.in_(calendar_map.keys()),
        )
    ).all()
    preference_map = {item.calendar_id: item for item in preferences}

    contexts: list[CalendarContext] = []
    for membership in memberships:
        calendar = calendar_map.get(membership.calendar_id)
        if calendar is None:
            continue
        contexts.append(
            CalendarContext(
                calendar=calendar,
                membership=membership,
                preference=preference_map.get(membership.calendar_id),
                user_can_edit=user_can_edit,
            )
        )
    contexts.sort(
        key=lambda item: (
            item.display_order,
            item.calendar.name.lower(),
            str(item.calendar.id),
        )
    )
    return contexts


def get_calendar_context(
    session: Session,
    user_id: UUID,
    calendar_id: UUID,
    *,
    include_archived: bool = True,
) -> CalendarContext | None:
    for context in list_calendar_contexts(session, user_id, include_archived=include_archived):
        if context.calendar.id == calendar_id:
            return context
    return None


def default_create_context(contexts: list[CalendarContext], user: User) -> CalendarContext | None:
    eligible = [item for item in contexts if item.can_create_events and not item.calendar.is_archived]
    if not eligible:
        return None
    if user.default_calendar_id:
        for item in eligible:
            if item.calendar.id == user.default_calendar_id:
                return item
    for item in eligible:
        if item.calendar.is_primary:
            return item
    return eligible[0]


def start_of_week(value: date) -> date:
    return value - timedelta(days=value.weekday())


def shift_anchor_date(mode: str, anchor: date, direction: int) -> date:
    if mode == "day":
        return anchor + timedelta(days=direction)
    if mode == "week":
        return anchor + timedelta(days=7 * direction)

    year = anchor.year
    month = anchor.month + direction
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    last_day = calendar_lib.monthrange(year, month)[1]
    return date(year, month, min(anchor.day, last_day))


def view_window_dates(mode: str, anchor: date) -> tuple[date, date]:
    if mode == "day":
        return anchor, anchor + timedelta(days=1)
    if mode == "week":
        start = start_of_week(anchor)
        return start, start + timedelta(days=7)

    month_start = anchor.replace(day=1)
    grid_start = start_of_week(month_start)
    return grid_start, grid_start + timedelta(days=42)


def view_window_utc(mode: str, anchor: date, timezone_name: str) -> tuple[datetime, datetime]:
    start_date, end_date = view_window_dates(mode, anchor)
    return combine_local_date(start_date, timezone_name), combine_local_date(end_date, timezone_name)


def split_csv_numbers(value: str | None) -> list[int]:
    if not value:
        return []
    result: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.append(int(item))
        except ValueError:
            continue
    return result


def split_csv_weekdays(value: str | None) -> list[int]:
    if not value:
        return []
    result: list[int] = []
    for item in value.split(","):
        token = item.strip().upper()
        if token in WEEKDAY_MAP:
            result.append(WEEKDAY_MAP[token])
    return sorted(set(result))


def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    month_index = (year * 12 + (month - 1)) + delta
    new_year, new_month_index = divmod(month_index, 12)
    return new_year, new_month_index + 1


def clamp_month_day(year: int, month: int, day_value: int) -> date | None:
    if day_value < 1:
        return None
    last_day = calendar_lib.monthrange(year, month)[1]
    if day_value > last_day:
        return None
    return date(year, month, day_value)


def overlaps_range(start_at: datetime, end_at: datetime, range_start: datetime, range_end: datetime) -> bool:
    return start_at < range_end and end_at > range_start


def _candidate_allowed(
    candidate_start: datetime,
    *,
    anchor_start: datetime,
    rule: RecurrenceRule,
    count_so_far: int,
) -> bool:
    if candidate_start < anchor_start:
        return False
    if rule.until_at and candidate_start > normalize_utc(rule.until_at):
        return False
    if rule.count is not None and count_so_far >= rule.count:
        return False
    return True


def generate_series_instances(
    event: Event,
    rule: RecurrenceRule,
    range_start: datetime,
    range_end: datetime,
) -> list[tuple[datetime, datetime, datetime]]:
    timezone_name = rule.timezone or event.timezone
    local_tz = get_zoneinfo(timezone_name)
    local_start = normalize_utc(event.start_at).astimezone(local_tz)
    duration = normalize_utc(event.end_at) - normalize_utc(event.start_at)
    results: list[tuple[datetime, datetime, datetime]] = []
    count_seen = 0

    def maybe_add(candidate_local: datetime) -> bool:
        nonlocal count_seen
        candidate_utc = normalize_utc(candidate_local.astimezone(timezone.utc))
        if not _candidate_allowed(candidate_utc, anchor_start=normalize_utc(event.start_at), rule=rule, count_so_far=count_seen):
            return False
        count_seen += 1
        candidate_end = candidate_utc + duration
        if overlaps_range(candidate_utc, candidate_end, range_start, range_end):
            results.append((candidate_utc, candidate_utc, candidate_end))
        return True

    if rule.freq == RecurrenceFrequency.daily:
        current_local = local_start
        while True:
            candidate_utc = normalize_utc(current_local.astimezone(timezone.utc))
            if candidate_utc >= range_end and (not rule.until_at or candidate_utc > normalize_utc(rule.until_at)):
                break
            if not maybe_add(current_local):
                break
            current_local = current_local + timedelta(days=max(rule.interval, 1))
            if candidate_utc > range_end and not results:
                break
        return results

    if rule.freq == RecurrenceFrequency.weekly:
        weekdays = split_csv_weekdays(rule.by_weekday) or [local_start.weekday()]
        week_start = local_start.date() - timedelta(days=local_start.weekday())
        week_index = 0
        while True:
            current_week = week_start + timedelta(weeks=week_index * max(rule.interval, 1))
            done = False
            for weekday in weekdays:
                current_day = current_week + timedelta(days=weekday)
                candidate_local = datetime.combine(current_day, local_start.timetz().replace(tzinfo=None)).replace(
                    tzinfo=local_tz
                )
                candidate_utc = normalize_utc(candidate_local.astimezone(timezone.utc))
                if candidate_utc >= range_end and (not rule.until_at or candidate_utc > normalize_utc(rule.until_at)):
                    done = True
                    continue
                if not maybe_add(candidate_local):
                    return results
            if done and current_week > localize_datetime(range_end, timezone_name).date():
                break
            week_index += 1
            if week_index > 1040:
                break
        return results

    if rule.freq == RecurrenceFrequency.monthly:
        month_days = split_csv_numbers(rule.by_month_day) or [local_start.day]
        step = 0
        while True:
            year_value, month_value = add_months(local_start.year, local_start.month, step * max(rule.interval, 1))
            generated = False
            for day_value in sorted(set(month_days)):
                current_day = clamp_month_day(year_value, month_value, day_value)
                if current_day is None:
                    continue
                candidate_local = datetime.combine(current_day, local_start.timetz().replace(tzinfo=None)).replace(
                    tzinfo=local_tz
                )
                candidate_utc = normalize_utc(candidate_local.astimezone(timezone.utc))
                if candidate_utc >= range_end and (not rule.until_at or candidate_utc > normalize_utc(rule.until_at)):
                    continue
                generated = True
                if not maybe_add(candidate_local):
                    return results
            if not generated and step > 0 and rule.until_at and datetime(year_value, month_value, 1, tzinfo=local_tz) > localize_datetime(rule.until_at, timezone_name):
                break
            step += 1
            if step > 240:
                break
        return results

    day_values = split_csv_numbers(rule.by_month_day) or [local_start.day]
    step = 0
    while True:
        year_value = local_start.year + step * max(rule.interval, 1)
        generated = False
        for day_value in sorted(set(day_values)):
            current_day = clamp_month_day(year_value, local_start.month, day_value)
            if current_day is None:
                continue
            candidate_local = datetime.combine(current_day, local_start.timetz().replace(tzinfo=None)).replace(
                tzinfo=local_tz
            )
            candidate_utc = normalize_utc(candidate_local.astimezone(timezone.utc))
            if candidate_utc >= range_end and (not rule.until_at or candidate_utc > normalize_utc(rule.until_at)):
                continue
            generated = True
            if not maybe_add(candidate_local):
                return results
        if not generated and step > 0 and rule.until_at and year_value > localize_datetime(rule.until_at, timezone_name).year:
            break
        step += 1
        if step > 120:
            break
    return results


def occurrence_records_for_event(
    event: Event,
    recurrence_rule: RecurrenceRule | None,
    override_map: dict[datetime, EventOverride],
    range_start: datetime,
    range_end: datetime,
) -> list[OccurrenceRecord]:
    if event.is_deleted:
        return []

    if event.kind == EventKind.series_master and recurrence_rule is not None:
        records: list[OccurrenceRecord] = []
        for original_start_at, generated_start_at, generated_end_at in generate_series_instances(
            event,
            recurrence_rule,
            range_start,
            range_end,
        ):
            override = override_map.get(original_start_at)
            if override and override.is_cancelled:
                continue
            start_at = generated_start_at if override is None or override.start_at is None else normalize_utc(override.start_at)
            end_at = generated_end_at if override is None or override.end_at is None else normalize_utc(override.end_at)
            records.append(
                OccurrenceRecord(
                    source_event=event,
                    original_start_at=original_start_at,
                    start_at=start_at,
                    end_at=end_at,
                    title=event.title if override is None or override.title is None else override.title,
                    description=event.description if override is None or override.description is None else override.description,
                    location=event.location if override is None or override.location is None else override.location,
                    timezone=event.timezone if override is None or override.timezone is None else override.timezone,
                    is_all_day=event.is_all_day if override is None or override.is_all_day is None else override.is_all_day,
                    visibility=event.visibility if override is None or override.visibility is None else override.visibility,
                    status=event.status,
                )
            )
        return records

    start_at = normalize_utc(event.start_at)
    end_at = normalize_utc(event.end_at)
    if not overlaps_range(start_at, end_at, range_start, range_end):
        return []
    return [
        OccurrenceRecord(
            source_event=event,
            original_start_at=start_at,
            start_at=start_at,
            end_at=end_at,
            title=event.title,
            description=event.description,
            location=event.location,
            timezone=event.timezone,
            is_all_day=event.is_all_day,
            visibility=event.visibility,
            status=event.status,
        )
    ]


def _permission_flags(
    *,
    user_id: UUID,
    context: CalendarContext,
    record: OccurrenceRecord,
) -> tuple[bool, bool, bool]:
    is_owner = context.membership.role == CalendarMemberRole.owner
    is_editor = context.membership.role == CalendarMemberRole.editor
    is_creator = record.source_event.created_by_user_id == user_id

    if record.visibility == EventVisibility.normal:
        can_view_details = True
    else:
        can_view_details = is_creator

    if record.visibility == EventVisibility.private and not is_creator:
        return can_view_details, False, False

    can_edit = is_owner or is_creator
    if not can_edit and is_editor:
        can_edit = record.visibility == EventVisibility.normal

    return can_view_details, can_edit, can_edit


def list_occurrences(
    session: Session,
    contexts: list[CalendarContext],
    user: User,
    range_start: datetime,
    range_end: datetime,
    *,
    calendar_ids: set[UUID] | None = None,
) -> list[EventOccurrence]:
    allowed_contexts = [
        item
        for item in contexts
        if not item.calendar.is_archived and (calendar_ids is None or item.calendar.id in calendar_ids)
    ]
    if not allowed_contexts:
        return []

    context_map = {item.calendar.id: item for item in allowed_contexts}
    events = session.exec(
        select(Event).where(
            Event.calendar_id.in_(context_map.keys()),
            Event.is_deleted.is_(False),
        )
    ).all()
    if not events:
        return []

    recurrence_ids = [item.recurrence_rule_id for item in events if item.recurrence_rule_id]
    series_ids = [item.id for item in events if item.kind == EventKind.series_master]

    recurrence_map = {}
    if recurrence_ids:
        recurrence_map = {
            item.id: item
            for item in session.exec(select(RecurrenceRule).where(RecurrenceRule.id.in_(recurrence_ids))).all()
        }

    override_group: dict[UUID, dict[datetime, EventOverride]] = {}
    if series_ids:
        for override in session.exec(
            select(EventOverride).where(EventOverride.series_event_id.in_(series_ids))
        ).all():
            group = override_group.setdefault(override.series_event_id, {})
            group[normalize_utc(override.original_start_at)] = override

    occurrences: list[EventOccurrence] = []
    for event in events:
        context = context_map.get(event.calendar_id)
        if context is None:
            continue
        records = occurrence_records_for_event(
            event,
            recurrence_map.get(event.recurrence_rule_id) if event.recurrence_rule_id else None,
            override_group.get(event.id, {}),
            range_start,
            range_end,
        )
        for record in records:
            can_view_details, can_edit, can_delete = _permission_flags(
                user_id=user.id,
                context=context,
                record=record,
            )
            occurrences.append(
                EventOccurrence(
                    calendar=context.calendar,
                    membership_role=context.membership.role,
                    source_event=event,
                    original_start_at=record.original_start_at,
                    start_at=record.start_at,
                    end_at=record.end_at,
                    title=record.title,
                    description=record.description,
                    location=record.location,
                    timezone=record.timezone,
                    is_all_day=record.is_all_day,
                    visibility=record.visibility,
                    status=record.status,
                    can_view_details=can_view_details,
                    can_edit=can_edit,
                    can_delete=can_delete,
                )
            )

    occurrences.sort(key=lambda item: (item.start_at, item.display_title.lower(), str(item.source_event_id)))
    return occurrences


def find_occurrence(
    session: Session,
    context: CalendarContext,
    user: User,
    event: Event,
    original_start_at: datetime | None,
) -> EventOccurrence | None:
    if event.kind != EventKind.series_master:
        record = occurrence_records_for_event(event, None, {}, normalize_utc(event.start_at) - timedelta(seconds=1), normalize_utc(event.end_at) + timedelta(seconds=1))
        if not record:
            return None
        record_item = record[0]
        flags = _permission_flags(user_id=user.id, context=context, record=record_item)
        return EventOccurrence(
            calendar=context.calendar,
            membership_role=context.membership.role,
            source_event=event,
            original_start_at=record_item.original_start_at,
            start_at=record_item.start_at,
            end_at=record_item.end_at,
            title=record_item.title,
            description=record_item.description,
            location=record_item.location,
            timezone=record_item.timezone,
            is_all_day=record_item.is_all_day,
            visibility=record_item.visibility,
            status=record_item.status,
            can_view_details=flags[0],
            can_edit=flags[1],
            can_delete=flags[2],
        )

    if original_start_at is None:
        return None

    recurrence_rule = session.get(RecurrenceRule, event.recurrence_rule_id) if event.recurrence_rule_id else None
    if recurrence_rule is None:
        return None
    override_map = {
        normalize_utc(item.original_start_at): item
        for item in session.exec(
            select(EventOverride).where(EventOverride.series_event_id == event.id)
        ).all()
    }
    records = occurrence_records_for_event(
        event,
        recurrence_rule,
        override_map,
        original_start_at,
        original_start_at + timedelta(seconds=1),
    )
    for record_item in records:
        if record_item.original_start_at != original_start_at:
            continue
        flags = _permission_flags(user_id=user.id, context=context, record=record_item)
        return EventOccurrence(
            calendar=context.calendar,
            membership_role=context.membership.role,
            source_event=event,
            original_start_at=record_item.original_start_at,
            start_at=record_item.start_at,
            end_at=record_item.end_at,
            title=record_item.title,
            description=record_item.description,
            location=record_item.location,
            timezone=record_item.timezone,
            is_all_day=record_item.is_all_day,
            visibility=record_item.visibility,
            status=record_item.status,
            can_view_details=flags[0],
            can_edit=flags[1],
            can_delete=flags[2],
        )
    return None


def format_datetime_local(value: datetime, timezone_name: str, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return localize_datetime(value, timezone_name).strftime(fmt)


def format_date_local(value: datetime, timezone_name: str, fmt: str = "%Y-%m-%d") -> str:
    return localize_datetime(value, timezone_name).strftime(fmt)


def format_time_local(value: datetime, timezone_name: str, fmt: str = "%H:%M") -> str:
    return localize_datetime(value, timezone_name).strftime(fmt)


def ensure_calendar_user_preferences(
    session: Session,
    *,
    calendar_id: UUID,
    user_id: UUID,
    is_visible: bool = True,
    display_order: int = 0,
) -> CalendarUserPreference:
    preference = session.exec(
        select(CalendarUserPreference).where(
            CalendarUserPreference.calendar_id == calendar_id,
            CalendarUserPreference.user_id == user_id,
        )
    ).first()
    if preference is None:
        preference = CalendarUserPreference(
            calendar_id=calendar_id,
            user_id=user_id,
            is_visible=is_visible,
            display_order=display_order,
        )
        session.add(preference)
        session.flush()
    return preference


def update_default_calendar_if_needed(session: Session, user: User, contexts: list[CalendarContext]) -> None:
    target = default_create_context(contexts, user)
    if target and user.default_calendar_id != target.calendar.id:
        user.default_calendar_id = target.calendar.id
        user.updated_at = utc_now()
        session.add(user)
        session.flush()


def search_occurrences(
    session: Session,
    contexts: list[CalendarContext],
    user: User,
    *,
    query: str,
    range_start: datetime,
    range_end: datetime,
    calendar_ids: set[UUID] | None = None,
) -> list[EventOccurrence]:
    needle = (query or "").strip().lower()
    if not needle:
        return []
    results: list[EventOccurrence] = []
    for occurrence in list_occurrences(session, contexts, user, range_start, range_end, calendar_ids=calendar_ids):
        if not occurrence.can_view_details:
            continue
        haystack = " ".join(
            [
                occurrence.title or "",
                occurrence.description or "",
                occurrence.location or "",
            ]
        ).lower()
        if needle in haystack:
            results.append(occurrence)
    return results


def active_reminders_for_event(session: Session, event_id: UUID) -> list[Reminder]:
    return session.exec(
        select(Reminder).where(
            Reminder.event_id == event_id,
            Reminder.is_deleted.is_(False),
        )
    ).all()


def sync_event_reminders(
    session: Session,
    *,
    event: Event,
    user_id: UUID,
    minutes_before_values: list[int],
) -> list[Reminder]:
    cleaned_values = sorted({value for value in minutes_before_values if value > 0})
    existing = session.exec(
        select(Reminder).where(
            Reminder.event_id == event.id,
            Reminder.user_id == user_id,
            Reminder.method == ReminderMethod.in_app,
        )
    ).all()
    existing_map = {item.minutes_before: item for item in existing}

    active: list[Reminder] = []
    for value in cleaned_values:
        reminder = existing_map.get(value)
        if reminder is None:
            reminder = Reminder(
                event_id=event.id,
                user_id=user_id,
                method=ReminderMethod.in_app,
                minutes_before=value,
                is_deleted=False,
            )
            session.add(reminder)
            session.flush()
        elif reminder.is_deleted:
            reminder.is_deleted = False
            reminder.updated_at = utc_now()
            session.add(reminder)
            session.flush()
        active.append(reminder)

    for reminder in existing:
        if reminder.minutes_before in cleaned_values:
            continue
        reminder.is_deleted = True
        reminder.updated_at = utc_now()
        session.add(reminder)
        for job in session.exec(select(NotificationJob).where(NotificationJob.reminder_id == reminder.id)).all():
            if job.status != NotificationJobStatus.sent:
                job.status = NotificationJobStatus.cancelled
                job.updated_at = utc_now()
                session.add(job)
    return active


def _raw_occurrences_for_notifications(
    session: Session,
    event: Event,
    range_start: datetime,
    range_end: datetime,
) -> list[OccurrenceRecord]:
    recurrence_rule = session.get(RecurrenceRule, event.recurrence_rule_id) if event.recurrence_rule_id else None
    override_map = {
        normalize_utc(item.original_start_at): item
        for item in session.exec(select(EventOverride).where(EventOverride.series_event_id == event.id)).all()
    }
    return occurrence_records_for_event(event, recurrence_rule, override_map, range_start, range_end)


def rebuild_notification_jobs_for_event(session: Session, event: Event, *, calendar: Calendar | None = None) -> None:
    reminders = active_reminders_for_event(session, event.id)
    now = utc_now()
    jobs = session.exec(select(NotificationJob).where(NotificationJob.source_event_id == event.id)).all()
    job_map = {(item.reminder_id, normalize_utc(item.original_start_at)): item for item in jobs}
    valid_keys: set[tuple[UUID, datetime]] = set()

    if event.is_deleted or event.status == EventLifecycleStatus.cancelled or (calendar and calendar.is_archived):
        for job in jobs:
            if job.status != NotificationJobStatus.sent:
                job.status = NotificationJobStatus.cancelled
                job.updated_at = now
                session.add(job)
        return

    window_end = now + timedelta(days=NOTIFICATION_WINDOW_DAYS)
    occurrences = _raw_occurrences_for_notifications(session, event, now - timedelta(minutes=1), window_end)
    for reminder in reminders:
        for occurrence in occurrences:
            scheduled_at = occurrence.start_at - timedelta(minutes=reminder.minutes_before)
            if scheduled_at <= now:
                continue
            key = (reminder.id, occurrence.original_start_at)
            valid_keys.add(key)
            job = job_map.get(key)
            if job is None:
                job = NotificationJob(
                    reminder_id=reminder.id,
                    user_id=reminder.user_id,
                    source_event_id=event.id,
                    original_start_at=occurrence.original_start_at,
                    occurrence_start_at=occurrence.start_at,
                    scheduled_at=scheduled_at,
                    status=NotificationJobStatus.pending,
                )
            else:
                job.user_id = reminder.user_id
                job.occurrence_start_at = occurrence.start_at
                job.scheduled_at = scheduled_at
                if job.status != NotificationJobStatus.sent:
                    job.status = NotificationJobStatus.pending
                job.updated_at = now
            session.add(job)

    for key, job in job_map.items():
        if key in valid_keys or job.status == NotificationJobStatus.sent:
            continue
        job.status = NotificationJobStatus.cancelled
        job.updated_at = now
        session.add(job)
