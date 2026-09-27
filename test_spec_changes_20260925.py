"""Approved sharing boundaries and initial/change attendance semantics."""
from datetime import date
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from auth import Role, StaffUser
from child_records.models import ChildObservationLog, ChildObservationLogRevision
from models import AttendanceAlarmState, AttendanceVerification, AttendanceVerificationHistory, User
import test_child_records as record_cases
import test_attendance_checks as attendance_cases


@pytest.fixture
def records():
    case = record_cases.ChildRecordFeatureTests()
    case.setUp()
    yield case
    case.client.close()
    case.engine.dispose()


@pytest.fixture
def checks():
    case = attendance_cases.AttendanceChecksTests()
    case.setUp()
    yield case
    case.client.close()
    case.engine.dispose()


def create(case, **values):
    response = case.client.post(f"/children/{case.child_id}/records", data={
        "observed_on": date.today().isoformat(), "child_state": "見本の記録", **values,
    }, follow_redirects=False)
    assert response.status_code == 303, response.text[:200]
    with Session(case.engine) as session:
        return session.exec(select(ChildObservationLog).order_by(ChildObservationLog.id.desc())).first()


def test_private_is_author_only_even_for_admin_or_manager(records):
    author = StaffUser(role=Role.CAN_EDIT, user_id=uuid4(), name="記録者")
    records.current_user = author
    log = create(records, child_state="個人だけの内容")
    assert log.visibility == "private"
    assert "個人だけの内容" in records.client.get(f"/children/{records.child_id}/records").text
    for role, manager in [(Role.ADMIN, True), (Role.CAN_EDIT, True), (Role.CAN_EDIT, False), (Role.VIEW_ONLY, False)]:
        records.current_user = StaffUser(role=role, user_id=uuid4(), can_manage_child_records=manager)
        assert "個人だけの内容" not in records.client.get(f"/children/{records.child_id}/records?include_voided=true").text
        for suffix, method in [("correct", "get"), ("correct", "post"), ("void", "post")]:
            assert getattr(records.client, method)(f"/children/{records.child_id}/records/{log.id}/{suffix}", follow_redirects=False).status_code == 403
    records.current_user = author
    assert records.client.get(f"/children/{records.child_id}/records/{log.id}/correct").status_code == 200


def test_shared_visible_outside_class_but_only_author_admin_can_change(records):
    log = create(records, visibility="shared", child_state="共有する内容")
    records.current_user = StaffUser(role=Role.CAN_EDIT, user_id=uuid4(), can_manage_child_records=True)
    page = records.client.get(f"/children/{records.child_id}/records")
    assert "共有する内容" in page.text
    assert f"/records/{log.id}/correct" not in page.text
    assert records.client.post(f"/children/{records.child_id}/records/{log.id}/void", data={"void_reason": "無効"}).status_code == 403
    # Daily records can be made for any child; progress-record writing stays restricted.
    records.current_user.can_manage_child_records = False
    assert records.client.get(f"/children/{records.child_id}/records/new").status_code == 200
    assert records.client.post(f"/children/{records.child_id}/progress-records", data={}).status_code == 403
    create(records, visibility="shared")


def test_restricted_recipient_cannot_edit_or_reveal_to_other_staff(records):
    recipient = User(email="recipient@example.test", display_name="指定職員")
    with Session(records.engine) as session:
        session.add(recipient)
        session.commit()
        session.refresh(recipient)
    log = create(records, visibility="shared", sensitivity="restricted", shared_staff_ids=[str(recipient.id)], child_state="限定した内容")
    records.current_user = StaffUser(role=Role.CAN_EDIT, user_id=recipient.id)
    assert "限定した内容" in records.client.get(f"/children/{records.child_id}/records").text
    assert records.client.get(f"/children/{records.child_id}/records/{log.id}/correct").status_code == 403
    records.current_user = StaffUser(role=Role.CAN_EDIT, user_id=uuid4())
    assert "限定した内容" not in records.client.get(f"/children/{records.child_id}/records").text
    records.current_user = StaffUser(role=Role.ADMIN, user_id=uuid4())
    assert "限定した内容" in records.client.get(f"/children/{records.child_id}/records").text
    assert "限定した内容" not in records.client.get(f"/children/{records.child_id}/progress-records/new").text


def test_private_history_does_not_become_shared_with_current_content(records):
    author = records.current_user
    log = create(records, child_state="非公開の変更前")
    data = {"observed_on": date.today().isoformat(), "child_state": "公開する変更後", "visibility": "shared", "correction_reason": "個人の訂正理由"}
    response = records.client.post(f"/children/{records.child_id}/records/{log.id}/correct", data=data, follow_redirects=False)
    assert response.status_code == 303
    with Session(records.engine) as session:
        revision = session.exec(select(ChildObservationLogRevision)).one()
        assert revision.snapshot["visibility"] == "private"
        assert revision.created_by == str(author.user_id)
    records.current_user = StaffUser(role=Role.ADMIN, user_id=uuid4())
    page = records.client.get(f"/children/{records.child_id}/records").text
    assert "公開する変更後" in page and "非公開の変更前" not in page and "個人の訂正理由" not in page
    # An administrator cannot make somebody else's shared record private.
    data["visibility"] = "private"
    assert records.client.post(f"/children/{records.child_id}/records/{log.id}/correct", data=data).status_code == 422
    records.current_user = author
    assert "非公開の変更前" in records.client.get(f"/children/{records.child_id}/records").text


