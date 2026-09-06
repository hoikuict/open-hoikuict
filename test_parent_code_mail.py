from datetime import timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, inspect, text
from sqlmodel import Session, create_engine, select

import database
import parent_auth
from auth import Role, StaffUser
from csrf import CSRF_COOKIE_NAME, CsrfTokenMiddleware, verify_csrf
from models import (
    CredentialActionToken, ParentAccount, ParentAccountStatus, ParentMailDelivery,
    PasswordCredential, User,
)
from test_guardian_account_sync import pilot as pilot_fixture, create_account
from time_utils import utc_now
import routers.parent_auth as routes


@pytest.fixture
def pilot(monkeypatch):
    yield from pilot_fixture.__wrapped__(monkeypatch)


def active_account(pilot):
    account_id = create_account(pilot)
    with Session(pilot[1]) as session:
        code = parent_auth.issue_parent_password_code(
            session, account=session.get(ParentAccount, account_id),
            actor_user=session.get(User, pilot[2]["actor"]), reason="本人確認済み",
            action="parent_activate",
        )
        state = parent_auth.exchange_parent_action_code(session, code, "parent_activate")
        parent_auth.complete_parent_action_password(
            session, raw_state=state, purpose="parent_activate",
            password="River!7892Long-Phrase", password_confirmation="River!7892Long-Phrase",
        )
    return account_id


def issue(pilot, account_id, action="activate"):
    response = pilot[0].post(f"/parent-accounts/{account_id}/authentication/{action}", data={"reason": "電話で本人確認済み"})
    assert response.status_code == 200, response.text
    code = response.context["action_code"]
    assert len(code) == 6 and "への送信を受け付けました" in response.text
    assert "no-store" in response.headers["cache-control"]
    return code


@pytest.mark.parametrize("action", ["activate", "reset"])
def test_issued_code_mail_has_both_urls_and_can_set_password_then_login(pilot, monkeypatch, action):
    client, engine, _, _ = pilot
    account_id = active_account(pilot) if action == "reset" else create_account(pilot)
    code = issue(pilot, account_id, action)
    with Session(engine) as session:
        delivery = session.exec(select(ParentMailDelivery)).one()
        credential = session.exec(select(PasswordCredential)).one()
        assert delivery.message_type == "parent_" + action and delivery.status == "pending"
        assert delivery.action_token_hash == parent_auth.token_hash(code)
        assert delivery.recipient == "parent@example.test"
        assert f"https://testserver/parent-portal/{action}" in delivery.body
        assert "https://testserver/parent-portal/login" in delivery.body
        assert f"ログインID：{credential.login_id}" in delivery.body
        assert f"認証コード：{code}" in delivery.body and "30分" in delivery.body
        assert "旧住所" not in delivery.body and "検証 葵" not in delivery.body
        sent = []
        monkeypatch.setenv("HOIKUICT_PARENT_MAIL_TRANSPORT", "smtp")
        monkeypatch.setattr(parent_auth, "_send_smtp", lambda mail: sent.append(mail.recipient))
        parent_auth.dispatch_pending_parent_mail(session)
        parent_auth.dispatch_pending_parent_mail(session)
        assert delivery.status == "sent" and sent == ["parent@example.test"]
    admin = client.get(f"/parent-accounts/{account_id}/authentication")
    assert "メールサーバー受付済み" in admin.text and code not in admin.text
    assert ("パスワード再設定コード" if action == "reset" else "初回設定・利用再開コード") in admin.text
    response = client.post(f"/parent-portal/{action}/verify", data={"activation_code" if action == "activate" else "reset_code": code})
    assert response.status_code == 200 and "新しいパスワード" in response.text
    password = "Maple!5938Long-Phrase"
    response = client.post(f"/parent-portal/{action}/complete", data={"password": password, "password_confirmation": password}, follow_redirects=False)
    assert response.status_code == 303
    response = client.post("/parent-portal/login", data={"login_id": "parent@example.test", "password": password}, follow_redirects=False)
    assert response.status_code == 303


@pytest.mark.parametrize("reason", ["expired", "revoked", "consumed", "email_changed", "inactive", "wrong_action", "missing_token"])
def test_outdated_code_mail_is_cancelled_before_smtp(pilot, monkeypatch, reason):
    account_id = create_account(pilot)
    code = issue(pilot, account_id)
    with Session(pilot[1]) as session:
        token = session.get(CredentialActionToken, parent_auth.token_hash(code))
        account = session.get(ParentAccount, account_id)
        delivery = session.exec(select(ParentMailDelivery)).one()
        if reason == "expired":
            token.expires_at = utc_now() - timedelta(seconds=1)
        elif reason == "revoked":
            token.revoked_at = utc_now()
        elif reason == "consumed":
            token.consumed_at = utc_now()
        elif reason == "email_changed":
            account.email = "new@example.test"
        elif reason == "inactive":
            account.status = ParentAccountStatus.inactive
        elif reason == "wrong_action":
            token.action = "parent_reset"
        else:
            delivery.action_token_hash = None
        session.add_all([token, account, delivery])
        session.commit()
        sent = []
        monkeypatch.setenv("HOIKUICT_PARENT_MAIL_TRANSPORT", "smtp")
        monkeypatch.setattr(parent_auth, "_send_smtp", lambda mail: sent.append(mail.id))
        parent_auth.dispatch_pending_parent_mail(session)
        assert sent == [] and delivery.status == "cancelled"
        assert delivery.next_retry_at is None and delivery.sent_at is None


