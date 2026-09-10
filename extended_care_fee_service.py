from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from io import StringIO
from math import ceil
from typing import Optional

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from models import (
    AttendanceRecord,
    CareTimeCategory,
    Child,
    ChildCareCertification,
    ExtendedCareCalculationSetting,
    ExtendedCareCharge,
    ExtendedCareChargeStatus,
    ExtendedCareFeeRule,
)
from time_utils import local_today, utc_now


LOCKED_STATUSES = {
    ExtendedCareChargeStatus.confirmed,
    ExtendedCareChargeStatus.manual_adjusted,
    ExtendedCareChargeStatus.excluded,
}


@dataclass(slots=True)
class ChargeComputation:
    charge_start_at: datetime
    actual_check_out_at: Optional[datetime]
    extended_minutes: int
    billable_units: int
    auto_amount: int
    actual_check_in_at: Optional[datetime] = None
    normal_start_at: Optional[datetime] = None
    normal_end_at: Optional[datetime] = None
    morning_extended_minutes: int = 0
    morning_billable_units: int = 0
    morning_amount: int = 0
    evening_extended_minutes: int = 0
    evening_billable_units: int = 0
    evening_amount: int = 0


@dataclass(slots=True)
class ExtendedCareChargeDetail:
    charge_id: int
    attendance_record_id: int
    target_date: date
    check_in_at: Optional[datetime]
    check_out_at: Optional[datetime]
    planned_pickup_time: str
    charge_start_at: datetime
    extended_minutes: int
    billable_units: int
    auto_amount: int
    adjustment_amount: int
    final_amount: int
    status: ExtendedCareChargeStatus
    status_label: str
    adjustment_reason: str
    is_transferred: bool
    transferred_amount: Optional[int]
    care_time_category_label: str = ""
    normal_time_label: str = ""
    morning_extended_minutes: int = 0
    morning_amount: int = 0
    evening_extended_minutes: int = 0
    evening_amount: int = 0
    warning: str = ""

    @property
    def needs_confirmation(self) -> bool:
        return self.status == ExtendedCareChargeStatus.draft and self.final_amount > 0


@dataclass(slots=True)
class ExtendedCareMonthlySummary:
    child_id: int
    child_name: str
    child_name_kana: str
    classroom_name: str
    classroom_sort_order: int
    extended_days: int = 0
    extended_minutes_total: int = 0
    auto_amount_total: int = 0
    adjustment_amount_total: int = 0
    final_amount_total: int = 0
    unconfirmed_count: int = 0
    standard_days: int = 0
    short_days: int = 0
    morning_minutes_total: int = 0
    morning_amount_total: int = 0
    evening_minutes_total: int = 0
    evening_amount_total: int = 0
    details: list[ExtendedCareChargeDetail] = field(default_factory=list)


@dataclass(slots=True)
class ExtendedCareMonthlyOverview:
    month: str
    start_date: date
    end_date: date
    summaries: list[ExtendedCareMonthlySummary]
    warnings: list[str]
    total_extended_days: int
    total_extended_minutes: int
    total_auto_amount: int
    total_adjustment_amount: int
    total_final_amount: int
    total_unconfirmed_count: int


def parse_month(raw: Optional[str]) -> tuple[str, date, date]:
    today = local_today()
    normalized = today.strftime("%Y-%m")
    if raw:
        try:
            parsed = date.fromisoformat(f"{raw}-01")
            normalized = parsed.strftime("%Y-%m")
        except ValueError:
            parsed = today.replace(day=1)
    else:
        parsed = today.replace(day=1)

    if parsed.month == 12:
        next_month = date(parsed.year + 1, 1, 1)
    else:
        next_month = date(parsed.year, parsed.month + 1, 1)
    return normalized, parsed, next_month - timedelta(days=1)


def charge_status_label(charge: ExtendedCareCharge) -> str:
    if charge.status == ExtendedCareChargeStatus.draft and charge.final_amount == 0:
        return "0円"
    return charge.status.label