@pytest.mark.parametrize("invalid", [{"observed_on": "bad"}, {"child_state": ""}, {"visibility": "invalid"}, {"shared_staff_ids": "invalid"}])
def test_validation_retains_other_inputs_without_saving(records, invalid):
    response = records.client.post(f"/children/{records.child_id}/records", data={"observed_on": date.today().isoformat(), "child_state": "入力した姿", "reflection": "消えてはいけない振り返り", "visibility": "shared", **invalid})
    assert response.status_code == 422
    assert "消えてはいけない振り返り" in response.text
    with Session(records.engine) as session:
        assert not session.exec(select(ChildObservationLog)).all()


def test_void_retains_reason_and_cannot_be_corrected(records):
    log = create(records)
    endpoint = f"/children/{records.child_id}/records/{log.id}"
    assert records.client.post(endpoint + "/void", data={"void_reason": "x" * 501}).status_code == 422
    assert records.client.post(endpoint + "/void", data={"void_reason": "誤登録"}, follow_redirects=False).status_code == 303
    assert "見本の記録" not in records.client.get(f"/children/{records.child_id}/records").text
    assert "誤登録" in records.client.get(f"/children/{records.child_id}/records?include_voided=true").text
    assert records.client.get(endpoint + "/correct").status_code == 403
    with Session(records.engine) as session:
        revision = session.exec(select(ChildObservationLogRevision)).one()
        assert revision.snapshot["action"] == "void"
        assert revision.created_by == str(records.current_user.user_id)


def test_correction_requires_reason_preserves_values_and_rejects_stale_version(records):
    log = create(records)
    endpoint = f"/children/{records.child_id}/records/{log.id}/correct"
    data = {"observed_on": date.today().isoformat(), "child_state": "保存待ちの訂正", "reflection": "訂正の振り返り"}
    for reason in ("", "x" * 501):
        response = records.client.post(endpoint, data={**data, "correction_reason": reason})
        assert response.status_code == 422
        assert "保存待ちの訂正" in response.text and "訂正の振り返り" in response.text
    response = records.client.post(endpoint, data={**data, "correction_reason": "訂正", "expected_updated_at": "stale"})
    assert response.status_code == 422
    with Session(records.engine) as session:
        assert session.get(ChildObservationLog, log.id).child_state == "見本の記録"
        assert not session.exec(select(ChildObservationLogRevision)).all()


def test_private_is_not_available_in_progress_source_even_to_author(records):
    create(records, child_state="個人メモは児童票の参照欄に出さない")
    assert "個人メモは児童票の参照欄に出さない" not in records.client.get(f"/children/{records.child_id}/progress-records/new").text


def test_view_only_can_read_shared_but_cannot_create(records):
    create(records, visibility="shared", child_state="閲覧のみ職員にも共有")
    records.current_user = StaffUser(role=Role.VIEW_ONLY, user_id=uuid4())
    assert "閲覧のみ職員にも共有" in records.client.get(f"/children/{records.child_id}/records").text
    assert records.client.get(f"/children/{records.child_id}/records/new").status_code == 403
    assert records.client.post(f"/children/{records.child_id}/records", data={}).status_code == 403


def test_legacy_records_keep_previous_access_scope(records):
    with Session(records.engine) as session:
        session.add(ChildObservationLog(child_id=records.child_id, observed_on=date.today(), child_state="既存の記録", created_by_name="元の職員"))
        session.commit()
    assert "既存の記録" in records.client.get(f"/children/{records.child_id}/records").text
    records.current_user = StaffUser(role=Role.CAN_EDIT, user_id=uuid4())
    assert "既存の記録" not in records.client.get(f"/children/{records.child_id}/records").text


STATES = ["present", "private_absent", "sick_absent", "unknown"]


@pytest.mark.parametrize("state", STATES)
def test_initial_status_saves_without_reason_even_with_alarm_and_never_notifies(checks, state):
    with Session(checks.engine) as session:
        session.add(AttendanceAlarmState(child_id=checks.child_id, target_date=checks.day, is_active=True, reasons=["no_contact_and_not_present"]))
        session.commit()
    with patch("routers.attendance_checks.notify_attendance_confirmation_needed") as notify:
        response = checks.client.post(f"/attendance-checks/{checks.child_id}/verification", data={"date": checks.day.isoformat(), "status": state, "notify_parent": "true"}, follow_redirects=False)
        assert response.status_code == 303
        notify.assert_not_called()
    with Session(checks.engine) as session:
        history = session.exec(select(AttendanceVerificationHistory)).one()
        assert history.previous_status is None and history.reason is None


@pytest.mark.parametrize("before,after", [(a,b) for a in STATES for b in STATES])
def test_every_status_transition_requires_reason_except_same_status(checks, before, after):
    url = f"/attendance-checks/{checks.child_id}/verification"
    data = {"date": checks.day.isoformat(), "status": before}
    assert checks.client.post(url, data=data, follow_redirects=False).status_code == 303
    data["status"] = after
    response = checks.client.post(url, data=data, follow_redirects=False)
    assert response.status_code == (303 if before == after else 400)
    with Session(checks.engine) as session:
        assert len(session.exec(select(AttendanceVerificationHistory)).all()) == 1
        assert session.exec(select(AttendanceVerification)).one().status.value == before
    data["reason"] = "誤入力"
    assert checks.client.post(url, data=data, follow_redirects=False).status_code == 303
    with Session(checks.engine) as session:
        histories = session.exec(select(AttendanceVerificationHistory).order_by(AttendanceVerificationHistory.id)).all()
        assert len(histories) == (1 if before == after else 2)
        if before != after:
            assert histories[-1].previous_status == before and histories[-1].reason == "誤入力"
