from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import xml.etree.ElementTree as ET

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
import pytest

from auth import Role, StaffUser
from csrf import CSRF_COOKIE_NAME, CsrfTokenMiddleware, verify_csrf
from models import (
    AuthenticationEvent,
    Child,
    Family,
    LoginThrottle,
    ParentAccount,
    ParentChildLink,
    ParentEnrollment,
    ParentMailDelivery,
    ParentPublicRegistration,
    ParentPublicRegistrationSettings,
    ParentRegistrationRequest,
    ParentRegistrationSession,
    PasswordCredential,
)
from parent_auth import dispatch_pending_parent_mail, token_hash
import parent_public_registration as public
import routers.parent_auth as routes
from test_guardian_account_sync import pilot as pilot_fixture, create_account
from test_parent_enrollment import profile, review
from time_utils import utc_now


@pytest.fixture
def pilot(monkeypatch):
    yield from pilot_fixture.__wrapped__(monkeypatch)


def enable(pilot):
    assert (
        pilot[0]
        .post("/parent-accounts/registration-qr", data={"enabled": "yes"})
        .status_code
        == 200
    )


def begin(pilot, email="signup@example.test"):
    response = pilot[0].post(public.PUBLIC_PATH, data={"email": email})
    assert response.status_code == 200, response.text
    with Session(pilot[1]) as session:
        registration = session.exec(
            select(ParentRegistrationRequest).order_by(
                ParentRegistrationRequest.created_at.desc()
            )
        ).first()
        mail = session.exec(
            select(ParentMailDelivery).where(
                ParentMailDelivery.registration_request_id == registration.id
            )
        ).one()
        code = mail.body.split("登録コード：\n")[1].split()[0]
        return registration.id, registration.parent_account_id, code


def submit(pilot, **changes):
    registration_id, account_id, code = begin(pilot)
    response = pilot[0].post(
        "/parent-portal/register/invite/verify", data={"token": code}
    )
    assert response.status_code == 200
    assert response.context["public_application"]
    assert 'value="初回申請"' not in response.text
    assert (
        pilot[0]
        .post("/parent-portal/register/enrollment", data=profile(**changes))
        .status_code
        == 200
    )
    return registration_id, account_id, code


def test_shared_qr_is_closed_until_admin_enables_it(pilot):
    client, engine, _, _ = pilot
    assert "受け付けていません" in client.get(public.PUBLIC_PATH).text
    assert (
        client.post(
            public.PUBLIC_PATH, data={"email": "signup@example.test"}
        ).status_code
        == 403
    )
    assert "共通QR・申請受付" in client.get("/parent-accounts/").text
    page = client.get("/parent-accounts/registration-qr")
    assert (
        page.status_code == 200
        and page.context["registration_url"]
        == "https://testserver" + public.PUBLIC_PATH
    )
    qr = client.get("/parent-accounts/registration-qr.svg")
    assert qr.status_code == 200 and "no-store" in qr.headers["cache-control"]
    root = ET.fromstring(qr.content)
    assert (
        root.tag.endswith("svg")
        and root.find("{http://www.w3.org/2000/svg}path") is not None
    )
    with Session(engine) as session:
        assert not session.exec(select(ParentAccount)).all()
    enable(pilot)
    assert 'name="email"' in client.get(public.PUBLIC_PATH).text
    with Session(engine) as session:
        assert session.get(ParentPublicRegistrationSettings, 1).enabled
        assert session.exec(
            select(AuthenticationEvent).where(
                AuthenticationEvent.reason_code == "enabled"
            )
        ).one()


