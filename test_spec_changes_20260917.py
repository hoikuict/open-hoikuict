from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlalchemy import event, inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

import auth
from auth import Role, StaffUser
from database import get_session
from models import (
    AttendancePickupHistory, AttendanceRecord, AttendanceVerification, AttendanceVerificationStatus,
    Child, Classroom, DailyContactEntry, DailyContactReply, Family, HealthCheckCorrection, HealthCheckRecord,
    ParentAccount, ParentAddressRemoval, ParentChildLink, ParentMailDelivery,
    ParentRegistrationRequest, PasswordCredential, Survey, SurveyResultViewer, User,
)
from pickup_plan_service import pickup_revision
from routers import child_health, daily_contacts, guardian, parent_accounts, parent_portal, surveys
from staff_portal_service import build_attendance_summaries
from time_utils import local_today


@pytest.fixture
def workbench(monkeypatch):
    for key, value in {"HOIKUICT_ENV": "development", "HOIKUICT_ENABLE_MOCK_AUTH": "1",
                       "HOIKUICT_KIOSK_ACCESS_MODE": "open", "HOIKUICT_PARENT_MAIL_TRANSPORT": "capture"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(auth, "_parent_portal_auth_backend", auth.MockParentPortalAuthBackend())
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="admin@example.test", display_name="管理職員", staff_role="admin")
        viewer = User(email="viewer@example.test", display_name="指定職員", staff_role="view_only")
        classroom = Classroom(name="試験組", display_order=1)
        family = Family(family_name="検証家")
        session.add_all([user, viewer, classroom, family]); session.flush()
        parent = ParentAccount(display_name="検証 保護者", email="parent@example.test", family_id=family.id)
        child = Child(last_name="検証", first_name="子", last_name_kana="ケンショウ", first_name_kana="コ", birth_date=date(2023, 1, 1),
                      enrollment_date=date(2026, 4, 1), classroom_id=classroom.id, family_id=family.id)
        other = Child(last_name="別", first_name="子", last_name_kana="ベツ", first_name_kana="コ", birth_date=date(2023, 1, 1), enrollment_date=date(2026, 4, 1))
        session.add_all([parent, child, other]); session.flush()
        session.add(ParentChildLink(parent_account_id=parent.id, child_id=child.id))
        session.commit()
        ids = dict(user=user.id, viewer=viewer.id, parent=parent.id, child=child.id, other=other.id, classroom=classroom.id)
    app = FastAPI()
    for module in (parent_portal, parent_accounts, guardian, daily_contacts, child_health, surveys):
        app.include_router(module.router)
    actor = StaffUser(role=Role.ADMIN, name="管理職員", user_id=ids["user"])
    def session_dep():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_session] = session_dep
    app.dependency_overrides[auth.get_current_staff_user] = lambda: actor
    with TestClient(app) as client:
        client.cookies.set(auth.MOCK_PARENT_ACCOUNT_COOKIE, str(ids["parent"]))
        yield SimpleNamespace(client=client, engine=engine, actor=actor, day=local_today(), **ids)
    engine.dispose()


def test_visual_presence_counts_without_creating_punch_and_resets(workbench):
    w = workbench
    with Session(w.engine) as session:
        verification = AttendanceVerification(child_id=w.child, target_date=w.day, status=AttendanceVerificationStatus.present)
        session.add(verification); session.commit()
        classroom = session.get(Classroom, w.classroom)
        summary = build_attendance_summaries(session, [classroom], w.day)[0]
        assert (summary.checked_in_count, summary.present_count, summary.not_checked_in_count) == (1, 1, 0)
        assert summary.missing_punch_count == 1 and summary.alarm_count == 0
        assert summary.attendance_url.startswith("/attendance-checks/?")
        assert session.exec(select(AttendanceRecord)).all() == []
        verification.status = AttendanceVerificationStatus.unknown
        session.add(verification); session.commit()
        summary = build_attendance_summaries(session, [classroom], w.day)[0]
        assert summary.present_count == 0 and summary.not_checked_in_count == 1
        verification.status = AttendanceVerificationStatus.present
        session.add(verification)
        session.add(AttendanceRecord(child_id=w.child, attendance_date=w.day,
            check_in_at=datetime.combine(w.day, datetime.min.time()), check_out_at=datetime.combine(w.day, datetime.max.time())))
        session.commit()
        summary = build_attendance_summaries(session, [classroom], w.day)[0]
        assert summary.checked_in_count == 1 and summary.present_count == 0 and summary.checked_out_count == 1


