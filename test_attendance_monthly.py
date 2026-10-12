from datetime import date, datetime, timedelta
import html
import json
import re
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import attendance_monthly_service as service
from auth import Role, StaffUser, get_current_staff_user
from database import get_session
from extended_care_fee_service import recalculate_attendance_charge
from models import (AttendanceCorrection, AttendanceRecord, AttendanceVerification,
                    AttendanceVerificationStatus, Child, Classroom, DailyContactEntry,
                    ExtendedCareCharge, ExtendedCareChargeStatus, ExtendedCareFeeRule,
                    ParentAccount, ParentContactType, User)
from routers.attendance import router


@pytest.fixture
def nursery(monkeypatch):
    monkeypatch.setattr(service, "local_today", lambda: date(2026, 10, 4))
    monkeypatch.setattr(service, "local_naive_now", lambda: datetime(2026, 10, 4, 12))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    state = {"actor": StaffUser(role=Role.ADMIN, name="検証園長", user_id=uuid4())}
    with Session(engine) as session:
        session.connection().exec_driver_sql("PRAGMA foreign_keys=ON")
        session.add(User(id=state["actor"].user_id, email="monthly@example.test", display_name="検証園長", staff_role="admin"))
        room = Classroom(name="架空くるみ")
        session.add(room)
        session.flush()
        child = Child(last_name="架空", first_name="園児A", last_name_kana="カクウ", first_name_kana="エー",
                      birth_date=date(2022, 1, 1), enrollment_date=date(2026, 4, 1), classroom_id=room.id)
        session.add(child)
        session.flush()
        state["child_id"] = child.id
        session.add(ExtendedCareFeeRule(name="試験料金", effective_from=date(2026, 1, 1)))
        for day in (1, 2, 3, 4):
            session.add(AttendanceVerification(child_id=child.id, target_date=date(2026, 9, day),
                        status=AttendanceVerificationStatus.present, updated_by_name="検証職員"))
        session.add(AttendanceRecord(child_id=child.id, attendance_date=date(2026, 9, 2),
                    check_in_at=datetime(2026, 9, 2, 8, 31, 47), planned_pickup_time="17:00",
                    pickup_person="母", snack_required=True, pickup_snack_confirmed=True))
        session.add(AttendanceRecord(child_id=child.id, attendance_date=date(2026, 9, 3),
                    check_out_at=datetime(2026, 9, 3, 17, 0, 22), actual_pickup_person="父"))
        session.commit()
    app = FastAPI()
    app.include_router(router)
    def sessions():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_current_staff_user] = lambda: state["actor"]
    with TestClient(app) as client:
        yield client, engine, state
    engine.dispose()


def page(client, state, month="2026-09"):
    response = client.get(f"/attendance/monthly?month={month}&child_id={state['child_id']}")
    assert response.status_code == 200, response.text
    return response, json.loads(html.unescape(re.search(r'data-state="([^"]+)"', response.text).group(1)))


def item(data, day, **changes):
    row = next(row for row in data["rows"] if row["date"] == day)
    return {"date": day, "revision": row["revision"], "arrival": row["arrival"],
            "departure": row["departure"], "next_day": row["next_day"], **changes}


def post(client, state, items, *, bulk=True, reason="職員の記録で確認"):
    path = f"/attendance/monthly/{state['child_id']}/"
    if bulk:
        body = {"month": "2026-09", "payload": json.dumps(items), "reason": reason}
    else:
        body = {"month": "2026-09", "reason": reason, **items[0]}
    return client.post(path + ("bulk" if bulk else "day"), data=body, follow_redirects=False)


def test_month_includes_no_record_days_and_read_is_side_effect_free(nursery):
    client, engine, state = nursery
    response, data = page(client, state)
    assert response.headers["cache-control"] == "private, no-store"
    assert len(data["rows"]) == 30
    assert data["rows"][0]["bulk_eligible"]
    assert data["rows"][4]["bulk_optional"]
    assert '管理者：まとめて補完' in response.text
    with Session(engine) as session:
        assert len(session.exec(select(AttendanceRecord)).all()) == 2
        assert not session.exec(select(AttendanceCorrection)).all()


