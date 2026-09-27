"""Approved compact roster, correction audit, replies and kiosk closing policy."""
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, create_engine, select

import database
from auth import Role
from csrf import CSRF_COOKIE_NAME
from guardian_hours import parse_closing_time
from models import (AttendanceCorrection, AttendanceRecord, AttendanceVerification,
                    AttendanceVerificationHistory, Child, DailyContactReply, GuardianHoursAudit,
                    GuardianHoursSetting)
from routers import attendance, attendance_checks, guardian, settings
import test_settings_sessions as settings_fixtures
import test_spec_changes_20260917 as shared_fixtures

workbench = shared_fixtures.workbench
settings_setup = settings_fixtures.setup


@pytest.fixture
def nursery(workbench):
    w = workbench
    for module in (attendance, attendance_checks, settings):
        w.client.app.include_router(module.router)
    return w


def test_roster_includes_every_state_and_visual_presence(nursery):
    w = nursery
    with Session(w.engine) as session:
        for i, state in enumerate(("departed", "absent", "visual")):
            child = Child(last_name="見本", first_name=state, last_name_kana="ミホン", first_name_kana=str(i),
                          birth_date=w.day - timedelta(days=900), enrollment_date=w.day, classroom_id=w.classroom)
            session.add(child)
            session.flush()
            if state == "departed":
                # A visually confirmed arrival may have a departure without a check-in.
                session.add(AttendanceRecord(child_id=child.id, attendance_date=w.day,
                                             check_out_at=datetime.combine(w.day, time(16))))
            else:
                session.add(AttendanceVerification(child_id=child.id, target_date=w.day,
                                                    status="sick_absent" if state == "absent" else "present"))
        session.add(AttendanceRecord(child_id=w.child, attendance_date=w.day,
                                     check_in_at=datetime.combine(w.day, time(8))))
        session.commit()
    response = w.client.get(f"/attendance-checks/roster?date={w.day}")
    assert response.status_code == 200
    assert response.context["totals"] == dict(present=2, departed=1, absent=1, pending=1)
    assert response.context["child_count"] == 5
    page = w.client.get(f"/attendance-checks/?date={w.day}")
    assert len(page.context["rows"]) == 5
    assert page.context["selected_filter"] == "all"
    assert len(w.client.get(f"/attendance-checks/roster?date={w.day}&classroom_id={w.classroom}").context["groups"]) == 1


def test_correction_requires_reason_and_records_real_actor(nursery):
    w = nursery
    path = f"/attendance-checks/{w.child}/verification"
    assert w.client.post(path, data=dict(date=str(w.day), status="present"), follow_redirects=False).status_code == 303
    assert w.client.post(path, data=dict(date=str(w.day), status="sick_absent", reason="  ")).status_code == 400
    assert w.client.post(path, data=dict(date=str(w.day), status="sick_absent", reason="x" * 501)).status_code == 400
    with Session(w.engine) as session:
        assert len(session.exec(select(AttendanceVerificationHistory)).all()) == 1
        assert session.exec(select(AttendanceVerification)).one().status.value == "present"
    data = dict(date=str(w.day), status="sick_absent", reason="対象児を取り違えたため", updated_by_name="偽の名前")
    response = w.client.post(path, data=data, headers={"HX-Request": "true"})
    assert response.status_code == 200 and 'id="attendance-checks-board"' in response.text
    assert "対象児を取り違えたため" in response.text
    with Session(w.engine) as session:
        history = session.exec(select(AttendanceVerificationHistory).order_by(AttendanceVerificationHistory.id.desc())).first()
        assert (history.reason, history.updated_by_name, history.actor_user_id) == (data["reason"], w.actor.name, w.actor.user_id)
        assert history.previous_status == "present" and history.status.value == "sick_absent"
    w.actor.role = Role.VIEW_ONLY
    assert w.client.post(path, data=data).status_code == 403


def test_punch_cancellation_returns_to_same_check_filters(nursery):
    w = nursery
    with Session(w.engine) as session:
        session.add(AttendanceRecord(child_id=w.child, attendance_date=w.day, check_in_at=datetime.combine(w.day, time(8))))
        session.commit()
    page = w.client.get(f"/attendance/{w.child}/correction", params={"date": str(w.day), "return_to": "checks",
                             "return_query": f"layout=classroom&filter=alarm&classroom_id={w.classroom}&next=https://example.test"})
    assert page.status_code == 200 and "出欠確認に戻る" in page.text
    result = w.client.post(f"/attendance/{w.child}/correction", data={
        "date": str(w.day), "operation": "all", "reason": "他児の打刻だった", "revision": page.context["revision"],
        "return_to": "checks", "return_query": page.context["return_query"],
    }, follow_redirects=False)
    assert result.status_code == 303
    assert result.headers["location"].startswith("/attendance-checks/?")
    assert "filter=alarm" in result.headers["location"] and "example.test" not in result.headers["location"]
    with Session(w.engine) as session:
        correction = session.exec(select(AttendanceCorrection)).one()
        assert correction.reason == "他児の打刻だった" and correction.changed_by_name == w.actor.name