def test_staff_first_contact_draft_publication_and_parent_submission(workbench):
    w = workbench
    url = f"/daily-contacts/{w.child}/reply"
    data = {"date": str(w.day), "reply_message": "明日の持ち物をお知らせします", "action": "draft"}
    assert w.client.post(url, data=data, follow_redirects=False).status_code == 303
    assert "明日の持ち物をお知らせします" not in w.client.get("/parent-portal/history").text
    data["action"] = "publish"
    assert w.client.post(url, data=data, follow_redirects=False).status_code == 303
    history = w.client.get("/parent-portal/history")
    assert "明日の持ち物をお知らせします" in history.text and "保護者連絡は未提出" in history.text
    with Session(w.engine) as session:
        assert not session.exec(select(DailyContactEntry)).all()
        assert session.exec(select(DailyContactReply)).one().daily_contact_entry_id is None
    assert w.client.post(f"/parent-portal/children/{w.child}/contact",
        data={"date": str(w.day), "contact_type": "present", "temperature": "36.5"}, follow_redirects=False).status_code == 303
    assert len(w.client.get("/parent-portal/history").context["history_items"]) == 1
    w.client.cookies.clear()
    assert w.client.get("/parent-portal/history", follow_redirects=False).status_code == 303


def test_home_care_structured_values_preserve_legacy_and_overnight_duration(workbench):
    w = workbench
    data = {"date": str(w.day), "contact_type": "present", "temperature": "36.5", "care_fields_version": "1",
            "bedtime": "21:00", "wakeup_time": "06:30", "sleep_notes": "夜中に一度起床",
            "breakfast_contents": "ごはんと卵", "breakfast_status": "完食", "stool_consistency": "soft", "stool_count": "2"}
    url = f"/parent-portal/children/{w.child}/contact"
    assert w.client.post(url, data=data, follow_redirects=False).status_code == 303
    history = w.client.get("/parent-portal/history").text
    assert "9時間30分" in history and "ごはんと卵" in history and "2回" in history
    data["stool_count"] = "-1"
    assert "排便回数は" in w.client.post(url, data=data).text
    with Session(w.engine) as session:
        entry = session.exec(select(DailyContactEntry)).one()
        assert entry.extra_data["stool_count"] == "2"
        assert entry.sleep_notes == "夜中に一度起床"


def test_survey_acl_grant_revoke_csv_and_settings(workbench):
    w = workbench
    with Session(w.engine) as session:
        survey = Survey(title="閲覧範囲検証")
        session.add(survey); session.commit(); sid = survey.id
    url = f"/surveys/{sid}"
    assert w.client.get(url).status_code == 200
    assert w.client.post(url + "/result-viewers", data={"user_ids": str(w.viewer)}, follow_redirects=False).status_code == 303
    w.actor.role, w.actor.user_id = Role.VIEW_ONLY, w.viewer
    assert w.client.get(url).status_code == 200
    assert w.client.get(url + "/answers.csv").status_code == 200
    assert w.client.post(url + "/result-viewers", data={}).status_code == 403
    with Session(w.engine) as session:
        session.delete(session.get(SurveyResultViewer, (sid, w.viewer))); session.commit()
    assert w.client.get(url).status_code == 403 and w.client.get(url + "/answers.csv").status_code == 403