def test_admin_bulk_fills_all_three_missing_shapes_with_audit_and_fees(nursery):
    client, engine, state = nursery
    _, data = page(client, state)
    payload = [item(data, "2026-09-01", arrival="08:30", departure="18:21"),
               item(data, "2026-09-02", departure="17:10"),
               item(data, "2026-09-03", arrival="08:10")]
    response = post(client, state, payload)
    assert response.status_code == 303, response.text
    with Session(engine) as session:
        records = {r.attendance_date.day: r for r in session.exec(select(AttendanceRecord)).all()}
        assert records[1].check_in_at == datetime(2026, 9, 1, 8, 30)
        assert records[2].check_in_at.second == 47
        assert records[3].check_out_at.second == 22
        assert records[2].planned_pickup_time == "17:00"
        assert records[2].pickup_person == "母" and records[2].snack_required
        assert records[3].actual_pickup_person == "父"
        histories = session.exec(select(AttendanceCorrection)).all()
        assert len(histories) == 3
        assert {h.operation for h in histories} == {"missing_fill"}
        assert {h.changed_by_user_id for h in histories} == {state["actor"].user_id}
        assert len({h.previous_values["_time_correction"]["batch_id"] for h in histories}) == 1
        charges = {r.target_date.day: r for r in session.exec(select(ExtendedCareCharge)).all()}
        assert charges[1].final_amount == 200
        assert charges[2].final_amount == charges[3].final_amount == 0
    assert post(client, state, payload).status_code == 409


@pytest.mark.parametrize("role,bulk,status", [(Role.CAN_EDIT, True, 403), (Role.VIEW_ONLY, True, 403),
                                            (Role.VIEW_ONLY, False, 403), (Role.CAN_EDIT, False, 303)])
def test_permissions_enforced_by_post(nursery, role, bulk, status):
    client, engine, state = nursery
    _, data = page(client, state)
    state["actor"].role = role
    response = post(client, state, [item(data, "2026-09-01", arrival="08:30", departure="17:00")], bulk=bulk)
    assert response.status_code == status
    response, _ = page(client, state)
    assert 'id="open-bulk"' not in response.text


@pytest.mark.parametrize("changes", [
    {"arrival": "09:00", "departure": "08:00"},
    {"arrival": "wrong", "departure": "17:00"},
    {"arrival": "08:00", "departure": "04:00", "next_day": True},
    {"arrival": "08:00", "departure": "17:00", "next_day": "false"},
])
def test_invalid_second_day_rolls_back_entire_batch(nursery, changes):
    client, engine, state = nursery
    _, data = page(client, state)
    response = post(client, state, [item(data, "2026-09-01", arrival="08:30", departure="17:00"),
                                    item(data, "2026-09-04", **changes)])
    assert response.status_code == 400
    with Session(engine) as session:
        assert len(session.exec(select(AttendanceRecord)).all()) == 2
        assert not session.exec(select(AttendanceCorrection)).all()


def test_existing_punch_cannot_be_overwritten_in_bulk(nursery):
    client, engine, state = nursery
    _, data = page(client, state)
    response = post(client, state, [item(data, "2026-09-02", arrival="07:00", departure="17:00")])
    assert response.status_code == 400
    assert "既存の打刻" in response.text


@pytest.mark.parametrize("absent_kind", ["verification", "contact"])
def test_absence_excluded_and_cannot_be_forged_into_bulk(nursery, absent_kind):
    client, engine, state = nursery
    with Session(engine) as session:
        if absent_kind == "verification":
            verification = session.exec(select(AttendanceVerification).where(AttendanceVerification.target_date == date(2026, 9, 1))).one()
            verification.status = AttendanceVerificationStatus.sick_absent
            session.add(verification)
        else:
            parent = ParentAccount(email="monthly-parent@example.test", display_name="架空保護者")
            session.add(parent)
            session.flush()
            session.add(DailyContactEntry(child_id=state["child_id"], target_date=date(2026, 9, 1),
                        parent_account_id=parent.id, contact_type=ParentContactType.absent_sick))
        session.commit()
    _, data = page(client, state)
    assert not data["rows"][0]["bulk_eligible"]
    response = post(client, state, [item(data, "2026-09-01", arrival="08:00", departure="17:00")])
    assert response.status_code == 400