def test_draft_of_published_reply_keeps_public_version_and_can_be_published(nursery):
    w = nursery
    url = f"/daily-contacts/{w.child}/reply"
    data = dict(date=str(w.day), action="publish", reply_message="公開中の連絡", reply_temperature="36.5")
    assert w.client.post(url, data=data, follow_redirects=False).status_code == 303
    public_page = w.client.get("/parent-portal/history")
    assert "公開中の連絡" in public_page.text
    data.update(action="draft", reply_message="まだ送らない変更", reply_temperature="37.0")
    assert w.client.post(url, data=data, follow_redirects=False).status_code == 303
    with Session(w.engine) as session:
        reply = session.exec(select(DailyContactReply)).one()
        assert reply.status.value == "published" and reply.message == "公開中の連絡"
        assert reply.field_values["temperature"] == "36.5"
        assert reply.pending_draft["message"] == "まだ送らない変更"
    public_page = w.client.get("/parent-portal/history")
    assert "公開中の連絡" in public_page.text and "まだ送らない変更" not in public_page.text
    detail = w.client.get(f"/daily-contacts/{w.child}?date={w.day}")
    assert detail.context["reply_message_value"] == "まだ送らない変更"
    assert detail.context["reply_form_values"]["temperature"] == "37.0"
    assert "未送信の変更あり" in detail.text
    w.actor.role = Role.VIEW_ONLY
    readonly = w.client.get(f"/daily-contacts/{w.child}?date={w.day}")
    assert "まだ送らない変更" in readonly.text and 'id="daily-reply-form"' not in readonly.text
    assert w.client.post(url, data=data).status_code == 403
    w.actor.role = Role.ADMIN
    data["action"] = "publish"
    assert w.client.post(url, data=data, follow_redirects=False).status_code == 303
    assert "まだ送らない変更" in w.client.get("/parent-portal/history").text
    with Session(w.engine) as session:
        assert session.exec(select(DailyContactReply)).one().pending_draft is None


def test_reply_empty_errors_stale_revision_and_same_child_navigation(nursery):
    w = nursery
    url = f"/daily-contacts/{w.child}/reply"
    headers = {"X-Reply-Request": "1"}
    data = dict(date=str(w.day), revision="new", action="publish")
    assert w.client.post(url, data=data, headers=headers).status_code == 400
    data.update(action="draft", reply_message="消さないメモ", reply_temperature="36.")
    invalid = w.client.post(url, data=data)
    assert invalid.status_code == 400 and "消さないメモ" in invalid.text
    data["reply_temperature"] = "36.7"
    saved = w.client.post(url, data=data, headers=headers)
    assert saved.status_code == 200 and saved.json()["status"] == "未送信"
    assert w.client.post(url, data={**data, "reply_message": "古い画面"}, headers=headers).status_code == 409
    with Session(w.engine) as session:
        assert session.exec(select(DailyContactReply)).one().message == "消さないメモ"
    detail = w.client.get(f"/daily-contacts/{w.child}?date={w.day}&classroom_id={w.classroom}&sort=unsent_first")
    assert f"/daily-contacts/{w.child}?date={w.day - timedelta(days=1)}" in detail.context["previous_url"]
    assert f"/daily-contacts/{w.child}?date={w.day + timedelta(days=1)}" in detail.context["next_url"]
    history = w.client.get(detail.context["history_url"])
    assert history.status_code == 200 and "未送信（下書き保存済み）" in history.text
    assert all(row["url"].startswith(f"/daily-contacts/{w.child}?") for row in history.context["rows"])
    assert w.client.get(f"/daily-contacts/{w.child}?date=bad").status_code == 400


@pytest.mark.parametrize("value,ok", [("18:29", True), ("18:30", False), ("18:31", False), ("19:00", False)])
def test_kiosk_rejects_planned_time_at_or_after_close(nursery, value, ok):
    w = nursery
    with Session(w.engine) as session:
        session.add(GuardianHoursSetting(closing_time="18:30"))
        session.commit()
    data = dict(date=str(w.day), revision="new", planned_pickup_time=value, pickup_person="母", snack_required="0")
    result = w.client.post(f"/guardian/child/{w.child}/pickup/commit", data=data)
    assert result.status_code == (200 if ok else 400)
    with Session(w.engine) as session:
        assert len(session.exec(select(AttendanceRecord)).all()) == int(ok)


