from __future__ import annotations

import calendar as month_calendar
import random
import uuid
from datetime import date, datetime, time, timedelta

from sqlmodel import Session, select

from extended_care_fee_service import recalculate_period
from models import (
    AttendanceAlarmHistory,
    AttendanceAlarmState,
    AttendanceRecord,
    AttendanceVerification,
    AttendanceVerificationHistory,
    AttendanceVerificationStatus,
    Calendar,
    CalendarType,
    Child,
    ChildStatus,
    DailyContactEntry,
    Event,
    EventKind,
    EventLifecycleStatus,
    EventVisibility,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentContactType,
)
from time_utils import local_today


DEMO_EVENT_MARKER = "[デモ自動生成]"
DEFAULT_RANDOM_SEED = 20260727

EVENT_SPECS = (
    ("避難訓練", "園庭", 40),
    ("職員会議", "職員室", 60),
    ("給食会議", "会議室", 60),
    ("保育カンファレンス", "会議室", 45),
    ("園内研修", "遊戯室", 90),
    ("保護者面談", "相談室", 45),
    ("身体測定", "各保育室", 90),
    ("誕生会", "遊戯室", 60),
    ("安全点検", "園内", 60),
    ("行事準備", "遊戯室", 75),
)


def add_months(value: date, months: int) -> date:
    """Return value shifted by months, clipping the day at month end."""

    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, month_calendar.monthrange(year, month)[1])
    return date(year, month, day)


def demo_calendar_range(reference_date: date) -> tuple[date, date]:
    """Five complete calendar months: two before through two after today."""

    start = add_months(reference_date.replace(day=1), -2)
    end = add_months(reference_date.replace(day=1), 3) - timedelta(days=1)
    return start, end


def demo_attendance_range(reference_date: date) -> tuple[date, date]:
    """The date three months before today through today, inclusive."""

    return add_months(reference_date, -3), reference_date


def _weekdays(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _month_starts(start: date, end: date) -> list[date]:
    months: list[date] = []
    current = start.replace(day=1)
    while current <= end:
        months.append(current)
        current = add_months(current, 1)
    return months


def _seed_calendar_events(
    session: Session,
    *,
    reference_date: date,
    random_seed: int,
) -> int:
    start, end = demo_calendar_range(reference_date)
    calendars = session.exec(
        select(Calendar).where(Calendar.is_archived.is_(False))
    ).all()
    if not calendars:
        return 0

    calendars.sort(
        key=lambda item: (
            item.calendar_type != CalendarType.facility_shared,
            item.name,
            str(item.id),
        )
    )

    # Only generated events are pruned as the five-month display window moves.
    generated_events = session.exec(
        select(Event).where(Event.description.startswith(DEMO_EVENT_MARKER))
    ).all()
    for event in generated_events:
        if event.start_at.date() < start or event.start_at.date() > end:
            session.delete(event)

    created = 0
    for month_start in _month_starts(start, end):
        month_end = add_months(month_start, 1) - timedelta(days=1)
        weekdays = _weekdays(month_start, month_end)
        rng = random.Random(f"{random_seed}:calendar:{month_start.isoformat()}")
        event_days = sorted(rng.sample(weekdays, k=min(6, len(weekdays))))
        for index, event_day in enumerate(event_days):
            title, location, duration_minutes = EVENT_SPECS[
                rng.randrange(len(EVENT_SPECS))
            ]
            calendar = calendars[rng.randrange(min(len(calendars), 4))]
            start_hour = rng.choice((9, 10, 13, 14, 15, 16))
            start_minute = rng.choice((0, 0, 0, 30))
            start_at = datetime.combine(event_day, time(start_hour, start_minute))
            event_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                (
                    "open-hoikuict/demo-event/"
                    f"{random_seed}/{calendar.id}/{event_day.isoformat()}/{index}"
                ),
            )
            if session.get(Event, event_id) is not None:
                continue
            session.add(
                Event(
                    id=event_id,
                    calendar_id=calendar.id,
                    created_by_user_id=calendar.owner_user_id,
                    kind=EventKind.single,
                    title=title,
                    description=f"{DEMO_EVENT_MARKER} 画面確認用の架空の予定です。",
                    location=location,
                    start_at=start_at,
                    end_at=start_at + timedelta(minutes=duration_minutes),
                    timezone="Asia/Tokyo",
                    is_all_day=False,
                    visibility=EventVisibility.normal,
                    status=EventLifecycleStatus.confirmed,
                )
            )
            created += 1
    return created


