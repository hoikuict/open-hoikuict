from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import inspect, text
from sqlmodel import SQLModel, Session, select

from child_profile_changes import build_child_profile_change_details, resolve_child_profile_change_payload
from child_profile_history import ensure_initial_child_profile_history
from database import create_db_and_tables, engine
from demo_data_generation import demo_attendance_range, seed_dynamic_demo_data
from extended_care_fee_service import recalculate_period
from models import (
    AttendanceAlarmHistory, AttendanceAlarmState, AttendanceRecord,
    AttendanceVerification, AttendanceVerificationHistory, Calendar,
    CalendarMember, CalendarUserPreference, Child, ChildAllergy, DailyContactEntry,
    ChildHealthProfile, ChildProfileChangeRequest, Classroom, Event,
    ExtendedCareCharge, ExtendedCareChargeStatus, ExtendedCareFeeRule,
    Family, Guardian, HealthCheckRecord, Message, Notice, NoticeRead,
    NoticeTarget, ParentAccount, ParentChildLink, ProfileChangeNotification,
    Survey, SurveyAnswer, SurveyQuestion, SurveyQuestionOption,
    SurveyResponse, SurveyTarget, User,
    USER_SOURCE_WEB_DEMO,
)
from time_utils import local_today

BASE_DIR = Path(__file__).resolve().parents[1]
CSV_DIR = BASE_DIR / "demo_data" / "full"
MAX_DUPLICATE_NAME_GROUPS = 2

MODEL_ORDER = [
    ("classrooms", Classroom),
    ("families", Family),
    ("children", Child),
    ("guardians", Guardian),
    ("parent_accounts", ParentAccount),
    ("parent_child_links", ParentChildLink),
    ("child_health_profiles", ChildHealthProfile),
    ("child_allergies", ChildAllergy),
    ("health_check_records", HealthCheckRecord),
    ("users", User),
    ("calendars", Calendar),
    ("calendar_members", CalendarMember),
    ("calendar_user_preferences", CalendarUserPreference),
    ("events", Event),
    ("daily_contact_entries", DailyContactEntry),
    ("attendance_records", AttendanceRecord),
    ("attendance_verifications", AttendanceVerification),
    ("attendance_verification_histories", AttendanceVerificationHistory),
    ("attendance_alarm_states", AttendanceAlarmState),
    ("attendance_alarm_histories", AttendanceAlarmHistory),
    ("notices", Notice),
    ("notice_targets", NoticeTarget),
    ("notice_reads", NoticeRead),
    ("messages", Message),
    ("surveys", Survey),
    ("survey_targets", SurveyTarget),
    ("survey_questions", SurveyQuestion),
    ("survey_question_options", SurveyQuestionOption),
    ("survey_answers", SurveyAnswer),
    ("survey_responses", SurveyResponse),
    ("profile_change_notifications", ProfileChangeNotification),
    ("child_profile_change_requests", ChildProfileChangeRequest),
]

# These tables are generated relative to the seed execution date instead of
# loading the fixed dates kept in the reference CSV set.
DYNAMIC_DEMO_TABLES = {
    "events",
    "daily_contact_entries",
    "attendance_records",
    "attendance_verifications",
    "attendance_verification_histories",
    "attendance_alarm_states",
    "attendance_alarm_histories",
}

DATE_FIELDS = {
    "birth_date", "enrollment_date", "withdrawal_date", "target_date", "attendance_date",
    "diagnosis_date", "source_document_date", "valid_until", "checked_at", "value_date",
    "effective_from", "effective_to",
}
DATETIME_FIELDS = {
    "created_at", "updated_at", "invited_at", "last_login_at", "submitted_at", "reviewed_at",
    "read_at", "publish_start_at", "publish_end_at", "check_in_at", "check_out_at", "evaluated_at",
    "opens_at", "closes_at", "start_at", "end_at", "submitted_at", "split_from_original_start_at",
    "charge_start_at", "actual_check_out_at", "confirmed_at",
}
UUID_FIELDS = {
    "id", "default_calendar_id", "owner_user_id", "calendar_id", "user_id", "actor_user_id",
    "created_by_user_id", "recurrence_rule_id", "split_from_event_id", "staff_user_id",
    "created_by_staff_user_id", "submitted_by_staff_user_id",
}
JSON_FIELDS = {
    "shared_profile", "extra_data", "reasons", "change_details", "request_data", "value_option_ids",
}
BOOL_FIELDS = {
    "is_primary_contact", "diagnosis_confirmed", "removal_required", "is_active", "requires_medical_care",
    "epipen_required", "sids_risk_flag", "has_allergy", "has_epipen", "has_anaphylaxis",
    "has_febrile_seizure", "has_nursemaids_elbow", "has_medication", "breastfed",
    "requires_followup", "is_calendar_admin", "can_manage_child_records",
    "can_manage_billing_accounts",
    "is_primary", "is_archived", "is_visible", "is_all_day", "is_deleted", "is_read",
    "is_required", "value_bool",
}
INT_FIELDS = {
    "id", "display_order", "child_id", "classroom_id", "family_id", "older_sibling_id", "order",
    "parent_account_id", "parent_child_link_id", "notice_id", "survey_id", "question_id", "answer_id",
    "created_by_parent_account_id", "submitted_by_parent_account_id", "staff_sort_order", "heart_rate",
    "respiratory_rate", "created_count", "updated_count", "skipped_count", "error_count", "room_id",
    "parent_message_id", "value_scale", "display_order", "attendance_record_id", "rule_id",
    "grace_minutes", "rounding_minutes", "unit_price", "daily_cap_amount", "extended_minutes",
    "billable_units", "auto_amount", "adjustment_amount", "final_amount",
}
FLOAT_FIELDS = {"height_cm", "weight_kg", "head_circumference_cm", "chest_circumference_cm"}
GUARDIAN_PROFILE_FIELDS = (
    "order",
    "last_name",
    "first_name",
    "last_name_kana",
    "first_name_kana",
    "relationship",
    "phone",
    "workplace",
    "workplace_address",
    "workplace_phone",
)

