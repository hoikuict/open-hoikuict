from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import delete, text
from sqlmodel import Session, select

from child_profile_changes import build_child_profile_change_details, resolve_child_profile_change_payload
from child_profile_history import ensure_initial_child_profile_history
from database import create_db_and_tables, engine
from demo_data_generation import demo_attendance_range, seed_dynamic_demo_data
from extended_care_fee_service import recalculate_period
from models import (
    AttendanceAlarmHistory, AttendanceAlarmState, AttendanceRecord,
    AttendanceVerification, AttendanceVerificationHistory, Calendar,
    CalendarMember, CalendarUserPreference, Child, ChildAllergy, DailyContactEntry,
    ChildHealthProfile, ChildProfileChangeRequest, ChildProfileHistory, Classroom, Event,
    CareNeedReason, CareTimeCategory, ChildCareCertification, ChildCareCertificationAuditLog,
    ChildCareNeedReason,
    ExtendedCareCalculationSetting, ExtendedCareCharge, ExtendedCareChargeStatus, ExtendedCareFeeRule,
    Family, Guardian, HealthCheckRecord, Message, Notice, NoticeRead,
    NoticeTarget, ParentAccount, ParentChildLink, ProfileChangeNotification,
    Survey, SurveyAnswer, SurveyQuestion, SurveyQuestionOption,
    SurveyResponse, SurveyTarget, User,
    USER_SOURCE_WEB_DEMO,
)
from time_utils import local_today
from scripts.materialize_demo_identity_scenarios import FOREIGN_SCENARIO_FAMILY_IDS

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