def _attendance_status(rng: random.Random) -> AttendanceVerificationStatus:
    roll = rng.random()
    if roll < 0.91:
        return AttendanceVerificationStatus.present
    if roll < 0.95:
        return AttendanceVerificationStatus.sick_absent
    if roll < 0.985:
        return AttendanceVerificationStatus.private_absent
    return AttendanceVerificationStatus.unknown


def _seed_attendance(
    session: Session,
    *,
    reference_date: date,
    random_seed: int,
) -> dict[str, int]:
    start, end = demo_attendance_range(reference_date)
    service_days = _weekdays(start, end)
    if reference_date not in service_days:
        service_days.append(reference_date)
    children = session.exec(
        select(Child)
        .where(Child.status == ChildStatus.enrolled)
        .order_by(Child.id)
    ).all()

    existing_record_keys = {
        (row.child_id, row.attendance_date)
        for row in session.exec(
            select(AttendanceRecord).where(
                AttendanceRecord.attendance_date >= start,
                AttendanceRecord.attendance_date <= end,
            )
        ).all()
    }
    existing_verifications = {
        (row.child_id, row.target_date): row.status
        for row in session.exec(
            select(AttendanceVerification).where(
                AttendanceVerification.target_date >= start,
                AttendanceVerification.target_date <= end,
            )
        ).all()
    }
    existing_history_keys = {
        (row.child_id, row.target_date)
        for row in session.exec(
            select(AttendanceVerificationHistory).where(
                AttendanceVerificationHistory.target_date >= start,
                AttendanceVerificationHistory.target_date <= end,
            )
        ).all()
    }
    existing_alarm_keys = {
        (row.child_id, row.target_date)
        for row in session.exec(
            select(AttendanceAlarmState).where(
                AttendanceAlarmState.target_date >= start,
                AttendanceAlarmState.target_date <= end,
            )
        ).all()
    }
    existing_alarm_history_keys = {
        (row.child_id, row.target_date)
        for row in session.exec(
            select(AttendanceAlarmHistory).where(
                AttendanceAlarmHistory.target_date >= start,
                AttendanceAlarmHistory.target_date <= end,
            )
        ).all()
    }

    counts = {
        "attendance_records": 0,
        "attendance_verifications": 0,
        "attendance_verification_histories": 0,
        "attendance_alarm_states": 0,
        "attendance_alarm_histories": 0,
    }
    pickup_people = ("母", "父", "祖母", "祖父", "保護者")
    notes = (None, None, None, None, "少し早めのお迎え予定。", "帰宅後に受診予定。")

    for child in children:
        if child.id is None:
            continue
        for service_day in service_days:
            if child.enrollment_date and service_day < child.enrollment_date:
                continue
            if child.withdrawal_date and service_day > child.withdrawal_date:
                continue

            key = (child.id, service_day)
            rng = random.Random(
                f"{random_seed}:attendance:{child.id}:{service_day.isoformat()}"
            )
            status = existing_verifications.get(key, _attendance_status(rng))
            if key in existing_record_keys and key not in existing_verifications:
                status = AttendanceVerificationStatus.present
            audit_at = datetime.combine(service_day, time(9, 45))

            if key not in existing_verifications:
                session.add(
                    AttendanceVerification(
                        child_id=child.id,
                        target_date=service_day,
                        status=status,
                        updated_by_name=rng.choice(("担任A", "担任B", "主任", "園長")),
                        created_at=audit_at - timedelta(minutes=15),
                        updated_at=audit_at,
                    )
                )
                counts["attendance_verifications"] += 1
            if key not in existing_history_keys:
                session.add(
                    AttendanceVerificationHistory(
                        child_id=child.id,
                        target_date=service_day,
                        status=status,
                        updated_by_name=rng.choice(("担任A", "担任B", "主任", "園長")),
                        created_at=audit_at,
                    )
                )
                counts["attendance_verification_histories"] += 1

            if status == AttendanceVerificationStatus.unknown:
                evaluated_at = datetime.combine(service_day, time(9, 50))
                reasons = ["no_contact_and_not_present"]
                if key not in existing_alarm_keys:
                    session.add(
                        AttendanceAlarmState(
                            child_id=child.id,
                            target_date=service_day,
                            is_active=True,
                            reasons=reasons,
                            evaluated_at=evaluated_at,
                            created_at=evaluated_at,
                            updated_at=evaluated_at,
                        )
                    )
                    counts["attendance_alarm_states"] += 1
                if key not in existing_alarm_history_keys:
                    session.add(
                        AttendanceAlarmHistory(
                            child_id=child.id,
                            target_date=service_day,
                            is_active=True,
                            reasons=reasons,
                            evaluated_at=evaluated_at,
                            created_at=evaluated_at,
                        )
                    )
                    counts["attendance_alarm_histories"] += 1

            if status != AttendanceVerificationStatus.present or key in existing_record_keys:
                continue

            check_in_minutes = rng.randint(7 * 60 + 20, 9 * 60 + 15)
            check_out_minutes = rng.randint(16 * 60, 18 * 60 + 45)
            check_in_at = datetime.combine(service_day, time()) + timedelta(
                minutes=check_in_minutes
            )
            check_out_at = datetime.combine(service_day, time()) + timedelta(
                minutes=check_out_minutes
            )
            # A small number of records intentionally remain checked in for UI checks.
            actual_check_out = None if rng.random() < 0.018 else check_out_at
            session.add(
                AttendanceRecord(
                    child_id=child.id,
                    attendance_date=service_day,
                    check_in_at=check_in_at,
                    check_out_at=actual_check_out,
                    planned_pickup_time=check_out_at.strftime("%H:%M"),
                    pickup_person=rng.choice(pickup_people),
                    snack_required=check_out_minutes >= 18 * 60,
                    note=rng.choice(notes),
                    created_at=datetime.combine(service_day, time(7, 0)),
                    updated_at=actual_check_out or check_in_at,
                )
            )
            counts["attendance_records"] += 1

    return counts