def test_stale_evidence_keeps_inputs_and_changes_nothing(nursery):
    client, engine, state = nursery
    _, data = page(client, state)
    with Session(engine) as session:
        verification = session.exec(select(AttendanceVerification).where(AttendanceVerification.target_date == date(2026, 9, 1))).one()
        verification.status = AttendanceVerificationStatus.sick_absent
        session.add(verification)
        session.commit()
    response = post(client, state, [item(data, "2026-09-01", arrival="08:30", departure="17:00")])
    assert response.status_code == 409
    rendered = json.loads(html.unescape(re.search(r'data-state="([^"]+)"', response.text).group(1)))
    assert rendered["draft"]["items"][0]["arrival"] == "08:30"
    with Session(engine) as session:
        assert not session.exec(select(AttendanceCorrection)).all()


@pytest.mark.parametrize("status", list(ExtendedCareChargeStatus))
def test_fee_state_protection_and_draft_recalculation(nursery, status):
    client, engine, state = nursery
    with Session(engine) as session:
        record = session.exec(select(AttendanceRecord).where(AttendanceRecord.attendance_date == date(2026, 9, 3))).one()
        charge = recalculate_attendance_charge(session, record)
        charge.status = status
        session.add(charge)
        session.commit()
    _, data = page(client, state)
    response = post(client, state, [item(data, "2026-09-03", arrival="08:30")])
    assert response.status_code == (303 if status == ExtendedCareChargeStatus.draft else 409), response.text
    with Session(engine) as session:
        charge = session.exec(select(ExtendedCareCharge)).one()
        assert charge.status == status


def test_manual_edit_updates_fee_and_shows_history(nursery):
    client, engine, state = nursery
    _, data = page(client, state)
    assert post(client, state, [item(data, "2026-09-03", arrival="08:30", departure="18:21")], bulk=False).status_code == 303
    response, data = page(client, state)
    assert data["rows"][2]["fee"] == 200
    assert data["rows"][2]["history"][0]["label"] == "時刻の補記・修正"


@pytest.mark.parametrize("reason", ["", " " * 5, "x" * 501])
def test_reason_required(nursery, reason):
    client, engine, state = nursery
    _, data = page(client, state)
    assert post(client, state, [item(data, "2026-09-01", arrival="08:30")], reason=reason).status_code == 400


def test_future_and_outside_month_rejected(nursery):
    client, engine, state = nursery
    _, data = page(client, state, "2026-10")
    response = client.post(f"/attendance/monthly/{state['child_id']}/bulk", data={
        "month": "2026-10", "payload": json.dumps([item(data, "2026-10-05", arrival="08:00")]),
        "reason": "確認"}, follow_redirects=False)
    assert response.status_code == 400
    _, data = page(client, state)
    entry = item(data, "2026-09-01", arrival="08:30")
    entry["date"] = "2026-08-31"
    assert post(client, state, [entry]).status_code == 400


def test_duplicate_dates_rejected(nursery):
    client, engine, state = nursery
    _, data = page(client, state)
    entry = item(data, "2026-09-01", arrival="08:30")
    assert post(client, state, [entry, entry]).status_code == 400


def test_time_deletion_rejected_and_overnight_supported(nursery):
    client, engine, state = nursery
    _, data = page(client, state)
    assert post(client, state, [item(data, "2026-09-02", arrival="", departure="17:00")], bulk=False).status_code == 400
    assert post(client, state, [item(data, "2026-09-01", arrival="09:00", departure="01:00", next_day=True)]).status_code == 303
    with Session(engine) as session:
        row = session.exec(select(AttendanceRecord).where(AttendanceRecord.attendance_date == date(2026, 9, 1))).one()
        assert row.check_out_at == datetime(2026, 9, 2, 1)