WIPE_ORDER = [
    ChildProfileHistory,
    ExtendedCareCharge,
    ChildCareNeedReason,
    ChildCareCertificationAuditLog,
    ChildCareCertification,
    ExtendedCareCalculationSetting,
    ExtendedCareFeeRule,
    *list(reversed([model for _, model in MODEL_ORDER])),
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


def validate_demo_identity_scenarios() -> dict[str, int | float]:
    families = load_rows("families")
    children = load_rows("children")
    parents = load_rows("parent_accounts")
    if len(families) != 84:
        raise ValueError(f"デモ家庭数は84件である必要があります: {len(families)}")

    people = children + parents
    for row in people:
        name = str(row.get("registration_verification_name") or "").strip()
        name_type = str(row.get("registration_verification_name_type") or "").strip()
        if name_type not in {"kana", "latin"}:
            raise ValueError(f"照合用氏名種別が不正です: {name_type!r}")
        if not name:
            raise ValueError("照合用氏名が空です")
        if name_type == "latin" and not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", name):
            raise ValueError(f"latin照合用氏名に英字がありません: {name}")

    latin_family_ids = {
        int(row["family_id"])
        for row in people
        if row.get("family_id") is not None
        and row["registration_verification_name_type"] == "latin"
    }
    if latin_family_ids != set(FOREIGN_SCENARIO_FAMILY_IDS):
        raise ValueError(
            "外国籍想定家庭が固定9家庭と一致しません: "
            f"expected={sorted(FOREIGN_SCENARIO_FAMILY_IDS)}, actual={sorted(latin_family_ids)}"
        )

    name_types_by_family: dict[int, set[str]] = {}
    child_counts_by_family = Counter(int(row["family_id"]) for row in children)
    for row in people:
        family_id = row.get("family_id")
        if family_id is None:
            continue
        name_types_by_family.setdefault(int(family_id), set()).add(
            str(row["registration_verification_name_type"])
        )
    mixed_family_count = sum(
        name_types_by_family.get(family_id) == {"kana", "latin"}
        for family_id in FOREIGN_SCENARIO_FAMILY_IDS
    )
    sibling_family_count = sum(
        child_counts_by_family[family_id] >= 2
        for family_id in FOREIGN_SCENARIO_FAMILY_IDS
    )
    if mixed_family_count < 2:
        raise ValueError(f"カナ・英字混在家庭は2件以上必要です: {mixed_family_count}")
    if sibling_family_count < 2:
        raise ValueError(f"外国籍想定の兄弟家庭は2件以上必要です: {sibling_family_count}")

    return {
        "foreign_scenario_families": len(latin_family_ids),
        "foreign_scenario_percentage": round(len(latin_family_ids) / len(families) * 100, 1),
        "mixed_name_type_families": mixed_family_count,
        "foreign_sibling_families": sibling_family_count,
        "latin_children": sum(
            row["registration_verification_name_type"] == "latin" for row in children
        ),
        "latin_parent_accounts": sum(
            row["registration_verification_name_type"] == "latin" for row in parents
        ),
    }

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

def wipe_all(session: Session) -> None:
    session.exec(text("PRAGMA foreign_keys=OFF"))
    for model in WIPE_ORDER:
        session.exec(delete(model))
    session.commit()
    session.exec(text("PRAGMA foreign_keys=ON"))


def seed_extended_care_demo_data(
    session: Session,
    *,
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    standard_rule = ExtendedCareFeeRule(
        id=1,
        name="保育標準時間・延長保育料（デモ）",
        effective_from=start_date,
        start_time="18:00",
        care_time_category=CareTimeCategory.standard,
        normal_start_time="07:30",
        normal_end_time="18:00",
        morning_enabled=True,
        morning_grace_minutes=5,
        morning_rounding_minutes=15,
        morning_unit_price=100,
        evening_enabled=True,
        grace_minutes=5,
        rounding_minutes=15,
        unit_price=100,
        daily_cap_amount=None,
        is_active=True,
        created_at=datetime.combine(start_date, datetime.min.time()).replace(hour=9),
        updated_at=datetime.combine(start_date, datetime.min.time()).replace(hour=9),
    )
    short_rule = ExtendedCareFeeRule(
        id=2,
        name="保育短時間・延長保育料（デモ）",
        effective_from=start_date,
        start_time="16:30",
        care_time_category=CareTimeCategory.short,
        normal_start_time="08:30",
        normal_end_time="16:30",
        morning_enabled=True,
        morning_grace_minutes=5,
        morning_rounding_minutes=15,
        morning_unit_price=100,
        evening_enabled=True,
        grace_minutes=5,
        rounding_minutes=15,
        unit_price=100,
        daily_cap_amount=800,
        is_active=True,
        created_at=datetime.combine(start_date, datetime.min.time()).replace(hour=9),
        updated_at=datetime.combine(start_date, datetime.min.time()).replace(hour=9),
    )
    session.add(standard_rule)
    session.add(short_rule)
    session.add(
        ExtendedCareCalculationSetting(
            id=1,
            mode="category_aware",
            category_aware_from=start_date,
            updated_by_name="デモデータ",
        )
    )
    session.flush()

    certification_count = 0
    reason_count = 0
    children = session.exec(select(Child).order_by(Child.id)).all()
    reason_cycle = [
        CareNeedReason.employment,
        CareNeedReason.illness_disability,
        CareNeedReason.job_search_startup,
        CareNeedReason.education_training,
    ]
    for child in children:
        certification = ChildCareCertification(
            child_id=child.id,
            care_time_category=CareTimeCategory.short if child.id % 3 == 0 else CareTimeCategory.standard,
            effective_from=start_date,
            created_by_name="デモデータ",
            updated_by_name="デモデータ",
        )
        session.add(certification)
        session.flush()
        profiles = child.family.guardian_profiles() if child.family else []
        for index, profile in enumerate(profiles[:2], start=1):
            session.add(
                ChildCareNeedReason(
                    certification_id=certification.id,
                    guardian_order=index,
                    guardian_name_snapshot=f"{profile.get('last_name', '')} {profile.get('first_name', '')}".strip(),
                    relationship_snapshot=str(profile.get("relationship", "")),
                    reason=reason_cycle[(child.id + index) % len(reason_cycle)],
                )
            )
            reason_count += 1
        certification_count += 1
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
        "extended_care_fee_rules": 2,
        "extended_care_charges": len(charges),
        "child_care_certifications": certification_count,
        "child_care_need_reasons": reason_count,
    }


def seed(wipe: bool = False) -> dict[str, int | float]:
    identity_summary = validate_demo_identity_scenarios()
    create_db_and_tables()
    counts: dict[str, int | float] = {}
    with Session(engine) as session:
        if wipe:
            wipe_all(session)
        else:
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
        counts.update(identity_summary)
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