@pytest.mark.parametrize("endpoint", ["check-in", "arrival/edit", "pickup", "pickup/commit", "check-out", "check-out/commit"])
def test_kiosk_blocks_all_writes_at_closing(nursery, monkeypatch, endpoint):
    w = nursery
    monkeypatch.setattr(guardian, "local_naive_now", lambda: datetime.combine(w.day, time(19)))
    data = dict(date=str(w.day), revision="new", planned_pickup_time="18:30", pickup_person="母",
                arrival_token="test", snack_required="0", actual_pickup_person="父")
    response = w.client.post(f"/guardian/child/{w.child}/{endpoint}", data=data)
    assert response.status_code == 400 and "閉園時間" in response.text
    with Session(w.engine) as session:
        assert session.exec(select(AttendanceRecord)).all() == []
    page = w.client.get(f"/guardian/?child_id={w.child}")
    assert "本日の受付は終了" in page.text and page.context["kiosk_closed"]
    assert '<button type="submit" data-punch' not in page.text


def test_kiosk_hides_late_hours_and_shows_all_children(nursery):
    w = nursery
    page = w.client.post(f"/guardian/child/{w.child}/check-in", data={"date": str(w.day)})
    assert page.status_code == 200
    assert 'data-pickup-hour="18"' in page.text
    assert 'data-pickup-hour="19"' not in page.text and 'data-pickup-hour="23"' not in page.text
    assert 'data-closing-time="19:00"' in page.text
    with Session(w.engine) as session:
        session.add(AttendanceVerification(child_id=w.child, target_date=w.day, status="sick_absent"))
        session.commit()
    chooser = w.client.get(f"/guardian/?class_id={w.classroom}")
    assert chooser.context["child_states"][w.child] == "お休み"
    assert [child.id for child in chooser.context["children"]] == [w.child]


def test_closing_settings_require_admin_csrf_and_audit(settings_setup):
    app, client, session, actor, principal = settings_setup
    assert client.get("/settings/guardian-hours").status_code == 200
    data = {"closing_time": "18:30"}
    assert client.post("/settings/guardian-hours", data=data).status_code == 403
    data["csrf_token"] = client.cookies[CSRF_COOKIE_NAME]
    assert client.post("/settings/guardian-hours", data=data, follow_redirects=False).status_code == 303
    assert session.get(GuardianHoursSetting, 1).closing_time == "18:30"
    audit = session.exec(select(GuardianHoursAudit)).one()
    assert audit.previous_closing_time == "19:00" and audit.changed_by_user_id == actor.id
    assert audit.changed_by_name == actor.display_name
    assert client.post("/settings/guardian-hours", data={**data, "closing_time": "25:00"}).status_code == 400
    principal.role = Role.CAN_EDIT
    actor.staff_role = "can_edit"
    session.add(actor)
    session.commit()
    assert client.post("/settings/guardian-hours", data=data).status_code == 403


@pytest.mark.parametrize("value", ["", "00:00", "24:00", "19:60", "9:00", "19:00:00"])
def test_invalid_closing_time(value):
    with pytest.raises(ValueError):
        parse_closing_time(value)


def test_additive_migration_keeps_old_audits_and_published_reply(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE attendance_verification_histories (id INTEGER PRIMARY KEY, updated_by_name VARCHAR, status VARCHAR)"))
        connection.execute(text("INSERT INTO attendance_verification_histories VALUES (1, '以前の職員', 'present')"))
        connection.execute(text("CREATE TABLE daily_contact_replies (id INTEGER PRIMARY KEY, message VARCHAR, status VARCHAR)"))
        connection.execute(text("INSERT INTO daily_contact_replies VALUES (1, '公開済みの記録', 'published')"))
    monkeypatch.setattr(database, "engine", engine)
    database._migrate_spec_20260924_columns()
    database._migrate_spec_20260924_columns()
    assert {"reason", "actor_user_id", "previous_status"} <= {c["name"] for c in inspect(engine).get_columns("attendance_verification_histories")}
    with engine.connect() as connection:
        assert tuple(connection.execute(text("SELECT updated_by_name, reason FROM attendance_verification_histories")).one()) == ("以前の職員", None)
        assert tuple(connection.execute(text("SELECT message, status, pending_draft FROM daily_contact_replies")).one()) == ("公開済みの記録", "published", None)
    engine.dispose()
