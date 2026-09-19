"""Agreed parent/kiosk workflow, including cancellation, stale screens and late pickup."""
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, create_engine, select

import database
import guardian_arrival
from attendance_correction_service import cancel_punch, correction_revision
from models import (
    AttendanceCorrection, AttendancePickupHistory, AttendanceRecord, AttendanceVerification,
    AttendanceVerificationStatus, DailyContactEntry,
)
from pickup_plan_service import save_pickup_plan
from routers import guardian
import test_spec_changes_20260917 as shared_fixtures

workbench = shared_fixtures.workbench


def parent_submit(w, **overrides):
    data = dict(date=str(w.day), attendance_mode="present", temperature="36.5", care_fields_version="1",
                bedtime="21:00", wakeup_time="06:30", breakfast_status="完食", breakfast_contents="ごはん、卵",
                sleep_notes="よく眠れた", stool_consistency="normal", stool_count="1",
                pickup_fields_version="1", pickup_revision="new", planned_pickup_time="22:45",
                pickup_person="母", snack_required="0")
    data.update(overrides)
    return w.client.post(f"/parent-portal/children/{w.child}/contact", data=data, follow_redirects=False)


def start(w):
    response = w.client.post(f"/guardian/child/{w.child}/check-in", data={"date": str(w.day), "class_id": w.classroom}, follow_redirects=False)
    assert response.status_code == 200, response.text
    return response


def arrival_values(w, started, **overrides):
    values = dict(date=str(w.day), class_id=w.classroom, arrival_token=started.context["arrival_token"],
                  revision=started.context["pickup_revision"], planned_pickup_time="22:15", pickup_person="母", snack_required="0")
    values.update(overrides)
    return values


def test_parent_contact_and_plan_save_together_with_all_care_fields(workbench):
    w = workbench
    page = w.client.get(f"/parent-portal/children/{w.child}/contact?date={w.day}")
    assert page.context["pickup_values"]["pickup_revision"] == "new"
    for field in ("sleep_notes", "bedtime", "wakeup_time", "breakfast_contents", "stool_count", "contact_note"):
        assert f'name="{field}"' in page.text
    assert parent_submit(w).status_code == 303
    with Session(w.engine) as session:
        record = session.exec(select(AttendanceRecord)).one()
        contact = session.exec(select(DailyContactEntry)).one()
        assert record.planned_pickup_time == "22:45" and record.pickup_person == "母"
        assert record.check_in_at is None and record.check_out_at is None
        assert record.pickup_snack_confirmed and record.snack_required is False
        assert contact.sleep_notes == "よく眠れた" and contact.extra_data["breakfast_contents"] == "ごはん、卵"
        assert contact.extra_data["bedtime"] == "21:00"
        assert session.exec(select(AttendancePickupHistory)).one().changed_by_parent_account_id == w.parent
    page = w.client.get(f"/parent-portal/children/{w.child}/contact?date={w.day}")
    assert page.context["pickup_values"]["planned_pickup_time"] == "22:45"
    kiosk = w.client.get(f"/guardian/?date={w.day}&child_id={w.child}")
    assert "登園する" in kiosk.text and "降園する" not in kiosk.text
    assert start(w).template.name == "guardian/pickup_confirm.html"


@pytest.mark.parametrize("time_value,person,snack,exists", [("", "", "", False), ("17:00", "", "", True),
    ("", "父", "", True), ("", "", "0", True), ("17:00", "母", "", True)])
def test_optional_partial_plan_is_saved_and_completed_at_kiosk(workbench, time_value, person, snack, exists):
    w = workbench
    assert parent_submit(w, planned_pickup_time=time_value, pickup_person=person, snack_required=snack).status_code == 303
    with Session(w.engine) as session:
        record = session.exec(select(AttendanceRecord)).first()
        assert bool(record) == exists
        if record:
            assert record.pickup_snack_confirmed == (snack != "")
            assert record.check_in_at is None
    response = start(w)
    assert response.template.name == "guardian/pickup_form.html"
    assert response.context["pickup_values"] == dict(planned_pickup_time=time_value, pickup_person=person, snack_required=snack)


@pytest.mark.parametrize("overrides", [{"temperature": "37.5"}, {"planned_pickup_time": "24:00"},
    {"planned_pickup_time": "", "pickup_hour": "17"}, {"snack_required": "invalid"}])
def test_invalid_contact_or_plan_saves_neither(workbench, overrides):
    w = workbench
    response = parent_submit(w, **overrides)
    assert response.status_code in {200, 400}
    assert "role=\"alert\"" in response.text
    assert response.context["form_data"]["sleep_notes"] == "よく眠れた"
    with Session(w.engine) as session:
        assert session.exec(select(AttendanceRecord)).all() == []
        assert session.exec(select(DailyContactEntry)).all() == []
        assert session.exec(select(AttendancePickupHistory)).all() == []