def test_email_verify_submit_explicit_approval_and_login(pilot):
    client, engine, _, _ = pilot
    enable(pilot)
    registration_id, account_id, raw_code = begin(pilot)
    with Session(engine) as session:
        registration = session.get(ParentRegistrationRequest, registration_id)
        assert registration.invitation_token_hash == token_hash(raw_code)
        assert session.get(ParentPublicRegistration, registration_id)
        assert not session.exec(select(ParentChildLink)).all()
        assert session.exec(select(PasswordCredential)).one().password_hash is None
        assert len(session.exec(select(Child)).all()) == 2
        dispatch_pending_parent_mail(session)
        assert session.exec(select(ParentMailDelivery)).one().status == "captured"
    assert (
        "共通QRからの初回申請"
        in client.get(f"/parent-accounts/{account_id}/authentication").text
    )
    assert client.post(
        "/parent-portal/register/enrollment", data=profile()
    ).url.path.endswith("status")
    response = client.post(
        "/parent-portal/register/invite/verify", data={"token": raw_code}
    )
    assert response.status_code == 200 and response.context["public_application"]
    assert "旧住所" not in response.text and "検証担当" not in response.text
    assert (
        client.post(
            "/parent-portal/register/invite/verify", data={"token": raw_code}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/parent-portal/register/enrollment",
            data=profile(child_id=999, email="forged@example.test"),
        ).status_code
        == 200
    )
    with Session(engine) as session:
        assert (
            session.get(ParentRegistrationRequest, registration_id).status
            == "pending_review"
        )
        assert session.get(ParentEnrollment, registration_id).child_name == "入園 はな"
        assert not session.exec(select(ParentChildLink)).all()
    page = client.get(f"/parent-accounts/{account_id}/authentication")
    assert 'name="public_child_target"' in page.text
    assert review(client, account_id, registration_id).status_code == 400
    assert (
        review(
            client,
            account_id,
            registration_id,
            public_child_target="new",
            enrollment_confirmed="",
        ).status_code
        == 400
    )
    assert (
        review(
            client, account_id, registration_id, public_child_target="new"
        ).status_code
        == 303
    )
    assert (
        review(
            client, account_id, registration_id, public_child_target="new"
        ).status_code
        == 400
    )
    with Session(engine) as session:
        assert len(session.exec(select(Child)).all()) == 3
        assert len(session.exec(select(ParentChildLink)).all()) == 1
        assert session.get(ParentAccount, account_id).email == "signup@example.test"
        mail = session.exec(
            select(ParentMailDelivery).where(
                ParentMailDelivery.message_type == "completion"
            )
        ).one()
        completion_code = mail.body.split("登録コード：\n")[1].split()[0]
    assert (
        client.post(
            "/parent-portal/register/complete/verify", data={"token": completion_code}
        ).status_code
        == 200
    )
    password = "River!7892Long-Phrase"
    assert (
        client.post(
            "/parent-portal/register/complete",
            data={"password": password, "password_confirmation": password},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/parent-portal/login",
            data={"login_id": "signup@example.test", "password": password},
            follow_redirects=False,
        ).status_code
        == 303
    )
    assert client.get("/parent-portal/children/profile").status_code == 200


def test_browser_review_error_preserves_inputs_and_pending_application(pilot):
    client, engine, _, _ = pilot
    enable(pilot)
    registration_id, account_id, _ = submit(pilot)
    response = client.post(
        f"/parent-accounts/{account_id}/authentication/registrations/{registration_id}/review",
        data={"decision": "approve", "reason": "面談で本人確認済み", "enrollment_confirmed": "yes", "public_child_target": ""},
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 400 and "text/html" in response.headers["content-type"]
    assert "面談で本人確認済み" in response.text and 'role="alert"' in response.text
    assert response.context["review_values"]["enrollment_confirmed"] == "yes"
    with Session(engine) as session:
        assert session.get(ParentRegistrationRequest, registration_id).status == "pending_review"
        assert not session.exec(select(ParentChildLink)).all()


def test_approval_can_link_an_existing_child_without_duplicate_records(pilot):
    client, engine, ids, _ = pilot
    enable(pilot)
    registration_id, account_id, _ = submit(
        pilot, last_name="検証", first_name="葵", birth_date="2021-05-04"
    )
    with Session(engine) as session:
        original_other_guardian = dict(
            session.get(Family, ids["family"]).guardian_profiles()[1]
        )
    assert (
        review(
            client,
            account_id,
            registration_id,
            public_child_target=f"{ids['sibling']}:1",
        ).status_code
        == 400
    )
    assert (
        review(
            client,
            account_id,
            registration_id,
            public_child_target=f"{ids['child']}:99",
        ).status_code
        == 400
    )
    assert (
        review(
            client, account_id, registration_id, public_child_target="new"
        ).status_code
        == 400
    )
    assert (
        review(
            client, account_id, registration_id, public_child_target=f"{ids['child']}:1"
        ).status_code
        == 303
    )
    with Session(engine) as session:
        assert len(session.exec(select(Child)).all()) == 2
        assert session.exec(select(ParentChildLink)).one().child_id == ids["child"]
        other_guardian = session.get(Family, ids["family"]).guardian_profiles()[1]
        assert all(
            other_guardian[key] == value
            for key, value in original_other_guardian.items()
        )
        assert not other_guardian.get("parent_account_id")


def test_existing_account_and_pending_review_cannot_be_replaced_by_public_request(
    pilot,
):
    client, engine, _, _ = pilot
    existing_id = create_account(pilot)
    enable(pilot)
    generic_existing = client.post(
        public.PUBLIC_PATH, data={"email": "PARENT@example.test"}
    )
    registration_id, account_id, _ = submit(pilot)
    generic_pending = client.post(
        public.PUBLIC_PATH, data={"email": "signup@example.test"}
    )
    assert generic_existing.status_code == generic_pending.status_code == 200
    assert generic_existing.text == generic_pending.text
    with Session(engine) as session:
        assert len(session.exec(select(ParentAccount)).all()) == 2
        assert len(session.exec(select(ParentRegistrationRequest)).all()) == 1
        assert (
            session.get(ParentRegistrationRequest, registration_id).status
            == "pending_review"
        )
        assert session.get(ParentAccount, existing_id).email == "parent@example.test"
        assert session.get(ParentAccount, account_id).email == "signup@example.test"
        assert len(session.exec(select(ParentMailDelivery)).all()) == 1


def test_network_limit_counts_requests_and_ignores_forged_forwarding_headers(pilot):
    client, engine, _, _ = pilot
    enable(pilot)
    for index in range(5):
        response = client.post(
            public.PUBLIC_PATH, data={"email": f"signup{index}@example.test"}
        )
        assert response.status_code == 200
    response = client.post(
        public.PUBLIC_PATH,
        data={"email": "sixth@example.test"},
        headers={
            "X-Forwarded-For": "198.51.100.1",
            "CF-Connecting-IP": "198.51.100.2",
        },
    )
    assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
    with Session(engine) as session:
        assert len(session.exec(select(ParentAccount)).all()) == 5
        bucket = session.exec(
            select(LoginThrottle).where(LoginThrottle.bucket_type == "signup_ip")
        ).one()
        assert bucket.failure_count == 5 and "testclient" not in bucket.bucket_hash
    assert client.get("/parent-portal/login").status_code == 200


def test_rate_limit_recovers_and_is_atomic_across_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("HOIKUICT_ENV", "test")
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "limits.db"), connect_args={"timeout": 15}
    )
    SQLModel.metadata.create_all(engine)
    now = utc_now()
    monkeypatch.setattr(public, "utc_now", lambda: now)

    def attempt(_):
        with Session(engine) as session:
            try:
                public.consume_registration_limit(session, "192.0.2.1")
            except public.RegistrationLimited:
                return False
            return True

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(8))) == 5
    assert not attempt(None)
    now += timedelta(minutes=16)
    assert attempt(None)
    with Session(engine) as session:
        assert session.exec(select(LoginThrottle)).one().failure_count == 1
    engine.dispose()


