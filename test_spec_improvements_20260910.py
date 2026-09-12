from datetime import date, datetime, timezone
import re

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import Session, select

from auth import Role, StaffUser
from csrf import CsrfTokenMiddleware, verify_csrf
from models import (
    AttendanceRecord, AttendancePickupHistory, ChildCareCertification, CareTimeCategory,
    ExtendedCareCalculationSetting, ExtendedCareCharge, ExtendedCareFeeRule,
    Event, CalendarUserPreference,
)
import routers.attendance as attendance
import test_extended_care_fees as fee_tests
import test_calendar_feature as calendar_tests


@pytest.fixture
def pilot():
    case = fee_tests.ExtendedCareFeeTests()
    case.setUp()
    with Session(case.engine) as session:
        record = AttendanceRecord(child_id=case.child_id, attendance_date=date(2026, 9, 10),
                                  check_in_at=datetime(2026, 9, 10, 9), planned_pickup_time="17:00",
                                  pickup_person="母", snack_required=True)
        session.add(record)
        session.commit()
        case.record_id = record.id
    yield case
    case.tearDown()


def pickup_form(pilot):
    response = pilot.client.get(f"/attendance/{pilot.child_id}/pickup?date=2026-09-10")
    assert response.status_code == 200
    revision = re.search(r'name="revision" value="([^"]+)"', response.text).group(1)
    return {"date": "2026-09-10", "revision": revision, "planned_pickup_time": "18:30",
            "pickup_person": "祖母", "return_query": "date=2026-09-10&classroom_id=1"}


def test_pickup_update_history_and_stale_submission(pilot):
    values = pickup_form(pilot)
    response = pilot.client.post(f"/attendance/{pilot.child_id}/pickup", data=values, follow_redirects=False)
    assert response.status_code == 303
    assert "classroom_id=1" in response.headers["location"]
    with Session(pilot.engine) as session:
        record = session.get(AttendanceRecord, pilot.record_id)
        assert (record.planned_pickup_time, record.pickup_person) == ("18:30", "祖母")
        assert record.check_in_at == datetime(2026, 9, 10, 9)
        assert record.check_out_at is None and record.snack_required
        assert not session.exec(select(ExtendedCareCharge)).all()
        history = session.exec(select(AttendancePickupHistory)).one()
        assert (history.previous_time, history.previous_person, history.new_time, history.new_person) == ("17:00", "母", "18:30", "祖母")
        assert history.changed_by_name == pilot.current_user.name
    stale = pilot.client.post(f"/attendance/{pilot.child_id}/pickup", data={**values, "pickup_person": "父"})
    assert stale.status_code == 409 and "最新の内容" in stale.text
    assert 'value="祖母"' in stale.text
    # A deliberate save with no changes must not manufacture another history entry.
    assert pilot.client.post(f"/attendance/{pilot.child_id}/pickup", data=pickup_form(pilot)).status_code == 200
    with Session(pilot.engine) as session:
        assert len(session.exec(select(AttendancePickupHistory)).all()) == 1


@pytest.mark.parametrize("changes", [{"planned_pickup_time": "25:00"}, {"planned_pickup_time": "09:00:30"},
                                      {"pickup_person": ""}, {"pickup_person": "x" * 101}])
def test_pickup_invalid_values_do_not_write(pilot, changes):
    response = pilot.client.post(f"/attendance/{pilot.child_id}/pickup", data={**pickup_form(pilot), **changes})
    assert response.status_code == 400
    with Session(pilot.engine) as session:
        assert session.get(AttendanceRecord, pilot.record_id).pickup_person == "母"
        assert not session.exec(select(AttendancePickupHistory)).all()


def test_pickup_requires_edit_permission_and_existing_attendance(pilot):
    values = pickup_form(pilot)
    assert pilot.client.get(f"/attendance/{pilot.child_id}/pickup?date=2026-09-11").status_code == 400
    pilot.current_user = StaffUser(role=Role.VIEW_ONLY, name="閲覧職員")
    assert pilot.client.get(f"/attendance/{pilot.child_id}/pickup?date=2026-09-10").status_code == 403
    assert pilot.client.post(f"/attendance/{pilot.child_id}/pickup", data=values).status_code == 403
    assert "お迎え予定を変更" not in pilot.client.get("/attendance/?date=2026-09-10").text


def test_pickup_requires_csrf(pilot, monkeypatch):
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "1")
    monkeypatch.setenv("HOIKUICT_COOKIE_SECURE", "0")
    app = FastAPI(dependencies=[Depends(verify_csrf)])
    app.add_middleware(CsrfTokenMiddleware)
    app.include_router(attendance.router)
    app.dependency_overrides = pilot.app.dependency_overrides.copy()
    values = pickup_form(pilot)
    with TestClient(app) as client:
        assert client.post(f"/attendance/{pilot.child_id}/pickup", data=values).status_code == 403
        form = client.get(f"/attendance/{pilot.child_id}/pickup?date=2026-09-10")
        token = re.search(r'name="csrf_token" value="([^"]+)"', form.text).group(1)
        response = client.post(f"/attendance/{pilot.child_id}/pickup", data={**values, "csrf_token": token})
        assert response.status_code == 200, response.text