def test_date_mismatch_can_be_explicitly_repaired(nursery):
    client, engine, state = nursery
    with Session(engine) as session:
        row = session.exec(select(AttendanceRecord).where(AttendanceRecord.attendance_date == date(2026, 9, 2))).one()
        row.check_in_at += timedelta(days=30)
        session.add(row)
        session.commit()
    _, data = page(client, state)
    assert data["rows"][1]["date_mismatch"]
    entry = item(data, "2026-09-02", departure="17:00")
    assert post(client, state, [entry], bulk=False).status_code == 400
    entry["repair_dates"] = True
    assert post(client, state, [entry], bulk=False).status_code == 303


def test_runtime_failure_rolls_back_prior_days(nursery, monkeypatch):
    client, engine, state = nursery
    _, data = page(client, state)
    real = service.recalculate_attendance_charge
    def fail_second(session, record):
        if record.attendance_date.day == 4:
            raise ValueError("料金計算の試験エラー")
        return real(session, record)
    monkeypatch.setattr(service, "recalculate_attendance_charge", fail_second)
    response = post(client, state, [item(data, "2026-09-01", arrival="08:30", departure="17:00"),
                                    item(data, "2026-09-04", arrival="08:30", departure="17:00")])
    assert response.status_code == 400
    with Session(engine) as session:
        assert len(session.exec(select(AttendanceRecord)).all()) == 2
        assert not session.exec(select(AttendanceCorrection)).all()
        assert not session.exec(select(ExtendedCareCharge)).all()


def test_concurrent_bulk_requests_save_once(nursery, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import sqlite3
    client, engine, state = nursery
    _, data = page(client, state)
    payload = [item(data, "2026-09-01", arrival="08:30", departure="17:00")]
    path = tmp_path / "concurrent.sqlite"
    with sqlite3.connect(path) as target:
        connection = engine.raw_connection()
        try:
            connection.driver_connection.backup(target)
        finally:
            connection.close()
    independent = create_engine("sqlite:///" + str(path), connect_args={"check_same_thread": False, "timeout": 10})
    def attempt():
        with Session(independent) as session:
            try:
                service.save_times(session, child_id=state["child_id"], month="2026-09",
                                   items=payload, reason="時刻確認済み", actor=state["actor"], bulk=True)
                return 303
            except service.AttendanceEditError as exc:
                session.rollback()
                return exc.status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: attempt(), range(2))) == [303, 409]
        with Session(independent) as session:
            assert len(session.exec(select(AttendanceCorrection)).all()) == 1
            assert len(session.exec(select(ExtendedCareCharge)).all()) == 1
    finally:
        independent.dispose()


def test_csrf_required_for_real_form_posts(nursery, monkeypatch):
    from fastapi import Depends
    from csrf import CsrfTokenMiddleware, verify_csrf, CSRF_COOKIE_NAME
    client, engine, state = nursery
    _, data = page(client, state)
    app = FastAPI(dependencies=[Depends(verify_csrf)])
    app.add_middleware(CsrfTokenMiddleware)
    app.include_router(router)
    app.dependency_overrides.update(client.app.dependency_overrides)
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "1")
    monkeypatch.setenv("HOIKUICT_COOKIE_SECURE", "0")
    with TestClient(app) as secure:
        page(secure, state)
        body = {"month": "2026-09", "payload": json.dumps([item(data, "2026-09-01", arrival="08:30")]),
                "reason": "確認済み"}
        url = f"/attendance/monthly/{state['child_id']}/bulk"
        assert secure.post(url, data=body).status_code == 403
        body["csrf_token"] = secure.cookies[CSRF_COOKIE_NAME]
        assert secure.post(url, data=body, follow_redirects=False).status_code == 303


def test_correction_history_labels_and_monthly_return(nursery):
    client, engine, state = nursery
    _, data = page(client, state)
    assert post(client, state, [item(data, "2026-09-01", arrival="08:30", departure="17:00")]).status_code == 303
    response = client.get(f"/attendance/{state['child_id']}/correction", params={
        "date": "2026-09-01", "return_to": "monthly",
        "return_query": f"month=2026-09&child_id={state['child_id']}"})
    assert response.status_code == 200
    assert "管理者の一括補完" in response.text and "変更後の登園" in response.text
    assert "園児別・月間修正に戻る" in response.text