def test_absence_does_not_write_pickup_plan(workbench):
    w = workbench
    assert parent_submit(w, attendance_mode="absent", absence_reason="absent_private", absence_note="家庭の都合").status_code == 303
    with Session(w.engine) as session:
        assert session.exec(select(AttendanceRecord)).all() == []
        assert session.exec(select(DailyContactEntry)).one().absence_note == "家庭の都合"


def test_stale_contact_cannot_overwrite_pickup_or_partially_save_contact(workbench):
    w = workbench
    with Session(w.engine) as session:
        save_pickup_plan(session, child_id=w.child, day=w.day, revision="new", planned_pickup_time="18:00",
                         pickup_person="父", snack_required=True, source="staff", actor_name="担当職員")
        session.commit()
    assert parent_submit(w).status_code == 409
    with Session(w.engine) as session:
        assert session.exec(select(AttendanceRecord)).one().pickup_person == "父"
        assert session.exec(select(DailyContactEntry)).all() == []
        assert len(session.exec(select(AttendancePickupHistory)).all()) == 1


def test_closed_pickup_remains_read_only_on_contact_validation_error(workbench):
    w = workbench
    with Session(w.engine) as session:
        session.add(AttendanceRecord(child_id=w.child, attendance_date=w.day,
            check_in_at=datetime.combine(w.day, time(8)), check_out_at=datetime.combine(w.day, time(17)),
            planned_pickup_time="17:00", pickup_person="父", pickup_snack_confirmed=True))
        session.commit()
    response = parent_submit(w, pickup_fields_version="", temperature="37.5")
    assert response.context["pickup_editable"] is False
    assert response.context["pickup_values"]["planned_pickup_time"] == "17:00"
    assert response.context["pickup_values"]["pickup_person"] == "父"
    assert 'name="pickup_fields_version"' not in response.text
    assert parent_submit(w, pickup_fields_version="").status_code == 303
    with Session(w.engine) as session:
        assert session.exec(select(AttendanceRecord)).one().pickup_person == "父"
        assert session.exec(select(DailyContactEntry)).one().sleep_notes == "よく眠れた"


def test_parent_cannot_modify_other_family_or_past_pickup(workbench):
    w = workbench
    data = dict(date=str(w.day), attendance_mode="present", pickup_fields_version="1", pickup_revision="new")
    assert w.client.post(f"/parent-portal/children/{w.other}/contact", data=data).status_code == 404
    assert parent_submit(w, date=str(w.day - timedelta(days=1))).status_code == 409
    with Session(w.engine) as session:
        assert session.exec(select(AttendanceRecord)).all() == []


def test_arrival_preview_edit_cancel_do_not_write_and_commit_uses_first_time(workbench, monkeypatch):
    w = workbench
    first = datetime.combine(w.day, time(8, 12, 23))
    monkeypatch.setattr(guardian, "local_naive_now", lambda: first)
    started = start(w)
    values = arrival_values(w, started)
    confirmed = w.client.post(f"/guardian/child/{w.child}/pickup", data=values)
    assert confirmed.status_code == 200 and confirmed.context["arrival_at"] == first
    edited = w.client.post(f"/guardian/child/{w.child}/arrival/edit", data=values)
    assert edited.status_code == 200 and edited.context["pickup_values"]["planned_pickup_time"] == "22:15"
    assert edited.context["arrival_token"] == started.context["arrival_token"]
    w.client.get(f"/guardian?date={w.day}")  # Cancel returns to the class chooser.
    with Session(w.engine) as session:
        assert session.exec(select(AttendanceRecord)).all() == []
        assert session.exec(select(AttendancePickupHistory)).all() == []
    monkeypatch.setattr(guardian, "local_naive_now", lambda: first + timedelta(minutes=4))
    committed = w.client.post(f"/guardian/child/{w.child}/pickup/commit", data=values)
    assert committed.status_code == 200
    with Session(w.engine) as session:
        record = session.exec(select(AttendanceRecord)).one()
        assert record.check_in_at == first and record.planned_pickup_time == "22:15"
    assert w.client.post(f"/guardian/child/{w.child}/pickup/commit", data=values).status_code == 409


