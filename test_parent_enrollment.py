from datetime import timedelta

import pytest
from sqlmodel import Session, select

from auth import Role, StaffUser
from family_support import bootstrap_family_data
from local_auth import AuthenticationFailed
from models import (
    Child,
    Family,
    Guardian,
    ParentAccount,
    ParentChildLink,
    ParentEnrollment,
    ParentMailDelivery,
    ParentRegistrationRequest,
    ParentRegistrationSession,
)
from parent_auth import dispatch_pending_parent_mail, token_hash
from time_utils import utc_now
from test_guardian_account_sync import pilot as pilot_fixture
import routers.parent_auth as routes


@pytest.fixture
def pilot(monkeypatch):
    yield from pilot_fixture.__wrapped__(monkeypatch)


def invite(pilot, **extra):
    client, engine, _, _ = pilot
    response = client.post(
        "/parent-accounts/enrollment/invite",
        data={
            "child_name": "入園 はな",
            "email": "intake@example.test",
            **extra,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    with Session(engine) as session:
        registration = session.exec(
            select(ParentRegistrationRequest).order_by(
                ParentRegistrationRequest.created_at.desc()
            )
        ).first()
        delivery = session.exec(
            select(ParentMailDelivery).where(
                ParentMailDelivery.registration_request_id == registration.id
            )
        ).one()
        return (
            registration.id,
            registration.parent_account_id,
            delivery.body.split("#")[1].split()[0],
        )


def open_form(client, raw_token):
    response = client.post(
        "/parent-portal/register/invite/verify", data={"token": raw_token}
    )
    assert response.status_code == 200, response.text
    assert "入園時の初回情報入力" in response.text
    return response


def profile(**extra):
    return {
        "last_name": "入園",
        "first_name": "はな",
        "last_name_kana": "ニュウエン",
        "first_name_kana": "ハナ",
        "birth_date": "2023-06-10",
        "enrollment_date": "2027-04-01",
        "home_address": "検証用の住所",
        "g1_last_name": "入園",
        "g1_first_name": "あい",
        "g1_last_name_kana": "ニュウエン",
        "g1_first_name_kana": "アイ",
        "g1_relationship": "母",
        "g1_phone": "09012345678",
        "g1_workplace": "検証会社",
        "g1_workplace_address": "勤務先の住所",
        "g1_workplace_phone": "0312345678",
        "g2_last_name": "入園",
        "g2_first_name": "たろう",
        "g2_relationship": "父",
        **extra,
    }


def review(client, account_id, registration_id, **extra):
    return client.post(
        f"/parent-accounts/{account_id}/authentication/registrations/{registration_id}/review",
        data={
            "decision": "approve",
            "reason": "保護者と園児・提出情報を確認",
            "enrollment_confirmed": "yes",
            **extra,
        },
        follow_redirects=False,
    )


def test_two_fields_to_parent_input_review_and_login(pilot):
    client, engine, ids, _ = pilot
    page = client.get("/parent-accounts/enrollment/new")
    assert page.status_code == 200
    assert 'name="child_name"' in page.text and 'name="email"' in page.text
    assert 'name="birth_date"' not in page.text
    registration_id, account_id, raw_token = invite(pilot)
    assert not client.get("/parent-accounts/").context["pending_registrations"]
    with Session(engine) as session:
        bootstrap_family_data(session)
        session.commit()
        assert session.get(ParentAccount, account_id).family_id is None
        assert len(session.exec(select(Child)).all()) == 2
        assert not session.exec(select(ParentChildLink)).all()
        assert session.get(ParentEnrollment, registration_id).submitted_data is None
        dispatch_pending_parent_mail(session, registration_request_id=registration_id)
        assert session.exec(select(ParentMailDelivery)).one().status == "captured"
    auth_page = client.get(f"/parent-accounts/{account_id}/authentication")
    assert "照合用氏名と生年月日を登録" not in auth_page.text
    assert "初回設定コードを発行" not in auth_page.text
    assert raw_token not in auth_page.text
    assert (
        client.post(
            f"/parent-accounts/{account_id}/authentication/activate",
            data={"reason": "test"},
        ).status_code
        == 400
    )
    form = open_form(client, raw_token)
    assert "検証担当" not in form.text and "旧住所" not in form.text
    assert len(client.cookies.get(routes.REGISTRATION_COOKIE)) > 20
    response = client.post(
        "/parent-portal/register/enrollment",
        data=profile(
            child_id=ids["sibling"],
            family_id=ids["other"],
            g1_parent_account_id=999,
            email="attacker@example.test",
        ),
    )
    assert response.status_code == 200 and "初回入力を受け付けました" in response.text
    inbox = client.get("/parent-accounts/")
    pending = inbox.context["pending_registrations"]
    assert len(pending) == 1 and pending[0].registration_id == registration_id
    assert "確認待ちの初回登録（1件）" in inbox.text
    assert f'/authentication#registration-{registration_id}' in inbox.text
    assert raw_token not in inbox.text and "no-store" in inbox.headers["cache-control"]
    submitted = client.get(f"/parent-accounts/{account_id}/authentication")
    assert f'id="registration-{registration_id}"' in submitted.text and "検証用の住所" in submitted.text
    with Session(engine) as session:
        registration = session.get(ParentRegistrationRequest, registration_id)
        assert registration.status == "pending_review"
        assert (
            not registration.guardian_name_matched
        )  # no fabricated ledger verification
        assert not session.exec(select(ParentChildLink)).all()
        assert len(session.exec(select(Child)).all()) == 2
    assert (
        review(client, account_id, registration_id, enrollment_confirmed="").status_code
        == 400
    )
    assert review(client, account_id, registration_id).status_code == 303
    assert not client.get("/parent-accounts/").context["pending_registrations"]
    assert review(client, account_id, registration_id).status_code == 400
    with Session(engine) as session:
        enrollment = session.get(ParentEnrollment, registration_id)
        child = session.get(Child, enrollment.child_id)
        account = session.get(ParentAccount, account_id)
        assert len(session.exec(select(Child)).all()) == 3
        assert (
            child.full_name == "入園 はな"
            and child.birth_date.isoformat() == "2023-06-10"
        )
        assert account.display_name == "入園 あい"
        assert account.email == "intake@example.test"
        assert account.home_address == child.family.home_address == "検証用の住所"
        assert account.phone == "09012345678" and account.workplace == "検証会社"
        assert child.family.guardian_profiles()[0]["parent_account_id"] == account_id
        assert len(child.guardians) == 2
        assert [
            item.child_id for item in session.exec(select(ParentChildLink)).all()
        ] == [child.id]
        delivery = session.exec(
            select(ParentMailDelivery).where(
                ParentMailDelivery.message_type == "completion"
            )
        ).one()
        completion_token = delivery.body.split("#")[1].split()[0]
    response = client.post(
        "/parent-portal/register/complete/verify", data={"token": completion_token}
    )
    assert response.status_code == 200
    password = "River!7892Long-Phrase"
    response = client.post(
        "/parent-portal/register/complete",
        data={"password": password, "password_confirmation": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    response = client.post(
        "/parent-portal/login",
        data={"login_id": "intake@example.test", "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert client.get("/parent-portal/children/profile").status_code == 200


def test_existing_child_preserves_other_guardian_and_links_only_selected_child(pilot):
    client, engine, ids, _ = pilot
    with Session(engine) as session:
        child = session.get(Child, ids["child"])
        child.extra_data = {"staff_only_note": "既存メモ"}
        session.add(child)
        session.commit()
    registration_id, account_id, raw_token = invite(
        pilot, child_id=ids["child"], guardian_order=1
    )
    form = open_form(client, raw_token)
    assert "検証 葵" in form.text and 'name="g2_last_name"' not in form.text
    assert "09011112222" not in form.text and 'value="勤務先住所"' not in form.text
    response = client.post(
        "/parent-portal/register/enrollment",
        data=profile(last_name="検証", first_name="葵"),
    )
    assert response.status_code == 200
    assert review(client, account_id, registration_id).status_code == 303
    with Session(engine) as session:
        assert len(session.exec(select(Child)).all()) == 2
        assert (
            session.get(Child, ids["child"]).extra_data["staff_only_note"] == "既存メモ"
        )
        family = session.get(Family, ids["family"])
        assert family.guardian_profiles()[1]["first_name"] == "太郎"
        assert session.get(Child, ids["sibling"]).home_address == "検証用の住所"
        assert [
            link.child_id for link in session.exec(select(ParentChildLink)).all()
        ] == [ids["child"]]
        assert len(session.exec(select(Guardian)).all()) == 4


def test_expired_session_resend_revokes_old_draft_and_keeps_previous_history(pilot):
    client, engine, _, _ = pilot
    registration_id, account_id, raw_token = invite(pilot)
    open_form(client, raw_token)
    old_state = client.cookies.get(routes.REGISTRATION_COOKIE)
    with Session(engine) as session:
        state = session.get(ParentRegistrationSession, token_hash(old_state))
        state.expires_at = utc_now() - timedelta(seconds=1)
        for delivery in session.exec(select(ParentMailDelivery)).all():
            delivery.created_at = utc_now() - timedelta(minutes=2)
            session.add(delivery)
        session.add(state)
        session.commit()
    response = client.post(
        "/parent-portal/register/enrollment", data=profile(), follow_redirects=False
    )
    assert response.status_code == 303
    response = client.post(
        f"/parent-accounts/{account_id}/authentication/invite",
        data={"reason": "再送"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with Session(engine) as session:
        assert (
            session.get(ParentRegistrationRequest, registration_id).status
            == "cancelled"
        )
        assert len(session.exec(select(ParentEnrollment)).all()) == 2
        assert len(session.exec(select(ParentAccount)).all()) == 1
        assert len(session.exec(select(Child)).all()) == 2
        assert (
            session.exec(
                select(ParentMailDelivery).where(
                    ParentMailDelivery.registration_request_id == registration_id
                )
            )
            .one()
            .status
            == "cancelled"
        )


def test_validation_submission_replay_and_identity_route_cannot_bypass(pilot):
    client, engine, _, _ = pilot
    registration_id, account_id, raw_token = invite(pilot)
    open_form(client, raw_token)
    state = client.cookies.get(routes.REGISTRATION_COOKIE)
    with Session(engine) as session:
        from parent_auth import submit_parent_identity

        with pytest.raises(AuthenticationFailed):
            submit_parent_identity(
                session,
                raw_state=state,
                guardian_name="test",
                child_name="test",
                child_birth_date=utc_now().date(),
            )
    for invalid in [
        profile(g1_phone=""),
        profile(birth_date="3000-01-01"),
        profile(g2_first_name=""),
        profile(first_name="別名"),
    ]:
        response = client.post("/parent-portal/register/enrollment", data=invalid)
        assert response.status_code == 400
        assert "検証会社" in response.text  # correction preserves typed fields
    assert (
        client.post("/parent-portal/register/enrollment", data=profile()).status_code
        == 200
    )
    client.cookies.set(routes.REGISTRATION_COOKIE, state)
    assert (
        client.post(
            "/parent-portal/register/enrollment", data=profile(), follow_redirects=False
        ).status_code
        == 303
    )
    assert (
        review(
            client,
            account_id,
            registration_id,
            decision="reject",
            enrollment_confirmed="",
        ).status_code
        == 303
    )
    with Session(engine) as session:
        assert not session.exec(select(ParentChildLink)).all()
        assert (
            session.get(ParentRegistrationRequest, registration_id).status == "rejected"
        )


def test_changed_ledger_blocks_approval_without_overwriting(pilot):
    client, engine, ids, _ = pilot
    registration_id, account_id, raw_token = invite(
        pilot, child_id=ids["child"], guardian_order=1
    )
    open_form(client, raw_token)
    client.post(
        "/parent-portal/register/enrollment",
        data=profile(last_name="検証", first_name="葵"),
    )
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        family.home_address = "招待後に園が訂正した住所"
        session.add(family)
        session.commit()
    response = review(client, account_id, registration_id)
    assert response.status_code == 400 and "変更されています" in response.text
    with Session(engine) as session:
        assert (
            session.get(Family, ids["family"]).home_address
            == "招待後に園が訂正した住所"
        )
        assert not session.exec(select(ParentChildLink)).all()
        assert (
            session.get(ParentRegistrationRequest, registration_id).status
            == "pending_review"
        )


def test_staff_authorization_duplicate_email_and_unknown_child(pilot):
    client, engine, ids, app = pilot
    invite(pilot)
    response = client.post(
        "/parent-accounts/enrollment/invite",
        data={"child_name": "別の子", "email": "INTAKE@example.test"},
    )
    assert response.status_code == 400
    response = client.post(
        "/parent-accounts/enrollment/invite",
        data={"child_name": "別の子", "email": "other@example.test", "child_id": 999},
    )
    assert response.status_code == 400
    with Session(engine) as session:
        assert len(session.exec(select(ParentAccount)).all()) == 1
    app.dependency_overrides[routes.get_current_staff_user] = lambda: StaffUser(
        role=Role.CAN_EDIT, name="職員", user_id=ids["actor"]
    )
    assert client.get("/parent-accounts/enrollment/new").status_code == 403
    assert (
        client.post(
            "/parent-accounts/enrollment/invite",
            data={"child_name": "別の子", "email": "other@example.test"},
        ).status_code
        == 403
    )


def test_resend_can_correct_invited_name_and_old_session_is_invalid(pilot):
    client, engine, _, _ = pilot
    registration_id, account_id, raw_token = invite(pilot)
    open_form(client, raw_token)
    with Session(engine) as session:
        delivery = session.exec(select(ParentMailDelivery)).one()
        delivery.created_at = utc_now() - timedelta(minutes=2)
        session.add(delivery)
        session.commit()
    response = client.post(
        f"/parent-accounts/{account_id}/authentication/invite",
        data={"reason": "名前の表記を訂正", "enrollment_child_name": "入園 ハナ"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert (
        client.post(
            "/parent-portal/register/enrollment", data=profile(), follow_redirects=False
        ).status_code
        == 303
    )
    with Session(engine) as session:
        assert (
            session.get(ParentRegistrationRequest, registration_id).status
            == "cancelled"
        )
        newest = session.exec(
            select(ParentRegistrationRequest).order_by(
                ParentRegistrationRequest.created_at.desc()
            )
        ).first()
        assert session.get(ParentEnrollment, newest.id).child_name == "入園 ハナ"
        assert session.get(ParentAccount, account_id).email == "intake@example.test"


def test_enrollment_routes_use_app_csrf_protection(pilot, monkeypatch):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    from csrf import CsrfTokenMiddleware, verify_csrf, CSRF_COOKIE_NAME

    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "1")
    _, engine, _, existing_app = pilot
    app = FastAPI(dependencies=[Depends(verify_csrf)])
    app.add_middleware(CsrfTokenMiddleware)
    app.include_router(routes.router)
    app.dependency_overrides.update(existing_app.dependency_overrides)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/parent-accounts/enrollment/new").status_code == 200
        data = {"child_name": "入園 はな", "email": "csrf-test@example.test"}
        assert (
            client.post("/parent-accounts/enrollment/invite", data=data).status_code
            == 403
        )
        data["csrf_token"] = client.cookies.get(CSRF_COOKIE_NAME)
        assert (
            client.post(
                "/parent-accounts/enrollment/invite", data=data, follow_redirects=False
            ).status_code
            == 303
        )
        with Session(engine) as session:
            delivery = session.exec(select(ParentMailDelivery)).one()
            raw_token = delivery.body.split("#")[1].split()[0]
        assert (
            client.post(
                "/parent-portal/register/invite/verify",
                data={"token": raw_token, "csrf_token": data["csrf_token"]},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/parent-portal/register/enrollment", data=profile()
            ).status_code
            == 403
        )
        response = client.post(
            "/parent-portal/register/enrollment",
            data={**profile(), "csrf_token": data["csrf_token"]},
        )
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
        assert response.headers["referrer-policy"] == "no-referrer"


def test_pending_intake_inbox_is_only_shown_to_admins(pilot):
    client, _, _, app = pilot
    _, _, token = invite(pilot)
    open_form(client, token)
    assert client.post("/parent-portal/register/enrollment", data=profile()).status_code == 200
    assert len(client.get("/parent-accounts/").context["pending_registrations"]) == 1
    app.dependency_overrides[routes.get_current_staff_user] = lambda: StaffUser(
        role=Role.CAN_EDIT, name="編集担当", can_manage_child_records=True,
    )
    response = client.get("/parent-accounts/")
    assert not response.context["pending_registrations"]
    assert "提出内容を確認する" not in response.text
