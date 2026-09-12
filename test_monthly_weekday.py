from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from calendar_service import generate_series_instances, monthly_weekday_date
from models import Event, RecurrenceFrequency, RecurrenceRule
from routers.calendar import _recurrence_rule_from_form


@pytest.mark.parametrize("expression,expected", [("1MO", "2026-09-07"), ("2TU", "2026-09-08"), ("5TU", "2026-09-29"), ("5MO", None), ("-1MO", "2026-09-28"), ("6MO", None)])
def test_monthly_ordinal_boundaries(expression, expected):
    actual = monthly_weekday_date(2026, 9, expression)
    assert (actual.isoformat() if actual else None) == expected


@pytest.mark.parametrize("expression,start,expected", [
    ("1MO", "2026-09-08", ["2026-10-05", "2026-11-02", "2026-12-07"]),
    ("5MO", "2026-09-01", ["2026-11-30", "2027-03-29", "2027-05-31"]),
    ("-1MO", "2026-09-01", ["2026-09-28", "2026-10-26", "2026-11-30"]),
])
def test_series_skips_missing_months_and_counts_actual_occurrences(expression, start, expected):
    event = Event(title="曜日の検証", start_at=datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
                  end_at=datetime.fromisoformat(start).replace(hour=1, tzinfo=timezone.utc), timezone="Asia/Tokyo")
    rule = RecurrenceRule(freq=RecurrenceFrequency.monthly, by_weekday=expression, count=3, timezone="Asia/Tokyo")
    instances = generate_series_instances(event, rule, datetime(2026, 9, 1, tzinfo=timezone.utc), datetime(2027, 7, 1, tzinfo=timezone.utc))
    assert [start.date().isoformat() for _, start, _ in instances] == expected


def test_monthly_rule_saves_and_switches_back_to_date():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    args = dict(existing=None, recurrence_mode="monthly", recurrence_interval=1,
                recurrence_by_weekday="", recurrence_by_month_day="8", recurrence_count="3", recurrence_until="", timezone_name="Asia/Tokyo")
    with Session(engine) as session:
        rule = _recurrence_rule_from_form(session, **args, recurrence_monthly_weekday="2TU")
        assert rule.by_weekday == "2TU" and rule.by_month_day is None
        session.commit()
        args["existing"] = rule
        rule = _recurrence_rule_from_form(session, **args, recurrence_monthly_weekday="")
        assert rule.by_weekday is None and rule.by_month_day == "8"
        with pytest.raises(HTTPException):
            _recurrence_rule_from_form(session, **args, recurrence_monthly_weekday="6MO")
    engine.dispose()
