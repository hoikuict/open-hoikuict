from datetime import date, datetime, timedelta, timezone
import re
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser, get_current_staff_user
from database import get_session
from models import (
    AttendanceRecord,
    AttendanceCorrection,
    Child,
    Classroom,
    DocumentReviewRequest,
    ExtendedCareCharge,
    ExtendedCareChargeStatus,
    ExtendedCareFeeRule,
    GuardianTerminalStatus,
    ParentAccount,
    ParentChildLink,
    ParentEmailPreference,
    ParentMailDelivery,
    ParentNotificationEmail,
    ParentNotificationDelivery,
    Calendar,
    CalendarMember,
    CalendarMemberRole,
    CalendarUserPreference,
    Event,
    StaffClassroomAssignment,
    User,
)
from attendance_correction_service import cancel_punch, correction_revision
from parent_notification_service import notify_attendance_confirmation_needed
from parent_auth import dispatch_pending_parent_mail
from staff_portal_service import (
    build_schedule_items,
    next_schedule_item,
    classroom_scope,
)
from terminal_monitor_service import terminal_statuses
from time_utils import utc_now, local_today
import routers.document_reviews as reviews
import routers.attendance as attendance
import routers.staff_rooms as rooms
from models import Message


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(reviews, "UPLOAD_ROOT", tmp_path / "reviews")
    monkeypatch.setenv("HOIKUICT_PARENT_MAIL_TRANSPORT", "capture")
    state = {"actor": StaffUser(role=Role.CAN_EDIT, user_id=uuid4(), name="検証職員")}
    app = FastAPI()
    for router in [reviews.router, attendance.router, rooms.router]:
        app.include_router(router)

    def sessions():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_current_staff_user] = lambda: state["actor"]
    with Session(engine) as session:
        session.add(
            User(
                id=state["actor"].user_id,
                email="actor@example.test",
                display_name="検証職員",
                staff_role="can_edit",
            )
        )
        child = Child(
            last_name="検証",
            first_name="花",
            last_name_kana="ケンショウ",
            first_name_kana="ハナ",
            birth_date=date(2022, 1, 1),
            enrollment_date=date(2026, 4, 1),
        )
        session.add(child)
        session.commit()
        state["child_id"] = child.id
    with TestClient(app) as client:
        yield client, engine, state
    engine.dispose()


def test_direct_thread_and_safe_clickable_links(fixture):
    client, engine, _ = fixture
    with Session(engine) as session:
        room = Classroom(name="検証組")
        session.add(room)
        session.flush()
        message = Message(
            room_id=room.id,
            author_name="検証",
            body="<script>alert(1)</script> https://example.test/form",
        )
        session.add(message)
        session.commit()
        message_id = message.id
    full = client.get(f"/staff-rooms/threads/{message_id}")
    assert "<html" in full.text and "<script>alert(1)</script>" not in full.text
    assert 'href="https://example.test/form"' in full.text and "noopener" in full.text
    fragment = client.get(
        f"/staff-rooms/threads/{message_id}", headers={"HX-Request": "true"}
    )
    assert "<html" not in fragment.text and "https://example.test/form" in fragment.text