def _seed_daily_contacts(
    session: Session,
    *,
    reference_date: date,
    random_seed: int,
) -> int:
    start, end = demo_attendance_range(reference_date)
    valid_parent_account_ids = set(
        session.exec(
            select(ParentAccount.id).where(
                ParentAccount.status == ParentAccountStatus.active
            )
        ).all()
    )
    links = session.exec(
        select(ParentChildLink).order_by(
            ParentChildLink.is_primary_contact.desc(),
            ParentChildLink.id,
        )
    ).all()
    parent_account_by_child_id: dict[int, int] = {}
    for link in links:
        if link.parent_account_id not in valid_parent_account_ids:
            continue
        parent_account_by_child_id.setdefault(link.child_id, link.parent_account_id)

    existing_entries = {
        (row.child_id, row.target_date): row
        for row in session.exec(
            select(DailyContactEntry).where(
                DailyContactEntry.target_date >= start,
                DailyContactEntry.target_date <= end,
            )
        ).all()
    }
    verifications = session.exec(
        select(AttendanceVerification).where(
            AttendanceVerification.target_date >= start,
            AttendanceVerification.target_date <= end,
        )
    ).all()

    sleep_notes = ("20:30-6:20", "21:00-6:40", "21:30-7:00", "22:00-6:30")
    breakfast_statuses = ("完食", "普通", "普通", "少なめ")
    bowel_statuses = ("あり", "あり", "なし", "軟便")
    moods = ("元気", "元気", "落ち着いている", "少し眠そう", "甘えたい様子")
    condition_notes = (
        "朝から元気です。",
        "昨夜もよく眠れました。",
        "少し眠そうですが、体調は変わりありません。",
        "食欲もあり、普段通りです。",
    )
    contact_notes = (
        "本日は通常通りのお迎えです。",
        "祖母がお迎え予定です。",
        "夕方の体調を見てください。",
        "連絡帳を確認しました。",
        "少し早めにお迎えに行きます。",
    )
    sick_symptoms = ("発熱", "咳・鼻水", "嘔吐", "腹痛", "倦怠感")
    diagnoses = (None, None, "風邪", "胃腸炎", "受診予定")
    private_notes = ("家庭の都合でお休みします。", "通院のためお休みします。", "家族行事のため欠席します。")

    created = 0
    for verification in verifications:
        key = (verification.child_id, verification.target_date)
        parent_account_id = parent_account_by_child_id.get(verification.child_id)
        if parent_account_id is None:
            continue

        rng = random.Random(
            f"{random_seed}:daily-contact:{verification.child_id}:"
            f"{verification.target_date.isoformat()}"
        )
        # Keep a few blank rows visible in the staff submission-status screen.
        submission_rate = 0.97 if verification.status.is_absent else 0.94
        should_submit = verification.status != AttendanceVerificationStatus.unknown
        if verification.target_date == reference_date:
            should_submit = should_submit and verification.child_id % 16 != 0
        else:
            should_submit = should_submit and rng.random() <= submission_rate

        existing_entry = existing_entries.get(key)
        if not should_submit:
            if (
                existing_entry is not None
                and isinstance(existing_entry.extra_data, dict)
                and existing_entry.extra_data.get("generated") == "rolling"
            ):
                session.delete(existing_entry)
            continue
        if existing_entry is not None:
            continue

        submitted_at = datetime.combine(verification.target_date, time(6, 0)) + timedelta(
            minutes=rng.randint(0, 165)
        )
        common_values = {
            "child_id": verification.child_id,
            "parent_account_id": parent_account_id,
            "target_date": verification.target_date,
            "extra_data": {
                "demo": True,
                "channel": "parent_portal",
                "generated": "rolling",
            },
            "submitted_at": submitted_at,
            "created_at": submitted_at,
            "updated_at": submitted_at,
        }

        if verification.status == AttendanceVerificationStatus.sick_absent:
            session.add(
                DailyContactEntry(
                    **common_values,
                    contact_type=ParentContactType.absent_sick,
                    absence_temperature=f"{rng.uniform(37.3, 39.1):.1f}",
                    absence_symptoms=rng.choice(sick_symptoms),
                    absence_diagnosis=rng.choice(diagnoses),
                    absence_note="自宅で様子を見ます。",
                )
            )
        elif verification.status == AttendanceVerificationStatus.private_absent:
            session.add(
                DailyContactEntry(
                    **common_values,
                    contact_type=ParentContactType.absent_private,
                    absence_note=rng.choice(private_notes),
                )
            )
        else:
            has_minor_symptom = rng.random() < 0.14
            session.add(
                DailyContactEntry(
                    **common_values,
                    contact_type=ParentContactType.present,
                    temperature=f"{rng.uniform(36.2, 37.2):.1f}",
                    sleep_notes=rng.choice(sleep_notes),
                    breakfast_status=rng.choice(breakfast_statuses),
                    bowel_movement_status=rng.choice(bowel_statuses),
                    mood=rng.choice(moods),
                    cough="少し" if has_minor_symptom and rng.random() < 0.5 else "なし",
                    runny_nose="少し" if has_minor_symptom else "なし",
                    medication="なし",
                    condition_note=rng.choice(condition_notes),
                    contact_note=rng.choice(contact_notes),
                )
            )
        created += 1
    return created


def seed_dynamic_demo_data(
    session: Session,
    *,
    reference_date: date | None = None,
    random_seed: int = DEFAULT_RANDOM_SEED,
    recalculate_extended_care: bool = True,
) -> dict[str, int]:
    """Seed rolling, deterministic demo data for local debug and public demos."""

    reference_date = reference_date or local_today()
    counts = _seed_attendance(
        session,
        reference_date=reference_date,
        random_seed=random_seed,
    )
    session.flush()
    counts["daily_contact_entries"] = _seed_daily_contacts(
        session,
        reference_date=reference_date,
        random_seed=random_seed,
    )
    counts["events"] = _seed_calendar_events(
        session,
        reference_date=reference_date,
        random_seed=random_seed,
    )
    session.flush()

    if recalculate_extended_care:
        start, end = demo_attendance_range(reference_date)
        counts["extended_care_charges"] = recalculate_period(
            session,
            start,
            end,
            include_locked=False,
        )
    return counts
