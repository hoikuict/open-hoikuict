from datetime import timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from csrf import CSRF_COOKIE_NAME, CsrfTokenMiddleware, verify_csrf
from models import ParentMailDelivery, ParentRegistrationRequest, ParentRegistrationSession
from parent_auth import token_hash
from time_utils import utc_now
from test_guardian_account_sync import pilot as pilot_fixture
from test_parent_enrollment import invite, profile, review
import routers.parent_auth as routes


@pytest.fixture
def pilot(monkeypatch):
    yield from pilot_fixture.__wrapped__(monkeypatch)


def mail_code(pilot, message_type):
    with Session(pilot[1]) as session:
        mail = session.exec(select(ParentMailDelivery).where(
            ParentMailDelivery.message_type == message_type
        )).one()
        code = mail.body.split("登録コード：\n")[1].split()[0]
        link = next(line for line in mail.body.splitlines() if line.startswith("https://"))
        assert link.endswith("#" + code)
        assert "Cloudflareの認証コードとは別" in mail.body
        return code, link


def prepare_completion(pilot):
    client = pilot[0]
    registration_id, account_id, code = invite(pilot)
    assert client.post("/parent-portal/register/invite/verify", data={"token": code}).status_code == 200
    assert client.post("/parent-portal/register/enrollment", data=profile()).status_code == 200
    assert review(client, account_id, registration_id).status_code == 303
    return registration_id, account_id, mail_code(pilot, "completion")


@pytest.mark.parametrize("use_link", [False, True])
def test_fragment_lost_during_access_can_finish_both_mail_steps(pilot, use_link):
    client = pilot[0]
    registration_id, account_id, _ = invite(pilot)
    code, link = mail_code(pilot, "invitation")
    # Access redirects cannot forward a URL fragment to the origin server.
    page = client.get("/parent-portal/register/invite")
    assert page.status_code == 200
    assert "登録コードまたはメールのリンク" in page.text
    assert code not in page.text and "no-store" in page.headers["cache-control"]
    assert page.headers["referrer-policy"] == "no-referrer"
    response = client.post("/parent-portal/register/invite/verify", data={
        "token": " \n" + (link if use_link else code) + "\n "
    })
    assert response.status_code == 200 and "入園時の初回情報入力" in response.text
    assert code not in response.text and "#" not in str(response.url)
    assert "httponly" in response.history[0].headers["set-cookie"].lower()
    # An identity cookie is not a password-setting session.
    assert "登録コードまたはメールのリンク" in client.get("/parent-portal/register/complete").text
    assert client.post("/parent-portal/register/enrollment", data=profile()).status_code == 200
    assert review(client, account_id, registration_id).status_code == 303
    code, link = mail_code(pilot, "completion")
    assert "登録コードまたはメールのリンク" in client.get("/parent-portal/register/complete").text
    response = client.post("/parent-portal/register/complete/verify", data={"token": link if use_link else code})
    assert response.status_code == 200 and "確認用パスワード" in response.text
    assert code not in response.text
    password = "River!7892Long-Phrase"
    assert client.post("/parent-portal/register/complete", data={
        "password": password, "password_confirmation": password
    }, follow_redirects=False).status_code == 303
    assert client.post("/parent-portal/login", data={
        "login_id": "intake@example.test", "password": password
    }, follow_redirects=False).status_code == 303


@pytest.mark.parametrize("value", [
    "", "123456", "x" * 2049, "無効なコード", "<script>alert(1)</script>",
    "https://other.example/parent-portal/register/invite#{code}",
    "https://testserver/parent-portal/register/complete#{code}",
    "https://testserver/parent-portal/register/invite?token={code}",
    "https://testserver/parent-portal/register/invite", "https://[bad/#x",
])
def test_invalid_paste_does_not_consume_invitation_or_echo_secret(pilot, value):
    client, engine, _, _ = pilot
    registration_id, _, code = invite(pilot)
    value = value.replace("{code}", code)
    response = client.post("/parent-portal/register/invite/verify", data={"token": value})
    assert response.status_code == 400
    assert 'name="token"' in response.text and "登録コードを確認できませんでした" in response.text
    assert code not in response.text and "<script>alert(1)</script>" not in response.text
    with Session(engine) as session:
        assert session.get(ParentRegistrationRequest, registration_id).invitation_token_hash == token_hash(code)
        assert not session.exec(select(ParentRegistrationSession)).all()


@pytest.mark.parametrize("purpose", ["invite", "complete"])
@pytest.mark.parametrize("invalid_reason", ["expired", "used", "cancelled"])
def test_code_fallback_preserves_expiry_single_use_and_cancellation(pilot, purpose, invalid_reason):
    client, engine, _, _ = pilot
    if purpose == "invite":
        registration_id, _, code = invite(pilot)
    else:
        registration_id, _, (code, _) = prepare_completion(pilot)
    endpoint = f"/parent-portal/register/{purpose}/verify"
    if invalid_reason == "used":
        assert client.post(endpoint, data={"token": code}).status_code == 200
    else:
        with Session(engine) as session:
            registration = session.get(ParentRegistrationRequest, registration_id)
            if invalid_reason == "cancelled":
                registration.status = "cancelled"
            elif purpose == "invite":
                registration.invitation_expires_at = utc_now() - timedelta(seconds=1)
            else:
                registration.completion_expires_at = utc_now() - timedelta(seconds=1)
            session.add(registration)
            session.commit()
    response = client.post(endpoint, data={"token": code})
    assert response.status_code == 400 and code not in response.text
    assert "施設へ再送をご依頼ください" in response.text


def test_expired_completion_cookie_shows_code_recovery(pilot):
    client, engine, _, _ = pilot
    _, _, (code, _) = prepare_completion(pilot)
    assert client.post("/parent-portal/register/complete/verify", data={"token": code}).status_code == 200
    raw_state = client.cookies.get(routes.REGISTRATION_COOKIE)
    with Session(engine) as session:
        state = session.get(ParentRegistrationSession, token_hash(raw_state))
        state.expires_at = utc_now() - timedelta(seconds=1)
        session.add(state)
        session.commit()
    response = client.get("/parent-portal/register/complete")
    assert "登録コードまたはメールのリンク" in response.text
    assert "確認用パスワード" not in response.text


def test_both_manual_exchange_forms_require_csrf(pilot, monkeypatch):
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "1")
    app = FastAPI(dependencies=[Depends(verify_csrf)])
    app.add_middleware(CsrfTokenMiddleware)
    app.include_router(routes.router)
    app.dependency_overrides.update(pilot[3].dependency_overrides)
    with TestClient(app, base_url="https://testserver") as client:
        for purpose in ("invite", "complete"):
            page = client.get(f"/parent-portal/register/{purpose}")
            csrf = client.cookies.get(CSRF_COOKIE_NAME)
            assert csrf in page.text
            endpoint = f"/parent-portal/register/{purpose}/verify"
            assert client.post(endpoint, data={"token": "a" * 43}).status_code == 403
            assert client.post(endpoint, data={"token": "a" * 43, "csrf_token": csrf}).status_code == 400