def test_health_correction_history_and_stale_update(workbench):
    w = workbench
    url = f"/children/{w.child}/health/check-records"
    assert w.client.post(url, data={"checked_at": str(w.day), "height_cm": "90"}, follow_redirects=False).status_code == 303
    with Session(w.engine) as session:
        record = session.exec(select(HealthCheckRecord)).one(); rid, revision = record.id, record.updated_at.isoformat()
    page = w.client.get(url + f"?edit={rid}")
    assert page.status_code == 200 and "健診記録を訂正" in page.text
    data = dict(record_id=rid, revision=revision, correction_reason="転記誤り", checked_at=str(w.day), height_cm="95")
    assert w.client.post(url, data=data, follow_redirects=False).status_code == 303
    assert w.client.post(url, data=data, follow_redirects=False).status_code == 409
    with Session(w.engine) as session:
        records = session.exec(select(HealthCheckRecord)).all()
        assert len(records) == 1 and records[0].height_cm == 95
        audit = session.exec(select(HealthCheckCorrection)).one()
        assert audit.before["height_cm"] == 90 and audit.after["height_cm"] == 95 and audit.actor_user_id == w.user
    assert w.client.get(url).context["height_summary"]["value"] == 95
    assert w.client.get(f"/children/{w.other}/health/check-records?edit={rid}").status_code == 404
    w.actor.role = Role.VIEW_ONLY
    assert w.client.post(url, data=data).status_code == 403


def test_pickup_before_arrival_shared_kiosk_revision_and_history(workbench):
    w = workbench
    url = f"/parent-portal/children/{w.child}/pickup"
    data = {"date": str(w.day), "revision": "new", "planned_pickup_time": "17:30", "pickup_person": "母"}
    assert w.client.post(url, data=data, follow_redirects=False).status_code == 303
    with Session(w.engine) as session:
        record = session.exec(select(AttendanceRecord)).one()
        assert record.check_in_at is None and record.check_out_at is None
        revision = pickup_revision(record)
    assert w.client.post(url, data=data, follow_redirects=False).status_code == 409
    data.update(revision=revision, pickup_person="父", snack_required="1")
    assert w.client.post(f"/guardian/child/{w.child}/pickup", data=data).status_code == 200
    assert w.client.post(f"/guardian/child/{w.child}/pickup/commit", data=data).status_code == 200
    page = w.client.get(url + f"?date={w.day}")
    assert page.context["record"].pickup_person == "父"
    with Session(w.engine) as session:
        history = session.exec(select(AttendancePickupHistory).order_by(AttendancePickupHistory.id)).all()
        assert [row.source for row in history] == ["parent_portal", "kiosk"]
        assert history[0].changed_by_parent_account_id == w.parent and history[1].new_snack_required
        record = session.exec(select(AttendanceRecord)).one()
        record.check_out_at = datetime.now(); session.add(record); session.commit()
        data["revision"] = pickup_revision(record)
    assert w.client.post(url, data=data, follow_redirects=False).status_code == 400
    assert w.client.post(f"/parent-portal/children/{w.other}/pickup", data=data).status_code == 404