def validate_fee_rule(
    session: Session,
    *,
    name: str,
    effective_from: date,
    effective_to: Optional[date],
    start_time: str,
    grace_minutes: int,
    rounding_minutes: int,
    unit_price: int,
    daily_cap_amount: Optional[int],
    is_active: bool,
    care_time_category: Optional[CareTimeCategory] = None,
    normal_start_time: Optional[str] = None,
    normal_end_time: Optional[str] = None,
    morning_enabled: bool = False,
    morning_grace_minutes: int = 0,
    morning_rounding_minutes: int = 15,
    morning_unit_price: int = 0,
    evening_enabled: bool = True,
    evening_grace_minutes: Optional[int] = None,
    evening_rounding_minutes: Optional[int] = None,
    evening_unit_price: Optional[int] = None,
    rule_id: Optional[int] = None,
) -> list[str]:
    errors: list[str] = []
    if not name.strip():
        errors.append("ルール名を入力してください。")
    try:
        _parse_rule_time(start_time)
    except ValueError:
        errors.append("延長開始時刻は HH:MM 形式で入力してください。")
    if not 0 <= grace_minutes <= 120:
        errors.append("猶予時間は 0 以上 120 以下で入力してください。")
    if not 1 <= rounding_minutes <= 120:
        errors.append("丸め単位は 1 以上 120 以下で入力してください。")
    if unit_price < 0:
        errors.append("単価は 0 以上で入力してください。")
    if daily_cap_amount is not None and daily_cap_amount < 0:
        errors.append("日別上限額は空欄または 0 以上で入力してください。")
    if effective_to is not None and effective_to < effective_from:
        errors.append("適用終了日は適用開始日以降にしてください。")
    if care_time_category is not None:
        try:
            normal_start = _parse_rule_time(normal_start_time or "")
            normal_end = _parse_rule_time(normal_end_time or "")
            if normal_start >= normal_end:
                errors.append("通常保育終了時刻は開始時刻より後にしてください。")
        except ValueError:
            errors.append("通常保育開始・終了時刻は HH:MM 形式で入力してください。")
        if not morning_enabled and not evening_enabled:
            errors.append("朝延長または夕延長のいずれかを有効にしてください。")
        if not 0 <= morning_grace_minutes <= 120:
            errors.append("朝猶予時間は 0 以上 120 以下で入力してください。")
        if not 1 <= morning_rounding_minutes <= 120:
            errors.append("朝丸め単位は 1 以上 120 以下で入力してください。")
        if morning_unit_price < 0:
            errors.append("朝単価は 0 以上で入力してください。")
        resolved_evening_grace = grace_minutes if evening_grace_minutes is None else evening_grace_minutes
        resolved_evening_rounding = rounding_minutes if evening_rounding_minutes is None else evening_rounding_minutes
        resolved_evening_price = unit_price if evening_unit_price is None else evening_unit_price
        if not 0 <= resolved_evening_grace <= 120:
            errors.append("夕猶予時間は 0 以上 120 以下で入力してください。")
        if not 1 <= resolved_evening_rounding <= 120:
            errors.append("夕丸め単位は 1 以上 120 以下で入力してください。")
        if resolved_evening_price < 0:
            errors.append("夕単価は 0 以上で入力してください。")

    if is_active and not errors:
        existing_rules = session.exec(
            select(ExtendedCareFeeRule).where(ExtendedCareFeeRule.is_active == True)  # noqa: E712
        ).all()
        for existing in existing_rules:
            if rule_id is not None and existing.id == rule_id:
                continue
            if existing.care_time_category != care_time_category:
                continue
            if _periods_overlap(effective_from, effective_to, existing.effective_from, existing.effective_to):
                category_label = care_time_category.label if care_time_category else "従来計算（区分なし）"
                errors.append(f"既存の有効ルールと適用期間が重複しています。「{existing.name}」と同じ{category_label}です。標準時間と短時間を分ける場合は、ルール名ではなく保育必要量を選択してください。")
                break

    return errors


def get_active_rule_for_date(
    session: Session,
    target_date: date,
    care_time_category: Optional[CareTimeCategory] = None,
) -> Optional[ExtendedCareFeeRule]:
    rules = session.exec(
        select(ExtendedCareFeeRule).where(
            ExtendedCareFeeRule.is_active == True,  # noqa: E712
            ExtendedCareFeeRule.effective_from <= target_date,
        )
    ).all()
    candidates = [
        rule
        for rule in rules
        if (rule.effective_to is None or rule.effective_to >= target_date)
        and rule.care_time_category == care_time_category
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda rule: (rule.effective_from, rule.id or 0), reverse=True)[0]