def test_review_attachment_is_private_and_decision_is_final(fixture):
    client, engine, state = fixture
    response = client.post(
        "/document-reviews/",
        data={"title": "月案の確認", "body": "内容をご確認ください"},
        files={"attachments": ("plan.pdf", b"%PDF-1.4 test", "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    url = response.headers["location"]
    assert client.get(url + "/attachments/0").content == b"%PDF-1.4 test"
    assert (
        client.post(url + "/decision", data={"decision": "approved"}).status_code == 403
    )
    state["actor"] = StaffUser(role=Role.CAN_EDIT, name="別職員", user_id=uuid4())
    assert client.get(url).status_code == 404
    assert client.get(url + "/attachments/0").status_code == 404
    state["actor"] = StaffUser(role=Role.ADMIN, name="園長", user_id=uuid4())
    with Session(engine) as session:
        session.add(
            User(
                id=state["actor"].user_id,
                email="admin@example.test",
                display_name="園長",
                staff_role="admin",
            )
        )
        session.commit()
    assert "月案の確認" in client.get("/document-reviews/").text
    assert (
        client.post(
            url + "/decision", data={"decision": "returned", "note": ""}
        ).status_code
        == 400
    )
    assert (
        client.post(
            url + "/decision",
            data={"decision": "approved", "note": "確認しました"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert (
        client.post(
            url + "/decision", data={"decision": "returned", "note": "二重操作"}
        ).status_code
        == 409
    )
    with Session(engine) as session:
        item = session.exec(select(DocumentReviewRequest)).one()
        assert item.status == "approved" and item.decision_note == "確認しました"


def test_review_rejects_unsupported_upload_without_record(fixture):
    client, engine, _ = fixture
    assert (
        client.post(
            "/document-reviews/",
            data={"title": "確認"},
            files={"attachments": ("run.html", b"<script>", "text/html")},
        ).status_code
        == 400
    )
    with Session(engine) as session:
        assert not session.exec(select(DocumentReviewRequest)).all()


@pytest.mark.parametrize("operation", ["all", "check_out"])
def test_cancel_retains_audit_and_invalidates_draft_charge(fixture, operation):
    client, engine, state = fixture
    with Session(engine) as session:
        record = AttendanceRecord(
            child_id=state["child_id"],
            attendance_date=date(2026, 9, 11),
            check_in_at=datetime(2026, 9, 11, 9),
            check_out_at=datetime(2026, 9, 11, 19),
            planned_pickup_time="18:00",
            pickup_person="母",
        )
        rule = ExtendedCareFeeRule(name="検証", effective_from=date(2026, 4, 1))
        session.add_all([record, rule])
        session.flush()
        session.add(
            ExtendedCareCharge(
                attendance_record_id=record.id,
                child_id=state["child_id"],
                target_date=record.attendance_date,
                rule_id=rule.id,
                charge_start_at=record.check_out_at,
                final_amount=100,
            )
        )
        session.commit()
    url = f"/attendance/{state['child_id']}/correction?date=2026-09-11"
    form = client.get(url)
    revision = re.search('name="revision" value="([^"]+)"', form.text).group(1)
    values = {
        "date": "2026-09-11",
        "operation": operation,
        "reason": "別の園児を押したため",
        "revision": revision,
    }
    assert (
        client.post(url.split("?")[0], data=values, follow_redirects=False).status_code
        == 303
    )
    assert client.post(url.split("?")[0], data=values).status_code == 409
    with Session(engine) as session:
        record = session.exec(select(AttendanceRecord)).one()
        assert record.check_out_at is None
        assert bool(record.check_in_at) == (operation == "check_out")
        assert not session.exec(select(ExtendedCareCharge)).all()
        history = session.exec(select(AttendanceCorrection)).one()
        assert history.previous_charge["final_amount"] == 100
        assert (
            history.previous_values["check_in_at"]
            and history.changed_by_name == "検証職員"
        )


@pytest.mark.parametrize(
    "status",
    [
        ExtendedCareChargeStatus.confirmed,
        ExtendedCareChargeStatus.manual_adjusted,
        ExtendedCareChargeStatus.excluded,
    ],
)
def test_cancel_preserves_protected_fee_and_punch(fixture, status):
    _, engine, state = fixture
    with Session(engine) as session:
        record = AttendanceRecord(
            child_id=state["child_id"],
            attendance_date=date(2026, 9, 11),
            check_in_at=datetime(2026, 9, 11, 9),
        )
        rule = ExtendedCareFeeRule(name="検証", effective_from=date(2026, 4, 1))
        session.add_all([record, rule])
        session.flush()
        session.add(
            ExtendedCareCharge(
                attendance_record_id=record.id,
                child_id=record.child_id,
                target_date=record.attendance_date,
                rule_id=rule.id,
                charge_start_at=record.check_in_at,
                status=status,
            )
        )
        session.commit()
        with pytest.raises(ValueError, match="料金"):
            cancel_punch(
                session,
                record,
                operation="all",
                reason="誤打刻",
                revision=correction_revision(record),
                actor=state["actor"],
            )
        assert (
            record.check_in_at and not session.exec(select(AttendanceCorrection)).all()
        )


def test_cancel_denies_read_only_staff(fixture):
    client, _, state = fixture
    state["actor"] = StaffUser(role=Role.VIEW_ONLY, name="閲覧職員")
    assert (
        client.get(
            f"/attendance/{state['child_id']}/correction?date=2026-09-11"
        ).status_code
        == 403
    )


def test_schedule_all_calendars_and_staff_all_classrooms(fixture):
    _, engine, _ = fixture
    today = date(2026, 9, 11)
    start = datetime(2026, 9, 10, 15, tzinfo=timezone.utc)
    with Session(engine) as session:
        user = User(
            email="teacher@example.test", display_name="担任", staff_role="can_edit"
        )
        a, b = Classroom(name="担当組"), Classroom(name="応援組")
        session.add_all([user, a, b])
        session.flush()
        session.add(
            StaffClassroomAssignment(
                staff_user_id=user.id, classroom_id=a.id, starts_on=today
            )
        )
        cal = Calendar(owner_user_id=user.id, name="非表示設定の共有予定")
        session.add(cal)
        session.flush()
        session.add(
            CalendarMember(
                calendar_id=cal.id, user_id=user.id, role=CalendarMemberRole.owner
            )
        )
        session.add(
            CalendarUserPreference(
                calendar_id=cal.id, user_id=user.id, is_visible=False
            )
        )
        session.add(
            Event(
                calendar_id=cal.id,
                created_by_user_id=user.id,
                title="終日行事",
                start_at=start,
                end_at=start + timedelta(days=1),
                is_all_day=True,
            )
        )
        for n in range(7):
            session.add(
                Event(
                    calendar_id=cal.id,
                    created_by_user_id=user.id,
                    title=f"予定{n}",
                    start_at=start + timedelta(hours=12 + n),
                    end_at=start + timedelta(hours=13 + n),
                )
            )
        session.commit()
        items, remaining = build_schedule_items(
            session, user, today, start + timedelta(hours=10)
        )
        assert (
            len(items) == 8
            and remaining == 0
            and next_schedule_item(items).title == "予定0"
        )
        assert len(classroom_scope(session, user, today)[0]) == 1
        assert len(classroom_scope(session, user, today, show_all=True)[0]) == 2


def test_monitor_only_warns_during_enabled_hours(fixture, monkeypatch):
    _, engine, _ = fixture
    now = datetime(2026, 9, 11, 1, tzinfo=timezone.utc)
    monkeypatch.setattr("terminal_monitor_service.utc_now", lambda: now)
    with Session(engine) as session:
        terminal = GuardianTerminalStatus(
            device_id="test", last_seen_at=now - timedelta(minutes=3)
        )
        session.add(terminal)
        session.commit()
        assert terminal_statuses(session)[0]["stale"]
        terminal.monitoring_enabled = False
        session.add(terminal)
        session.commit()
        assert not terminal_statuses(session)[0]["stale"]
        terminal.monitoring_enabled = True
        terminal.start_hour = 11
        session.add(terminal)
        session.commit()
        assert not terminal_statuses(session)[0]["stale"]


@pytest.mark.parametrize("disable_before_send", [False, True])
def test_email_can_accompany_push_and_rechecks_opt_out(fixture, disable_before_send):
    _, engine, state = fixture
    with Session(engine) as session:
        account = ParentAccount(
            display_name="検証保護者", email="guardian@example.test"
        )
        session.add(account)
        session.flush()
        session.add(
            ParentChildLink(parent_account_id=account.id, child_id=state["child_id"])
        )
        preference = ParentEmailPreference(
            parent_account_id=account.id, attendance_confirmation_enabled=True
        )
        session.add(preference)
        session.commit()
        child = session.get(Child, state["child_id"])
        notify_attendance_confirmation_needed(
            session,
            child=child,
            target_date=local_today(),
            source_id="test-request",
            created_by_name="職員",
            now=utc_now(),
        )
        session.commit()
        assert len(session.exec(select(ParentNotificationDelivery)).all()) == 2
        assert len(session.exec(select(ParentNotificationEmail)).all()) == 1
        if disable_before_send:
            preference.attendance_confirmation_enabled = False
            session.add(preference)
            session.commit()
        dispatch_pending_parent_mail(session)
        mail = session.exec(select(ParentMailDelivery)).one()
        assert mail.status == ("cancelled" if disable_before_send else "captured")