@pytest.mark.parametrize("change", ["signature", "child", "day", "expired", "device"])
def test_arrival_draft_rejects_tampering_expiry_and_other_targets(workbench, monkeypatch, change):
    w = workbench
    values = arrival_values(w, start(w))
    child = w.child
    if change == "signature":
        values["arrival_token"] += "0"
    elif change == "child":
        child = w.other
        values.pop("class_id")
    elif change == "day":
        values["date"] = str(w.day + timedelta(days=1))
    elif change == "expired":
        now = guardian_arrival.time.time()
        monkeypatch.setattr(guardian_arrival.time, "time", lambda: now + 601)
    else:
        # Use the actual cookie name; open test mode grants no extra authority.
        from kiosk_security import KIOSK_DEVICE_COOKIE
        w.client.cookies.set(KIOSK_DEVICE_COOKIE, "different-device")
    assert w.client.post(f"/guardian/child/{child}/pickup/commit", data=values).status_code == 409
    with Session(w.engine) as session:
        assert session.exec(select(AttendanceRecord)).all() == []


def test_arrival_rejects_plan_changed_after_first_button(workbench):
    w = workbench
    values = arrival_values(w, start(w))
    assert parent_submit(w).status_code == 303
    assert w.client.post(f"/guardian/child/{w.child}/pickup/commit", data=values).status_code == 409
    with Session(w.engine) as session:
        record = session.exec(select(AttendanceRecord)).one()
        assert record.check_in_at is None and record.planned_pickup_time == "22:45"


def test_arrival_requires_explicit_snack_choice(workbench):
    w = workbench
    values = arrival_values(w, start(w), snack_required="")
    for path in ("pickup", "pickup/commit"):
        assert w.client.post(f"/guardian/child/{w.child}/{path}", data=values).status_code == 400
    with Session(w.engine) as session:
        assert session.exec(select(AttendanceRecord)).all() == []


@pytest.mark.parametrize("existing_plan", [False, True])
def test_visual_presence_can_depart_without_inventing_arrival(workbench, existing_plan):
    w = workbench
    if existing_plan:
        assert parent_submit(w).status_code == 303
    with Session(w.engine) as session:
        session.add(AttendanceVerification(child_id=w.child, target_date=w.day, status=AttendanceVerificationStatus.present))
        session.commit()
    page = w.client.get(f"/guardian/?date={w.day}&child_id={w.child}")
    assert "降園する" in page.text and "登園する" not in page.text
    assert 'name="actual_pickup_person" value=""' in page.text
    url = f"/guardian/child/{w.child}/check-out/commit"
    assert w.client.post(url, data={"date": str(w.day)}).status_code == 400
    assert w.client.post(url, data={"date": str(w.day), "actual_pickup_person": "祖母"}, follow_redirects=False).status_code == 303
    with Session(w.engine) as session:
        record = session.exec(select(AttendanceRecord)).one()
        assert record.check_in_at is None and record.check_out_at is not None
        assert record.actual_pickup_person == "祖母"
        assert record.pickup_person == ("母" if existing_plan else None)
        cancel_punch(session, record, operation="check_out", reason="検証の取消", revision=correction_revision(record), actor=w.actor)
        assert record.actual_pickup_person is None and record.check_in_at is None
        assert session.exec(select(AttendanceCorrection)).one().previous_values["actual_pickup_person"] == "祖母"


@pytest.mark.parametrize("status", [AttendanceVerificationStatus.unknown, AttendanceVerificationStatus.private_absent])
def test_pickup_plan_without_presence_never_allows_departure(workbench, status):
    w = workbench
    assert parent_submit(w).status_code == 303
    with Session(w.engine) as session:
        session.add(AttendanceVerification(child_id=w.child, target_date=w.day, status=status))
        session.commit()
    for action in ("check-out", "check-out/commit"):
        assert w.client.post(f"/guardian/child/{w.child}/{action}", data={"date": str(w.day), "actual_pickup_person": "母"}).status_code == 400
    with Session(w.engine) as session:
        assert session.exec(select(AttendanceRecord)).one().check_out_at is None


def test_confirmation_migration_preserves_existing_false_and_is_repeatable(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE attendance_records (id INTEGER PRIMARY KEY, snack_required BOOLEAN NOT NULL)"))
        conn.execute(text("INSERT INTO attendance_records VALUES (1,0),(2,1)"))
    monkeypatch.setattr(database, "engine", engine)
    database._migrate_guardian_confirmation_columns()
    database._migrate_guardian_confirmation_columns()
    assert {"pickup_snack_confirmed", "actual_pickup_person"} <= {c["name"] for c in inspect(engine).get_columns("attendance_records")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT id,snack_required,pickup_snack_confirmed,actual_pickup_person FROM attendance_records ORDER BY id")).all() == [(1, 0, 1, None), (2, 1, 1, None)]
    engine.dispose()
