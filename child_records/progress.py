"""Period selection for progress records written after the reporting period."""
from datetime import date, timedelta
import re

from fastapi import HTTPException

from models import ChildStatus


def month_end(value: date) -> date:
    return date(value.year + (value.month == 12), value.month % 12 + 1, 1) - timedelta(days=1)


def target_month(raw: str, today: date) -> date:
    if not raw:
        return today.replace(day=1) - timedelta(days=1)
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", raw):
        raise HTTPException(422, "対象月を正しく入力してください")
    try:
        value = date.fromisoformat(raw + "-01")
        if not 1901 <= value.year <= 2100:
            raise ValueError
        return month_end(value)
    except ValueError as exc:
        raise HTTPException(422, "対象月を正しく入力してください") from exc


def fiscal_year(value: date) -> int:
    return value.year if value.month >= 4 else value.year - 1


def age_key(child, target: date) -> str:
    april = date(fiscal_year(target), 4, 1)
    age = max(0, april.year - child.birth_date.year - (
        (april.month, april.day) < (child.birth_date.month, child.birth_date.day)
    ))
    return f"age_{age}" if age <= 4 else "final_year"


def cycle_key(start: date, end: date) -> str:
    # Independent of when or how the record is opened, including old manual URLs.
    return f"fy{fiscal_year(start)}:{start.isoformat()}:{end.isoformat()}"


def containing_cycle(child, config: dict, target: date) -> dict:
    year = fiscal_year(target)
    age = age_key(child, target)
    rule = config.get("age_rules", {}).get(age, {}).get("child_progress_record", {})
    interval = min(12, max(1, int(rule.get("interval_months") or 3)))
    fiscal_index = year * 12 + 3
    offset = ((target.year * 12 + target.month - 1 - fiscal_index) // interval) * interval
    start_index = fiscal_index + offset
    next_index = start_index + interval
    start = date(start_index // 12, start_index % 12 + 1, 1)
    end = min(date(next_index // 12, next_index % 12 + 1, 1) - timedelta(days=1), date(year + 1, 3, 31))
    return {"fiscal_year": year, "age_key": age, "interval_months": interval,
            "period_start": start, "period_end": end, "cycle_key": cycle_key(start, end)}


def cycle_ending_by(child, config: dict, end: date) -> dict:
    cycle = containing_cycle(child, config, end)
    if cycle["period_end"] > end:
        cycle = containing_cycle(child, config, cycle["period_start"] - timedelta(days=1))
    return cycle


def in_period(child, start: date, end: date) -> bool:
    if child.enrollment_date > end:
        return False
    if child.withdrawal_date is not None:
        return child.withdrawal_date >= start
    # An unknown leaving date is not evidence of enrollment during a past period.
    return child.status == ChildStatus.enrolled


def validate_period(start: date, end: date) -> None:
    if not (1901 <= start.year <= 2100 and 1901 <= end.year <= 2100):
        raise HTTPException(422, "対象期間は1901年から2100年までで指定してください")
    if start > end:
        raise HTTPException(422, "対象期間の開始日と終了日を確認してください")
    if (end - start).days > 370:
        raise HTTPException(422, "児童票の対象期間は1年以内にしてください")


def period_context(child, config: dict, start: date, end: date, today: date) -> dict:
    previous = containing_cycle(child, config, start - timedelta(days=1))
    following = containing_cycle(child, config, end + timedelta(days=1))
    current = containing_cycle(child, config, start)
    latest = cycle_ending_by(child, config, today.replace(day=1) - timedelta(days=1))
    return {
        "selected_target_month": end.strftime("%Y-%m"),
        "previous_target_month": previous["period_end"].strftime("%Y-%m"),
        "next_target_month": following["period_end"].strftime("%Y-%m"),
        "period_start": start, "period_end": end,
        "period_fiscal_year": fiscal_year(start),
        "interval_months": current["interval_months"],
        "is_latest_period": (start, end) == (latest["period_start"], latest["period_end"]),
        "today": today,
    }