# Fields named id in UUID models must parse as UUID, not int.
UUID_MODEL_TABLES = {
    "users", "calendars", "calendar_members", "calendar_user_preferences", "events",
}

def parse_value(table: str, key: str, value: str) -> Any:
    if value == "":
        return None
    if key in JSON_FIELDS:
        return json.loads(value)
    if key in DATE_FIELDS:
        return date.fromisoformat(value)
    if key in DATETIME_FIELDS:
        return datetime.fromisoformat(value)
    if key in BOOL_FIELDS:
        return value.lower() in {"true", "1", "yes", "y", "はい", "有", "あり"}
    if key in UUID_FIELDS and (key != "id" or table in UUID_MODEL_TABLES):
        return UUID(value)
    if key in INT_FIELDS:
        try:
            return int(value)
        except ValueError:
            return value
    if key == "temperature" and table == "health_check_records":
        return float(value)
    if key in FLOAT_FIELDS:
        return float(value)
    return value


def validate_name_duplicates(table: str, rows: list[dict[str, Any]]) -> None:
    """Keep accidental duplicate people names out of the bundled demo data."""

    if table == "children":
        names = [f"{row['last_name']} {row['first_name']}" for row in rows]
    elif table == "parent_accounts":
        names = [str(row["display_name"]).strip() for row in rows]
    else:
        return

    duplicate_counts = {
        name: count for name, count in Counter(names).items() if count > 1
    }
    over_repeated = {
        name: count for name, count in duplicate_counts.items() if count > 2
    }
    if over_repeated or len(duplicate_counts) > MAX_DUPLICATE_NAME_GROUPS:
        details = ", ".join(
            f"{name} ({count}人)" for name, count in sorted(duplicate_counts.items())
        )
        raise ValueError(
            f"{table} の同姓同名は最大{MAX_DUPLICATE_NAME_GROUPS}組、"
            f"各2人までです: {details}"
        )

def load_rows(table: str) -> list[dict[str, Any]]:
    path = CSV_DIR / f"{table}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [
            {key: parse_value(table, key, value) for key, value in row.items() if value != ""}
            for row in reader
        ]
    validate_name_duplicates(table, rows)
    return rows


def build_family_guardian_profiles() -> dict[int, list[dict[str, Any]]]:
    """Build canonical family profiles from guardian rows, deduplicating siblings."""

    family_id_by_child_id = {
        row["id"]: row["family_id"] for row in load_rows("children")
    }
    profiles_by_family: dict[int, list[dict[str, Any]]] = {}
    seen_identities_by_family: dict[int, set[tuple[Any, ...]]] = {}
    for guardian in load_rows("guardians"):
        family_id = family_id_by_child_id[guardian["child_id"]]
        phone = str(guardian.get("phone", "")).strip()
        identity = (
            ("phone", phone)
            if phone
            else tuple(guardian.get(field) for field in GUARDIAN_PROFILE_FIELDS)
        )
        seen_identities = seen_identities_by_family.setdefault(family_id, set())
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        profiles_by_family.setdefault(family_id, []).append(
            {
                field: guardian.get(field, "")
                for field in GUARDIAN_PROFILE_FIELDS
            }
        )

    for profiles in profiles_by_family.values():
        profiles.sort(key=lambda profile: int(profile.get("order", 99)))
    return profiles_by_family

def wipe_all(session: Session) -> None:
    # --wipe-all is intended to rebuild a disposable local/demo database.  Use
    # every table actually present in SQLite so newly added or legacy dependent
    # tables cannot be left pointing at rows replaced by the seed.
    session.exec(text("PRAGMA foreign_keys=OFF"))
    table_names = inspect(session.get_bind()).get_table_names()
    for table_name in reversed(table_names):
        quoted_name = table_name.replace('"', '""')
        session.exec(text(f'DELETE FROM "{quoted_name}"'))
    session.commit()
    session.exec(text("PRAGMA foreign_keys=ON"))