def test_uncalculated_reasons_and_read_only_render(pilot):
    with Session(pilot.engine) as session:
        record = session.get(AttendanceRecord, pilot.record_id)
        record.check_out_at = datetime(2026, 9, 10, 10)
        session.add(record)
        session.add(ExtendedCareCalculationSetting(mode="category_aware", category_aware_from=date(2026, 4, 1)))
        session.commit()
    queries = []
    def count_query(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)
    event.listen(pilot.engine, "before_cursor_execute", count_query)
    try:
        response = pilot.client.get("/attendance/?date=2026-09-10")
    finally:
        event.remove(pilot.engine, "before_cursor_execute", count_query)
    assert "料金未算出" in response.text and "有効な保育認定がありません" in response.text
    assert "理由・設定を確認" in response.text
    assert all(not query.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries)
    with Session(pilot.engine) as session:
        session.add(ChildCareCertification(child_id=pilot.child_id, care_time_category=CareTimeCategory.short,
                                          effective_from=date(2026, 4, 1)))
        session.commit()
    assert "の料金ルールがありません" in pilot.client.get("/attendance/?date=2026-09-10").text


def rule_values(category):
    return {"name": f"{category}延長", "care_time_category": category, "effective_from": "2026-01-01",
            "start_time": "18:00", "normal_start_time": "08:30", "normal_end_time": "16:30",
            "grace_minutes": "0", "rounding_minutes": "15", "unit_price": "100",
            "morning_enabled": "1", "morning_grace_minutes": "0", "morning_rounding_minutes": "15",
            "morning_unit_price": "100", "evening_enabled": "1", "is_active": "1"}


def test_separate_category_rules_and_morning_only_update(pilot):
    for category in ("standard", "short"):
        assert pilot.client.post("/extended-care-fees/settings", data=rule_values(category), follow_redirects=False).status_code == 303
    duplicate = pilot.client.post("/extended-care-fees/settings", data=rule_values("short"))
    assert duplicate.status_code == 400 and "保育必要量を選択" in duplicate.text
    with Session(pilot.engine) as session:
        rule = session.exec(select(ExtendedCareFeeRule).where(ExtendedCareFeeRule.care_time_category == CareTimeCategory.short)).one()
        rule_id = rule.id
    values = rule_values("short")
    del values["evening_enabled"]
    assert pilot.client.post(f"/extended-care-fees/settings/{rule_id}", data=values, follow_redirects=False).status_code == 303
    with Session(pilot.engine) as session:
        rule = session.get(ExtendedCareFeeRule, rule_id)
        assert rule.morning_enabled and not rule.evening_enabled
    error = pilot.client.post(f"/extended-care-fees/settings/{rule_id}", data={**values, "normal_end_time": "07:00"})
    assert error.status_code == 400 and f'action="/extended-care-fees/settings/{rule_id}"' in error.text
    assert 'name="normal_end_time" value="07:00"' in error.text


def test_day_navigation_includes_overnight_events_and_respects_visibility():
    case = calendar_tests.CalendarFeatureTests()
    case.setUp()
    try:
        case._login(case.user_a_id)
        with Session(case.engine) as session:
            session.add(Event(calendar_id=case.shared_calendar_id, created_by_user_id=case.user_a_id,
                              title="前日からの予定", start_at=datetime(2026, 9, 9, 14, tzinfo=timezone.utc),
                              end_at=datetime(2026, 9, 10, 1, tzinfo=timezone.utc)))
            session.add(Event(calendar_id=case.b_personal_id, created_by_user_id=case.user_b_id,
                              title="他の職員だけの予定", start_at=datetime(2026, 9, 10, 0, tzinfo=timezone.utc),
                              end_at=datetime(2026, 9, 10, 1, tzinfo=timezone.utc)))
            session.commit()
        month = case.client.get("/calendar?date=2026-09-10")
        assert 'href="/calendar?mode=day&date=2026-09-10"' in month.text
        daily = case.client.get("/calendar/view?mode=day&date=2026-09-10")
        assert "前日からの予定" in daily.text and "前日以前から継続" in daily.text
        assert "他の職員だけの予定" not in daily.text
        assert "月表示に戻る" in daily.text
        with Session(case.engine) as session:
            preference = session.exec(select(CalendarUserPreference).where(
                CalendarUserPreference.user_id == case.user_a_id,
                CalendarUserPreference.calendar_id == case.shared_calendar_id,
            )).one()
            preference.is_visible = False
            session.add(preference)
            session.commit()
        hidden = case.client.get("/calendar/view?mode=day&date=2026-09-10")
        assert "前日からの予定" not in hidden.text and "この日の予定はありません" in hidden.text
    finally:
        case.tearDown()