def test_address_removal_preserves_activity_and_disables_credentials(workbench):
    w = workbench
    with Session(w.engine) as session:
        parent = session.get(ParentAccount, w.parent)
        revision = parent.updated_at.isoformat()
        session.add(PasswordCredential(principal_type="parent", parent_account_id=w.parent,
            login_id=parent.email, login_id_normalized=parent.email, password_hash="test-only-hash"))
        session.add(ParentRegistrationRequest(parent_account_id=w.parent, email_normalized_snapshot=parent.email))
        session.add(ParentMailDelivery(parent_account_id=w.parent, message_type="invitation", recipient=parent.email,
            subject="招待", body="案内 " + parent.email))
        session.add(DailyContactEntry(parent_account_id=w.parent, child_id=w.child, target_date=w.day))
        session.commit()
    url = f"/parent-accounts/{w.parent}/remove-email"
    assert w.client.post(url, data={"confirmed": "yes", "reason": "誤登録取消", "revision": revision}, follow_redirects=False).status_code == 303
    with Session(w.engine) as session:
        parent = session.get(ParentAccount, w.parent)
        assert parent.email_removed and parent.contact_email == "" and parent.status.value == "inactive"
        credential = session.exec(select(PasswordCredential)).one()
        assert credential.disabled_at and not credential.password_hash and "@" not in credential.login_id
        assert session.exec(select(ParentMailDelivery)).one().recipient == ""
        assert session.exec(select(ParentRegistrationRequest)).one().email_normalized_snapshot == ""
        assert session.exec(select(DailyContactEntry)).one().parent_account_id == w.parent
        assert session.exec(select(ParentAddressRemoval)).one().actor_user_id == w.user
        assert len(session.exec(select(ParentChildLink)).all()) == 1
    assert "parent@example.test" not in w.client.get("/parent-accounts/").text
    assert w.client.get("/parent-portal/", follow_redirects=False).status_code == 303


def test_address_removal_preserves_other_addresses_and_family_edits(workbench):
    from parent_address_removal import remove_parent_address
    from family_support import sync_family_to_parent_accounts
    from data_transfer_service import _export_parent_accounts
    w = workbench
    with Session(w.engine) as session:
        parent = session.get(ParentAccount, w.parent)
        family = session.get(Family, parent.family_id)
        family.shared_profile = {"guardians": [
            {"order": 1, "last_name": "検証", "first_name": "保護者", "email": parent.email, "parent_account_id": parent.id},
            {"order": 2, "last_name": "検証", "first_name": "別", "email": "anotherparent@example.test"},
        ]}
        session.add(family); session.commit()
        remove_parent_address(session, parent, actor=w.actor, reason="誤登録")
        session.commit()
        assert family.guardian_profiles()[0]["email"] == ""
        assert family.guardian_profiles()[1]["email"] == "anotherparent@example.test"
        sync_family_to_parent_accounts(session, family, previous_address=family.home_address, previous_account_ids={parent.id})
        session.commit()
        assert parent.email_removed
        assert _export_parent_accounts(session)[0][2] == ""


@pytest.mark.parametrize("field,value", [("height_cm", "nan"), ("weight_kg", "abc"), ("heart_rate", "-1")])
def test_invalid_health_values_do_not_create_record(workbench, field, value):
    w = workbench
    response = w.client.post(f"/children/{w.child}/health/check-records", data={"checked_at": str(w.day), field: value})
    assert response.status_code == 400
    with Session(w.engine) as session:
        assert not session.exec(select(HealthCheckRecord)).all()


def test_existing_pickup_history_migration_is_repeatable(tmp_path, monkeypatch):
    import database
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE attendance_pickup_history (id INTEGER PRIMARY KEY, attendance_record_id INTEGER NOT NULL, previous_time VARCHAR, previous_person VARCHAR, new_time VARCHAR NOT NULL, new_person VARCHAR NOT NULL, changed_by_user_id CHAR(32), changed_by_name VARCHAR NOT NULL, changed_at DATETIME NOT NULL)"))
        connection.execute(text("INSERT INTO attendance_pickup_history (id,attendance_record_id,new_time,new_person,changed_by_name,changed_at) VALUES (1,1,'17:00','母','旧職員','2026-09-16 00:00:00')"))
    monkeypatch.setattr(database, "engine", engine)
    database._migrate_pickup_history_columns()
    database._migrate_pickup_history_columns()
    columns = {item["name"] for item in inspect(engine).get_columns("attendance_pickup_history")}
    assert {"source", "changed_by_parent_account_id", "previous_snack_required", "new_snack_required"} <= columns
    with engine.connect() as connection:
        assert connection.execute(text("SELECT new_time, source, new_snack_required FROM attendance_pickup_history")).one() == ("17:00", "staff", None)
    engine.dispose()
