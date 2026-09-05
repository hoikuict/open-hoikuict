from datetime import timedelta

import pytest
from sqlmodel import Session, select

from auth import Role, StaffUser
from models import Notice, NoticeStatus, ParentAccount, ParentMailDelivery, ParentRegistrationRequest, User
from time_utils import utc_now
from test_guardian_account_sync import pilot as pilot_fixture
from test_parent_enrollment import invite, open_form, profile, review
import routers.parent_auth as registration_routes
import routers.staff_portal as home


@pytest.fixture
def pilot(monkeypatch):
    fixture = pilot_fixture.__wrapped__(monkeypatch)
    context = next(fixture)
    app = context[3]
    app.include_router(home.router)
    app.dependency_overrides[home.get_optional_current_staff_user] = app.dependency_overrides[
        registration_routes.get_current_staff_user
    ]
    try:
        yield context
    finally:
        fixture.close()


def submit(pilot):
    registration_id, account_id, token = invite(pilot)
    open_form(pilot[0], token)
    response = pilot[0].post("/parent-portal/register/enrollment", data=profile())
    assert "初回入力を受け付けました" in response.text
    return registration_id, account_id


@pytest.mark.parametrize("decision", ["approve", "reject", "resend"])
def test_home_counts_submitted_enrollment_and_removes_resolved_request(pilot, decision):
    client, engine, _, _ = pilot
    with Session(engine) as session:
        session.add(Notice(title="既存の承認依頼", body="検証", status=NoticeStatus.pending_approval))
        session.commit()
    assert client.get("/").context["approval_queue_count"] == 1
    registration_id, account_id = submit(pilot)
    response = client.get("/")
    assert response.status_code == 200 and response.context["approval_queue_count"] == 2
    items = [item for item in response.context["approval_queue_items"] if item["kind"] == "parent_registration"]
    assert len(items) == 1 and items[0]["title"] == "入園 はなさんの初回入力"
    assert "保護者の初回登録" in response.text and "検証用の住所" not in response.text
    url = f"/parent-accounts/{account_id}/authentication#registration-{registration_id}"
    assert items[0]["url"] == url and "no-store" in response.headers["cache-control"]
    detail = client.get(url)
    assert "検証用の住所" in detail.text and f'id="registration-{registration_id}"' in detail.text
    assert client.get("/staff/portal").context["approval_queue_count"] == 2
    if decision == "resend":
        with Session(engine) as session:
            for delivery in session.exec(select(ParentMailDelivery)).all():
                delivery.created_at = utc_now() - timedelta(minutes=2)
                session.add(delivery)
            session.commit()
        action = client.post(f"/parent-accounts/{account_id}/authentication/invite", data={"reason": "再入力を依頼"}, follow_redirects=False)
    else:
        action = review(client, account_id, registration_id, decision=decision)
    assert action.status_code == 303
    response = client.get("/")
    assert response.context["approval_queue_count"] == 1
    assert response.context["approval_queue_items"][0]["title"] == "既存の承認依頼"


def test_home_does_not_expose_intake_requests_to_non_admin_or_logged_out(pilot):
    client, engine, ids, app = pilot
    submit(pilot)
    with Session(engine) as session:
        staff = session.get(User, ids["actor"])
        staff.staff_role = "can_edit"
        session.add(staff)
        session.commit()
    app.dependency_overrides[home.get_optional_current_staff_user] = lambda: StaffUser(
        role=Role.CAN_EDIT, name="編集担当", user_id=ids["actor"],
    )
    response = client.get("/")
    assert response.context["approval_queue_count"] == 0
    assert "入園 はなさんの初回入力" not in response.text
    app.dependency_overrides[home.get_optional_current_staff_user] = lambda: None
    assert "入園 はなさんの初回入力" not in client.get("/").text


def test_home_includes_legacy_identity_registration_without_an_enrollment(pilot):
    client, engine, _, _ = pilot
    with Session(engine) as session:
        account = ParentAccount(display_name="検証 保護者", email="legacy@example.test")
        session.add(account)
        session.flush()
        registration = ParentRegistrationRequest(
            parent_account_id=account.id, email_normalized_snapshot=account.email,
            status="pending_review", submitted_at=utc_now(),
        )
        session.add(registration)
        session.commit()
    response = client.get("/")
    assert response.context["approval_queue_count"] == 1
    assert "検証 保護者さんの登録申請" in response.text


def test_home_reports_registration_load_failure_instead_of_empty_queue(pilot, monkeypatch):
    def unavailable(_session):
        raise RuntimeError("Synthetic database failure")

    monkeypatch.setattr(home, "list_pending_parent_registrations", unavailable)
    response = pilot[0].get("/")
    assert response.status_code == 200
    assert "保護者の初回登録の承認依頼を取得できませんでした" in response.text
    assert "現在、承認待ちの依頼はありません" not in response.text