def test_reissue_cancels_old_mail_and_double_click_preserves_current_code(pilot):
    client, engine, _, _ = pilot
    account_id = create_account(pilot)
    first_code = issue(pilot, account_id)
    response = client.post(f"/parent-accounts/{account_id}/authentication/activate", data={"reason": "同じ操作"})
    assert response.status_code == 400 and "60秒" in response.text
    with Session(engine) as session:
        token = session.get(CredentialActionToken, parent_auth.token_hash(first_code))
        assert token.revoked_at is None
        assert len(session.exec(select(CredentialActionToken)).all()) == 1
        delivery = session.exec(select(ParentMailDelivery)).one()
        delivery.created_at = utc_now() - timedelta(minutes=2)
        session.add(delivery)
        session.commit()
    new_code = issue(pilot, account_id)
    assert new_code != first_code
    with Session(engine) as session:
        assert session.get(CredentialActionToken, parent_auth.token_hash(first_code)).revoked_at
        deliveries = session.exec(select(ParentMailDelivery)).all()
        assert sorted(item.status for item in deliveries) == ["cancelled", "pending"]
        parent_auth.dispatch_pending_parent_mail(session)
        assert sorted(item.status for item in deliveries) == ["cancelled", "captured"]


@pytest.mark.parametrize("expire_before_retry", [False, True])
def test_smtp_failure_retries_same_code_but_stops_at_expiry(pilot, monkeypatch, expire_before_retry):
    account_id = create_account(pilot)
    code = issue(pilot, account_id)
    calls = []
    def smtp(mail):
        calls.append(mail.body)
        if len(calls) == 1:
            raise RuntimeError("SMTP failure with a sensitive response")
    monkeypatch.setenv("HOIKUICT_PARENT_MAIL_TRANSPORT", "smtp")
    monkeypatch.setattr(parent_auth, "_send_smtp", smtp)
    with Session(pilot[1]) as session:
        parent_auth.dispatch_pending_parent_mail(session)
        delivery = session.exec(select(ParentMailDelivery)).one()
        assert delivery.status == "pending" and delivery.failure_code == "RuntimeError"
        delivery.next_retry_at = utc_now() - timedelta(seconds=1)
        session.add(delivery)
        if expire_before_retry:
            token = session.get(CredentialActionToken, parent_auth.token_hash(code))
            token.expires_at = utc_now() - timedelta(seconds=1)
            session.add(token)
        session.commit()
        parent_auth.dispatch_pending_parent_mail(session)
        assert delivery.status == ("cancelled" if expire_before_retry else "sent")
        assert len(calls) == (1 if expire_before_retry else 2)
        assert all(f"認証コード：{code}" in body for body in calls)


def test_code_issuance_requires_admin_and_csrf_without_queuing_mail(pilot, monkeypatch):
    _, engine, _, existing_app = pilot
    account_id = create_account(pilot)
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "1")
    app = FastAPI(dependencies=[Depends(verify_csrf)])
    app.add_middleware(CsrfTokenMiddleware)
    app.include_router(routes.router)
    app.dependency_overrides.update(existing_app.dependency_overrides)
    with TestClient(app, base_url="https://testserver") as client:
        client.get(f"/parent-accounts/{account_id}/authentication")
        endpoint = f"/parent-accounts/{account_id}/authentication/activate"
        assert client.post(endpoint, data={"reason": "確認済み"}).status_code == 403
        app.dependency_overrides[routes.get_current_staff_user] = lambda: StaffUser(role=Role.CAN_EDIT, name="編集担当")
        assert client.post(endpoint, data={"reason": "確認済み", "csrf_token": client.cookies.get(CSRF_COOKIE_NAME)}).status_code == 403
    with Session(engine) as session:
        assert not session.exec(select(ParentMailDelivery)).all()
        assert not session.exec(select(CredentialActionToken)).all()


def test_existing_mail_schema_migrates_idempotently_without_changing_messages(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    event.listen(engine, "connect", database._set_sqlite_connection_pragmas)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE credential_action_tokens (token_hash VARCHAR(64) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE parent_mail_deliveries (id TEXT PRIMARY KEY, recipient TEXT, body TEXT, status TEXT)"))
            connection.execute(text("INSERT INTO parent_mail_deliveries VALUES ('legacy', 'parent@example.test', 'Original invitation body', 'sent')"))
        monkeypatch.setattr(database, "engine", engine)
        database._migrate_parent_mail_delivery_columns()
        database._migrate_parent_mail_delivery_columns()
        with engine.connect() as connection:
            row = connection.execute(text("SELECT recipient, body, status, action_token_hash FROM parent_mail_deliveries")).one()
            assert tuple(row) == ("parent@example.test", "Original invitation body", "sent", None)
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
        assert any(key["referred_table"] == "credential_action_tokens" for key in inspect(engine).get_foreign_keys("parent_mail_deliveries"))
    finally:
        engine.dispose()