@pytest.mark.parametrize(
    "email",
    [
        "",
        "invalid",
        "a\r\nBcc:x@example.test",
        "a" * 256 + "@example.test",
        "\ud800@example.test",
    ],
)
def test_invalid_addresses_create_no_account_and_count_toward_network_limit(
    pilot, email
):
    enable(pilot)
    # Direct service call covers a surrogate value that an HTTP client cannot encode.
    if "\ud800" in email:
        with Session(pilot[1]) as session, pytest.raises(ValueError):
            public.request_public_registration(session, email)
        return
    assert pilot[0].post(public.PUBLIC_PATH, data={"email": email}).status_code == 400
    with Session(pilot[1]) as session:
        assert not session.exec(select(ParentAccount)).all()
        assert (
            session.exec(
                select(LoginThrottle).where(LoginThrottle.bucket_type == "signup_ip")
            )
            .one()
            .failure_count
            == 1
        )


def test_closing_reception_does_not_cancel_an_existing_application(pilot):
    client, engine, _, _ = pilot
    enable(pilot)
    registration_id, _, code = begin(pilot)
    assert (
        client.post(
            "/parent-accounts/registration-qr", data={"enabled": "no"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            public.PUBLIC_PATH, data={"email": "another@example.test"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/parent-portal/register/invite/verify", data={"token": code}
        ).status_code
        == 200
    )
    assert (
        client.post("/parent-portal/register/enrollment", data=profile()).status_code
        == 200
    )
    with Session(engine) as session:
        assert (
            session.get(ParentRegistrationRequest, registration_id).status
            == "pending_review"
        )


def test_resend_keeps_public_origin_and_cancels_old_link(pilot):
    client, engine, _, _ = pilot
    enable(pilot)
    old_id, account_id, old_code = begin(pilot)
    with Session(engine) as session:
        mail = session.exec(select(ParentMailDelivery)).one()
        mail.created_at -= timedelta(minutes=2)
        session.add(mail)
        session.commit()
    assert (
        client.post(
            f"/parent-accounts/{account_id}/authentication/invite",
            data={"reason": "再案内"},
        ).status_code
        == 200
    )
    with Session(engine) as session:
        latest = session.exec(
            select(ParentRegistrationRequest).order_by(
                ParentRegistrationRequest.created_at.desc()
            )
        ).first()
        assert latest.id != old_id and session.get(ParentPublicRegistration, latest.id)
        assert session.get(ParentRegistrationRequest, old_id).status == "cancelled"
    assert (
        client.post(
            "/parent-portal/register/invite/verify", data={"token": old_code}
        ).status_code
        == 400
    )


def test_public_resend_limits_each_recipient_and_revokes_old_codes(pilot, monkeypatch):
    client, engine, _, _ = pilot
    enable(pilot)
    now = utc_now()
    monkeypatch.setattr(public, "utc_now", lambda: now)
    first_id, _, first_code = begin(pilot)
    for _ in range(2):
        now += timedelta(seconds=61)
        begin(pilot)
    now += timedelta(seconds=61)
    assert (
        client.post(
            public.PUBLIC_PATH, data={"email": "signup@example.test"}
        ).status_code
        == 200
    )
    with Session(engine) as session:
        assert len(session.exec(select(ParentMailDelivery)).all()) == 3
        assert len(session.exec(select(ParentAccount)).all()) == 1
        assert session.get(ParentRegistrationRequest, first_id).status == "cancelled"
    assert (
        client.post(
            "/parent-portal/register/invite/verify", data={"token": first_code}
        ).status_code
        == 400
    )


def test_public_resend_does_not_interrupt_a_verified_active_form(pilot, monkeypatch):
    client, engine, _, _ = pilot
    enable(pilot)
    registration_id, _, code = begin(pilot)
    assert (
        client.post(
            "/parent-portal/register/invite/verify", data={"token": code}
        ).status_code
        == 200
    )
    later = utc_now() + timedelta(minutes=2)
    monkeypatch.setattr(public, "utc_now", lambda: later)
    assert (
        client.post(
            public.PUBLIC_PATH, data={"email": "signup@example.test"}
        ).status_code
        == 200
    )
    with Session(engine) as session:
        assert len(session.exec(select(ParentRegistrationRequest)).all()) == 1
        assert (
            session.get(ParentRegistrationRequest, registration_id).status == "invited"
        )
    assert (
        client.post("/parent-portal/register/enrollment", data=profile()).status_code
        == 200
    )


def test_non_admin_cannot_open_qr_or_change_reception(pilot):
    client, _, ids, app = pilot
    app.dependency_overrides[routes.get_current_staff_user] = lambda: StaffUser(
        role=Role.CAN_EDIT, name="担当", user_id=ids["actor"]
    )
    for path in [
        "/parent-accounts/registration-qr",
        "/parent-accounts/registration-qr.svg",
    ]:
        assert client.get(path).status_code == 403
    assert (
        client.post(
            "/parent-accounts/registration-qr", data={"enabled": "yes"}
        ).status_code
        == 403
    )


def test_csrf_is_required_for_public_requests_and_reception_changes(pilot, monkeypatch):
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "1")
    enable(pilot)
    app = FastAPI(dependencies=[Depends(verify_csrf)])
    app.add_middleware(CsrfTokenMiddleware)
    app.include_router(routes.router)
    app.dependency_overrides.update(pilot[3].dependency_overrides)
    with TestClient(app, base_url="https://testserver") as client:
        client.get(public.PUBLIC_PATH)
        token = client.cookies.get(CSRF_COOKIE_NAME)
        for path, data in [
            (public.PUBLIC_PATH, {"email": "signup@example.test"}),
            ("/parent-accounts/registration-qr", {"enabled": "no"}),
        ]:
            assert client.post(path, data=data).status_code == 403
            assert (
                client.post(path, data={**data, "csrf_token": token}).status_code == 200
            )


def test_invitation_exchange_is_single_use_under_concurrent_access(
    tmp_path, monkeypatch
):
    from parent_auth import AuthenticationFailed, exchange_invitation_token

    monkeypatch.setenv("HOIKUICT_ENV", "test")
    engine = create_engine(
        "sqlite:///" + str(tmp_path / "exchange.db"), connect_args={"timeout": 15}
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        account = ParentAccount(display_name="試験", email="signup@example.test")
        session.add(account)
        session.flush()
        registration = ParentRegistrationRequest(
            parent_account_id=account.id,
            email_normalized_snapshot=account.email,
            invitation_token_hash=token_hash("single-use-code"),
            invitation_expires_at=utc_now() + timedelta(hours=1),
        )
        session.add(registration)
        session.commit()

    def attempt(_):
        with Session(engine) as session:
            try:
                return bool(exchange_invitation_token(session, "single-use-code"))
            except AuthenticationFailed:
                return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, range(4))) == 1
    with Session(engine) as session:
        assert len(session.exec(select(ParentRegistrationSession)).all()) == 1
    engine.dispose()