def seed_extended_care_demo_data(
    session: Session,
    *,
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    rule = ExtendedCareFeeRule(
        id=1,
        name="標準延長保育料（デモ）",
        effective_from=start_date,
        start_time="18:00",
        grace_minutes=5,
        rounding_minutes=15,
        unit_price=100,
        daily_cap_amount=None,
        is_active=True,
        created_at=datetime.combine(start_date, datetime.min.time()).replace(hour=9),
        updated_at=datetime.combine(start_date, datetime.min.time()).replace(hour=9),
    )
    session.add(rule)
    session.flush()

    recalculate_period(
        session,
        start_date,
        end_date,
        include_locked=True,
    )
    session.flush()

    charges = session.exec(select(ExtendedCareCharge)).all()
    for charge in charges:
        if charge.auto_amount <= 0:
            continue

        confirmed_at = (charge.actual_check_out_at or charge.charge_start_at) + timedelta(minutes=8)
        if charge.attendance_record_id % 29 == 0:
            charge.status = ExtendedCareChargeStatus.excluded
            charge.adjustment_amount = -charge.auto_amount
            charge.final_amount = 0
            charge.adjustment_reason = "デモ対象外: 園判断"
            charge.confirmed_by = "園長"
            charge.confirmed_at = confirmed_at + timedelta(minutes=4)
        elif charge.attendance_record_id % 17 == 0:
            charge.status = ExtendedCareChargeStatus.manual_adjusted
            charge.adjustment_amount = 50
            charge.final_amount = charge.auto_amount + charge.adjustment_amount
            charge.adjustment_reason = "デモ調整: 連絡確認済み"
            charge.confirmed_by = "事務"
            charge.confirmed_at = confirmed_at + timedelta(minutes=2)
        elif charge.attendance_record_id % 5 == 0:
            charge.status = ExtendedCareChargeStatus.confirmed
            charge.confirmed_by = "事務"
            charge.confirmed_at = confirmed_at

        if charge.confirmed_at is not None:
            charge.updated_at = charge.confirmed_at
        session.add(charge)

    return {
        "extended_care_fee_rules": 1,
        "extended_care_charges": len(charges),
    }


def seed(wipe: bool = False) -> dict[str, int]:
    # A previous/partial seed can leave foreign-key violations behind.  In
    # wipe mode, remove the old demo rows before the normal startup validation
    # so the seed command can repair that database itself.
    if wipe:
        import child_records.models  # noqa: F401
        import plan_docs.db_models  # noqa: F401

        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            wipe_all(session)

    create_db_and_tables()
    counts: dict[str, int] = {}
    guardian_profiles_by_family = build_family_guardian_profiles()
    with Session(engine) as session:
        if not wipe:
            existing = session.get(Classroom, 1)
            if existing:
                raise RuntimeError(
                    "既存データがあるようです。デモDBを作り直す場合のみ --wipe-all を付けて実行してください。"
                )
        # The demo set contains a small circular reference between users.default_calendar_id
        # and calendars.owner_user_id. Keep this limited to local/demo seeding only.
        session.exec(text("PRAGMA foreign_keys=OFF"))
        for table, model in MODEL_ORDER:
            if table in DYNAMIC_DEMO_TABLES:
                continue
            rows = load_rows(table)
            if table == "families":
                for row in rows:
                    row["shared_profile"] = {
                        "guardians": guardian_profiles_by_family.get(row["id"], [])
                    }
            if table == "users":
                for row in rows:
                    row.setdefault("provisioning_source", USER_SOURCE_WEB_DEMO)
                    is_admin = row.get("staff_role") == "admin"
                    is_office = row.get("email") == "office@demo.open-hoikuict.example"
                    row.setdefault("can_manage_child_records", is_admin or is_office)
                    row.setdefault("can_manage_billing_accounts", is_office)
            if table == "child_profile_change_requests":
                for row in rows:
                    child = session.get(Child, row["child_id"])
                    if not child:
                        continue
                    payload = resolve_child_profile_change_payload(child, row.get("request_data"))
                    if payload:
                        row["request_data"] = payload
                        row["change_details"] = build_child_profile_change_details(child, payload)
            for row in rows:
                session.add(model(**row))
            counts[table] = len(rows)
            session.flush()
        reference_date = local_today()
        counts.update(
            seed_dynamic_demo_data(
                session,
                reference_date=reference_date,
                recalculate_extended_care=False,
            )
        )
        attendance_start, attendance_end = demo_attendance_range(reference_date)
        counts.update(
            seed_extended_care_demo_data(
                session,
                start_date=attendance_start,
                end_date=attendance_end,
            )
        )
        children = session.exec(select(Child).order_by(Child.id)).all()
        for child in children:
            ensure_initial_child_profile_history(session, child, actor_name="デモデータ")
        counts["child_profile_histories"] = len(children)
        session.commit()
        session.exec(text("PRAGMA foreign_keys=ON"))
    return counts

def main() -> int:
    parser = argparse.ArgumentParser(description="Seed open-hoikuict with a 100-child realistic demo dataset.")
    parser.add_argument("--wipe-all", action="store_true", help="Delete all existing rows in supported demo tables before seeding. Use only for local/demo DBs.")
    args = parser.parse_args()
    try:
        counts = seed(wipe=args.wipe_all)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Demo data seeded successfully.")
    for table, count in counts.items():
        print(f"- {table}: {count}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