def calculate_charge(record: AttendanceRecord, rule: ExtendedCareFeeRule) -> ChargeComputation:
    if rule.care_time_category is not None:
        return _calculate_category_charge(record, rule)
    if record.check_out_at is None:
        raise ValueError("降園打刻がないため計算できません。")

    charge_start_at = datetime.combine(record.attendance_date, _parse_rule_time(rule.start_time)) + timedelta(
        minutes=rule.grace_minutes
    )
    actual_check_out_at = _floor_to_minute(record.check_out_at)

    if actual_check_out_at <= charge_start_at:
        return ChargeComputation(
            charge_start_at=charge_start_at,
            actual_check_out_at=actual_check_out_at,
            extended_minutes=0,
            billable_units=0,
            auto_amount=0,
        )

    elapsed_seconds = (actual_check_out_at - charge_start_at).total_seconds()
    raw_minutes = max(0, int(elapsed_seconds // 60))
    billable_units = ceil(raw_minutes / rule.rounding_minutes)
    extended_minutes = billable_units * rule.rounding_minutes
    auto_amount = billable_units * rule.unit_price
    if rule.daily_cap_amount is not None:
        auto_amount = min(auto_amount, rule.daily_cap_amount)

    return ChargeComputation(
        charge_start_at=charge_start_at,
        actual_check_out_at=actual_check_out_at,
        extended_minutes=extended_minutes,
        billable_units=billable_units,
        auto_amount=auto_amount,
        evening_extended_minutes=extended_minutes,
        evening_billable_units=billable_units,
        evening_amount=auto_amount,
    )


def _calculate_category_charge(record: AttendanceRecord, rule: ExtendedCareFeeRule) -> ChargeComputation:
    if not rule.normal_start_time or not rule.normal_end_time:
        raise ValueError("区分別料金ルールの通常保育時間が未設定です。")
    normal_start_at = datetime.combine(record.attendance_date, _parse_rule_time(rule.normal_start_time))
    normal_end_at = datetime.combine(record.attendance_date, _parse_rule_time(rule.normal_end_time))
    morning_minutes = morning_units = morning_amount = 0
    evening_minutes = evening_units = evening_amount = 0

    actual_check_in_at = _floor_to_minute(record.check_in_at) if record.check_in_at else None
    actual_check_out_at = _floor_to_minute(record.check_out_at) if record.check_out_at else None
    if rule.morning_enabled:
        if actual_check_in_at is None:
            raise ValueError("登園打刻がないため朝延長を計算できません。")
        morning_boundary = normal_start_at - timedelta(minutes=rule.morning_grace_minutes)
        raw_morning = max(0, int((morning_boundary - actual_check_in_at).total_seconds() // 60))
        morning_units = ceil(raw_morning / rule.morning_rounding_minutes) if raw_morning else 0
        morning_minutes = morning_units * rule.morning_rounding_minutes
        morning_amount = morning_units * rule.morning_unit_price

    evening_grace = rule.grace_minutes if rule.evening_grace_minutes is None else rule.evening_grace_minutes
    evening_rounding = rule.rounding_minutes if rule.evening_rounding_minutes is None else rule.evening_rounding_minutes
    evening_price = rule.unit_price if rule.evening_unit_price is None else rule.evening_unit_price
    charge_start_at = normal_end_at + timedelta(minutes=evening_grace)
    if rule.evening_enabled:
        if actual_check_out_at is None:
            raise ValueError("降園打刻がないため夕延長を計算できません。")
        raw_evening = max(0, int((actual_check_out_at - charge_start_at).total_seconds() // 60))
        evening_units = ceil(raw_evening / evening_rounding) if raw_evening else 0
        evening_minutes = evening_units * evening_rounding
        evening_amount = evening_units * evening_price

    auto_amount = morning_amount + evening_amount
    if rule.daily_cap_amount is not None:
        auto_amount = min(auto_amount, rule.daily_cap_amount)
    return ChargeComputation(
        charge_start_at=charge_start_at,
        actual_check_out_at=actual_check_out_at,
        actual_check_in_at=actual_check_in_at,
        normal_start_at=normal_start_at,
        normal_end_at=normal_end_at,
        morning_extended_minutes=morning_minutes,
        morning_billable_units=morning_units,
        morning_amount=morning_amount,
        evening_extended_minutes=evening_minutes,
        evening_billable_units=evening_units,
        evening_amount=evening_amount,
        extended_minutes=morning_minutes + evening_minutes,
        billable_units=morning_units + evening_units,
        auto_amount=auto_amount,
    )


def recalculate_attendance_charge(
    session: Session,
    record: AttendanceRecord,
    *,
    include_locked: bool = False,
) -> Optional[ExtendedCareCharge]:
    if record.id is None or record.check_out_at is None:
        return None

    existing = session.exec(
        select(ExtendedCareCharge).where(ExtendedCareCharge.attendance_record_id == record.id)
    ).first()
    if existing and existing.billing_charge_line_id is not None:
        return existing
    if existing and existing.status in LOCKED_STATUSES and not include_locked:
        return existing

    rule, certification, _ = resolve_calculation_context(session, record)
    if rule is None or rule.id is None:
        return existing

    computed = calculate_charge(record, rule)
    charge = existing or ExtendedCareCharge(
        attendance_record_id=record.id,
        child_id=record.child_id,
        target_date=record.attendance_date,
        rule_id=rule.id,
        charge_start_at=computed.charge_start_at,
    )
    charge.child_id = record.child_id
    charge.target_date = record.attendance_date
    charge.rule_id = rule.id
    charge.charge_start_at = computed.charge_start_at
    charge.actual_check_out_at = computed.actual_check_out_at
    charge.extended_minutes = computed.extended_minutes
    charge.billable_units = computed.billable_units
    charge.auto_amount = computed.auto_amount
    charge.certification_id = certification.id if certification else None
    charge.care_time_category_snapshot = certification.care_time_category if certification else None
    charge.calculation_version = "category_v1" if certification else "legacy_v1"
    charge.actual_check_in_at = computed.actual_check_in_at
    charge.normal_start_at = computed.normal_start_at
    charge.normal_end_at = computed.normal_end_at
    charge.morning_extended_minutes = computed.morning_extended_minutes
    charge.morning_billable_units = computed.morning_billable_units
    charge.morning_amount = computed.morning_amount
    charge.evening_extended_minutes = computed.evening_extended_minutes
    charge.evening_billable_units = computed.evening_billable_units
    charge.evening_amount = computed.evening_amount
    charge.adjustment_amount = 0
    charge.final_amount = computed.auto_amount
    charge.status = ExtendedCareChargeStatus.draft
    charge.adjustment_reason = None
    charge.confirmed_by = None
    charge.confirmed_at = None
    charge.updated_at = utc_now()
    session.add(charge)
    return charge


def get_calculation_setting(session: Session) -> ExtendedCareCalculationSetting:
    setting = session.exec(
        select(ExtendedCareCalculationSetting).order_by(ExtendedCareCalculationSetting.id)
    ).first()
    if setting is not None:
        return setting
    return ExtendedCareCalculationSetting(mode="legacy")


def resolve_calculation_context(
    session: Session,
    record: AttendanceRecord,
    *,
    lookup: Optional[tuple] = None,
) -> tuple[Optional[ExtendedCareFeeRule], Optional[ChildCareCertification], str]:
    setting, rules, certification_rows = lookup if lookup is not None else _calculation_lookup(session, [record])
    def active_rule(category=None):
        candidates = [rule for rule in rules if rule.care_time_category == category
                      and rule.effective_from <= record.attendance_date
                      and (rule.effective_to is None or rule.effective_to >= record.attendance_date)]
        return max(candidates, key=lambda rule: (rule.effective_from, rule.id or 0), default=None)

    category_mode = (
        setting.mode == "category_aware"
        and setting.category_aware_from is not None
        and record.attendance_date >= setting.category_aware_from
    )
    if not category_mode:
        rule = active_rule()
        return rule, None, "" if rule else "有効な料金ルールがありません"

    certifications = [
        item
        for item in certification_rows
        if item.child_id == record.child_id and item.effective_from <= record.attendance_date
        and (item.effective_to is None or item.effective_to >= record.attendance_date)
    ]
    if not certifications:
        return None, None, "有効な保育認定がありません"
    if len(certifications) > 1:
        return None, None, "保育認定の適用期間が重複しています"
    certification = certifications[0]
    rule = active_rule(certification.care_time_category)
    if rule is None:
        return None, certification, f"{certification.care_time_category.label}の料金ルールがありません"
    if rule.morning_enabled and record.check_in_at is None:
        return None, certification, "登園打刻がないため朝延長を計算できません"
    if rule.evening_enabled and record.check_out_at is None:
        return None, certification, "降園打刻がないため夕延長を計算できません"
    return rule, certification, ""


def _calculation_lookup(session: Session, records: list[AttendanceRecord]) -> tuple:
    setting = get_calculation_setting(session)
    rules = session.exec(select(ExtendedCareFeeRule).where(ExtendedCareFeeRule.is_active == True)).all()  # noqa: E712
    certifications = []
    if setting.mode == "category_aware":
        child_ids = {record.child_id for record in records}
        certifications = session.exec(select(ChildCareCertification).where(
            ChildCareCertification.child_id.in_(child_ids), ChildCareCertification.is_active == True,  # noqa: E712
        )).all()
    return setting, rules, certifications


def calculation_issues_for_records(session: Session, records: list[AttendanceRecord]) -> dict[int, str]:
    if not records:
        return {}
    lookup = _calculation_lookup(session, records)
    return {record.id: resolve_calculation_context(session, record, lookup=lookup)[2]
            or "料金データが未作成です。対象月を再計算してください。" for record in records}


def recalculate_period(
    session: Session,
    start_date: date,
    end_date: date,
    *,
    include_locked: bool = False,
) -> int:
    records = session.exec(
        select(AttendanceRecord).where(
            AttendanceRecord.attendance_date >= start_date,
            AttendanceRecord.attendance_date <= end_date,
            AttendanceRecord.check_out_at.is_not(None),
        )
    ).all()
    updated = 0
    for record in records:
        before = session.exec(
            select(ExtendedCareCharge).where(ExtendedCareCharge.attendance_record_id == record.id)
        ).first()
        before_snapshot = _charge_recalculation_snapshot(before)
        charge = recalculate_attendance_charge(session, record, include_locked=include_locked)
        if charge is not None and _charge_recalculation_snapshot(charge) != before_snapshot:
            updated += 1
    return updated


def _charge_recalculation_snapshot(charge: Optional[ExtendedCareCharge]) -> tuple | None:
    if charge is None:
        return None
    return (
        charge.rule_id,
        charge.charge_start_at,
        charge.actual_check_out_at,
        charge.extended_minutes,
        charge.billable_units,
        charge.auto_amount,
        charge.adjustment_amount,
        charge.final_amount,
        charge.status,
        charge.adjustment_reason,
        charge.confirmed_by,
        charge.confirmed_at,
        charge.certification_id,
        charge.care_time_category_snapshot,
        charge.calculation_version,
        charge.morning_extended_minutes,
        charge.morning_amount,
        charge.evening_extended_minutes,
        charge.evening_amount,
    )


def confirm_charge(charge: ExtendedCareCharge, staff_name: str) -> None:
    _ensure_not_transferred(charge)
    charge.status = ExtendedCareChargeStatus.confirmed
    charge.confirmed_by = staff_name
    charge.confirmed_at = utc_now()
    charge.final_amount = max(0, charge.auto_amount + charge.adjustment_amount)
    charge.updated_at = utc_now()


def adjust_charge(charge: ExtendedCareCharge, adjustment_amount: int, reason: str, staff_name: str) -> None:
    _ensure_not_transferred(charge)
    cleaned_reason = reason.strip()
    if adjustment_amount != 0 and not cleaned_reason:
        raise ValueError("調整額を入力する場合は理由を入力してください。")
    charge.adjustment_amount = adjustment_amount
    charge.adjustment_reason = cleaned_reason or None
    charge.final_amount = max(0, charge.auto_amount + adjustment_amount)
    charge.status = ExtendedCareChargeStatus.manual_adjusted
    charge.confirmed_by = staff_name
    charge.confirmed_at = utc_now()
    charge.updated_at = utc_now()


def exclude_charge(charge: ExtendedCareCharge, reason: str, staff_name: str) -> None:
    _ensure_not_transferred(charge)
    charge.adjustment_amount = -charge.auto_amount
    charge.adjustment_reason = reason.strip() or "請求対象外"
    charge.final_amount = 0
    charge.status = ExtendedCareChargeStatus.excluded
    charge.confirmed_by = staff_name
    charge.confirmed_at = utc_now()
    charge.updated_at = utc_now()


def build_monthly_overview(
    session: Session,
    *,
    month: str,
    classroom_id: Optional[int] = None,
    child_name: str = "",
    unconfirmed_only: bool = False,
) -> ExtendedCareMonthlyOverview:
    normalized_month, start_date, end_date = parse_month(month)
    normalized_child_name = _normalize_text(child_name)
    children = session.exec(select(Child).options(selectinload(Child.classroom))).all()
    children_by_id = {child.id: child for child in children if child.id is not None}
    summaries: dict[int, ExtendedCareMonthlySummary] = {}
    warnings: list[str] = []

    charges = session.exec(
        select(ExtendedCareCharge).where(
            ExtendedCareCharge.target_date >= start_date,
            ExtendedCareCharge.target_date <= end_date,
        )
    ).all()
    charge_record_ids = {charge.attendance_record_id for charge in charges}
    record_ids = list(charge_record_ids)
    records_by_id: dict[int, AttendanceRecord] = {}
    if record_ids:
        records = session.exec(
            select(AttendanceRecord).where(AttendanceRecord.id.in_(record_ids))
        ).all()
        records_by_id = {record.id: record for record in records if record.id is not None}

    for charge in sorted(charges, key=lambda item: (item.target_date, item.child_id, item.id or 0)):
        child = children_by_id.get(charge.child_id)
        if child is None or not _matches_child_filter(child, classroom_id, normalized_child_name):
            continue
        if unconfirmed_only and not _is_unconfirmed(charge):
            continue

        summary = summaries.setdefault(charge.child_id, _make_summary(child))
        record = records_by_id.get(charge.attendance_record_id)
        detail = _make_detail(charge, record)
        summary.details.append(detail)
        if charge.final_amount > 0:
            summary.extended_days += 1
        summary.extended_minutes_total += charge.extended_minutes
        summary.auto_amount_total += charge.auto_amount
        summary.adjustment_amount_total += charge.adjustment_amount
        summary.final_amount_total += charge.final_amount
        if charge.care_time_category_snapshot == CareTimeCategory.standard:
            summary.standard_days += 1
        elif charge.care_time_category_snapshot == CareTimeCategory.short:
            summary.short_days += 1
        summary.morning_minutes_total += charge.morning_extended_minutes
        summary.morning_amount_total += charge.morning_amount
        summary.evening_minutes_total += charge.evening_extended_minutes
        summary.evening_amount_total += charge.evening_amount
        if _is_unconfirmed(charge):
            summary.unconfirmed_count += 1

    unchecked_records = session.exec(
        select(AttendanceRecord).where(
            AttendanceRecord.attendance_date >= start_date,
            AttendanceRecord.attendance_date <= end_date,
            AttendanceRecord.check_out_at.is_not(None),
        )
    ).all()
    for record in unchecked_records:
        if record.id in charge_record_ids:
            continue
        child = children_by_id.get(record.child_id)
        if child is None or not _matches_child_filter(child, classroom_id, normalized_child_name):
            continue
        rule, _, issue = resolve_calculation_context(session, record)
        reason = issue or ("有効な料金ルールがありません" if rule is None else "未計算です")
        warnings.append(f"{record.attendance_date.isoformat()} {child.full_name}: {reason}")

    summary_list = sorted(
        summaries.values(),
        key=lambda item: (item.classroom_sort_order, _normalize_text(item.child_name_kana), item.child_id),
    )
    return ExtendedCareMonthlyOverview(
        month=normalized_month,
        start_date=start_date,
        end_date=end_date,
        summaries=summary_list,
        warnings=warnings,
        total_extended_days=sum(item.extended_days for item in summary_list),
        total_extended_minutes=sum(item.extended_minutes_total for item in summary_list),
        total_auto_amount=sum(item.auto_amount_total for item in summary_list),
        total_adjustment_amount=sum(item.adjustment_amount_total for item in summary_list),
        total_final_amount=sum(item.final_amount_total for item in summary_list),
        total_unconfirmed_count=sum(item.unconfirmed_count for item in summary_list),
    )


def build_monthly_csv(overview: ExtendedCareMonthlyOverview) -> bytes:
    buffer = StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(
        [
            "対象月",
            "園児ID",
            "園児名",
            "園児名カナ",
            "クラス",
            "延長回数",
            "延長分数合計",
            "自動計算額合計",
            "調整額合計",
            "確定額合計",
            "未確認件数",
            "保育標準時間日数",
            "保育短時間日数",
            "朝延長分数合計",
            "朝延長金額合計",
            "夕延長分数合計",
            "夕延長金額合計",
        ]
    )
    for summary in overview.summaries:
        writer.writerow(
            [
                overview.month,
                summary.child_id,
                summary.child_name,
                summary.child_name_kana,
                summary.classroom_name,
                summary.extended_days,
                summary.extended_minutes_total,
                summary.auto_amount_total,
                summary.adjustment_amount_total,
                summary.final_amount_total,
                summary.unconfirmed_count,
                summary.standard_days,
                summary.short_days,
                summary.morning_minutes_total,
                summary.morning_amount_total,
                summary.evening_minutes_total,
                summary.evening_amount_total,
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")


def _parse_rule_time(value: str) -> time:
    parsed = datetime.strptime(value, "%H:%M")
    return parsed.time()


def _floor_to_minute(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def _periods_overlap(
    start_a: date,
    end_a: Optional[date],
    start_b: date,
    end_b: Optional[date],
) -> bool:
    normalized_end_a = end_a or date.max
    normalized_end_b = end_b or date.max
    return start_a <= normalized_end_b and start_b <= normalized_end_a


def _normalize_text(value: str) -> str:
    return "".join((value or "").lower().split())


def _matches_child_filter(child: Child, classroom_id: Optional[int], child_name: str) -> bool:
    if classroom_id is not None and child.classroom_id != classroom_id:
        return False
    if not child_name:
        return True
    haystacks = [
        child.full_name,
        child.full_name.replace(" ", ""),
        child.full_name_kana,
        child.full_name_kana.replace(" ", ""),
    ]
    return any(child_name in _normalize_text(value) for value in haystacks)


def _is_unconfirmed(charge: ExtendedCareCharge) -> bool:
    return charge.status == ExtendedCareChargeStatus.draft and charge.final_amount > 0


def _make_summary(child: Child) -> ExtendedCareMonthlySummary:
    return ExtendedCareMonthlySummary(
        child_id=child.id or 0,
        child_name=child.full_name,
        child_name_kana=child.full_name_kana,
        classroom_name=child.classroom.name if child.classroom else "",
        classroom_sort_order=child.classroom.display_order if child.classroom else 999,
    )


def _make_detail(charge: ExtendedCareCharge, record: Optional[AttendanceRecord]) -> ExtendedCareChargeDetail:
    warning = ""
    if record and record.check_out_at:
        cutoff = datetime.combine(record.attendance_date + timedelta(days=1), time(3, 0))
        if record.check_out_at > cutoff:
            warning = "翌日03:00を超える降園打刻です"
    return ExtendedCareChargeDetail(
        charge_id=charge.id or 0,
        attendance_record_id=charge.attendance_record_id,
        target_date=charge.target_date,
        check_in_at=record.check_in_at if record else None,
        check_out_at=record.check_out_at if record else charge.actual_check_out_at,
        planned_pickup_time=record.planned_pickup_time if record and record.planned_pickup_time else "",
        charge_start_at=charge.charge_start_at,
        extended_minutes=charge.extended_minutes,
        billable_units=charge.billable_units,
        auto_amount=charge.auto_amount,
        adjustment_amount=charge.adjustment_amount,
        final_amount=charge.final_amount,
        status=charge.status,
        status_label=charge_status_label(charge),
        adjustment_reason=charge.adjustment_reason or "",
        is_transferred=charge.billing_charge_line_id is not None,
        transferred_amount=charge.transferred_amount,
        care_time_category_label=(
            charge.care_time_category_snapshot.label if charge.care_time_category_snapshot else "レガシー"
        ),
        normal_time_label=(
            f"{charge.normal_start_at.strftime('%H:%M')}〜{charge.normal_end_at.strftime('%H:%M')}"
            if charge.normal_start_at and charge.normal_end_at
            else ""
        ),
        morning_extended_minutes=charge.morning_extended_minutes,
        morning_amount=charge.morning_amount,
        evening_extended_minutes=charge.evening_extended_minutes,
        evening_amount=charge.evening_amount,
        warning=warning,
    )


def _ensure_not_transferred(charge: ExtendedCareCharge) -> None:
    if charge.billing_charge_line_id is not None:
        raise ValueError("請求へ転送済みです。先に対象月の請求転送を解除してください。")
