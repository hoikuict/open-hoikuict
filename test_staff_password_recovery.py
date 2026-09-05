import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

import database
import staff_recovery
from auth import (
    configure_auth_backends_from_environment,
    get_current_staff_user,
    reset_auth_backends,
)
from auth_mail import send_auth_mail
from csrf import CsrfTokenMiddleware, verify_csrf
from local_auth import (
    AuthenticationFailed,
    authenticate_staff,
    create_staff_credential,
    hash_password,
    issue_staff_password_reset,
    resolve_staff_session,
    verify_password,
)
from models import (
    CredentialActionToken,
    LoginThrottle,
    PasswordCredential,
    StaffMailDelivery,
    StaffPasswordRecovery,
    User,
)
from routers.staff_auth import local_login_router
from security_config import staff_recovery_base_url
from time_utils import utc_now

OLD_PASSWORD = "Cedar!9274Blue"
NEW_PASSWORD = "Maple!6842Green"
EMAIL = "principal@example.com"


@pytest.fixture
def recovery(tmp_path, monkeypatch, request):
    for key, value in {
        "HOIKUICT_ENV": "test", "HOIKUICT_ENABLE_MOCK_AUTH": "0",
        "HOIKUICT_STAFF_AUTH_MODE": "local_password", "HOIKUICT_COOKIE_SECURE": "0",
        "HOIKUICT_CSRF_ENFORCE": "1", "HOIKUICT_PARENT_MAIL_TRANSPORT": "capture",
        "HOIKUICT_PARENT_REGISTRATION_BASE_URL": "http://testserver",
        "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY": "t" * 40,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("HOIKUICT_STAFF_RECOVERY_BASE_URL", raising=False)
    if "concurrent" in request.node.name:
        engine = create_engine(f"sqlite:///{tmp_path / 'recovery.db'}", connect_args={"check_same_thread": False})
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            connection.exec_driver_sql("PRAGMA synchronous=NORMAL")
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    configure_auth_backends_from_environment()
    with Session(engine) as session:
        user = User(email=EMAIL, display_name="園長", staff_role="admin", staff_sort_order=10)
        session.add(user)
        session.flush()
        credential, _code = create_staff_credential(session, user=user, login_id="principal")
        credential.password_hash = hash_password(OLD_PASSWORD)
        session.add(credential)
        session.commit()
        user_id, credential_id = user.id, credential.id
    app = FastAPI(dependencies=[Depends(verify_csrf)])
    app.add_middleware(CsrfTokenMiddleware)
    app.include_router(local_login_router)

    @app.get("/protected")
    def protected(user=Depends(get_current_staff_user)):
        return {"name": user.name}

    with TestClient(app) as client:
        client.get("/staff/forgot-password")
        yield SimpleNamespace(engine=engine, client=client, user_id=user_id, credential_id=credential_id)
    reset_auth_backends()
    engine.dispose()


def post(recovery, path, **data):
    if not recovery.client.cookies.get("hoikuict_csrf"):
        recovery.client.get("/staff/forgot-password")
    return recovery.client.post(path, data={**data, "csrf_token": recovery.client.cookies.get("hoikuict_csrf")},
                                follow_redirects=False)


def request_link(recovery):
    assert post(recovery, "/staff/forgot-password", email=EMAIL).status_code == 303
    with Session(recovery.engine) as session:
        delivery = session.exec(select(StaffMailDelivery).where(
            StaffMailDelivery.message_type == "password_recovery"
        ).order_by(StaffMailDelivery.created_at.desc())).first()
        return re.search(r"/staff/recover-password#([A-Za-z0-9_-]{43})", delivery.body).group(1)


def complete(recovery, token, **overrides):
    return post(recovery, "/staff/recover-password", **{
        "token": token, "password": NEW_PASSWORD, "password_confirmation": NEW_PASSWORD, **overrides,
    })


def test_request_and_complete_require_csrf(recovery):
    assert recovery.client.post("/staff/forgot-password", data={"email": EMAIL}).status_code == 403
    token = request_link(recovery)
    assert recovery.client.post("/staff/recover-password", data={"token": token}).status_code == 403


@pytest.mark.parametrize("ineligible", ["unknown", "ordinary_staff", "inactive", "disabled", "unconfigured", "ambiguous"])
def test_request_never_reveals_or_recovers_ineligible_accounts(recovery, ineligible):
    with Session(recovery.engine) as session:
        user = session.get(User, recovery.user_id)
        credential = session.get(PasswordCredential, recovery.credential_id)
        if ineligible == "ordinary_staff":
            user.staff_role = "can_edit"
        elif ineligible == "inactive":
            user.is_active = False
        elif ineligible == "disabled":
            credential.disabled_at = utc_now()
        elif ineligible == "unconfigured":
            credential.password_hash = None
        elif ineligible == "ambiguous":
            session.add(User(email=EMAIL.upper(), display_name="別職員", staff_role="admin"))
        session.add(user)
        session.add(credential)
        session.commit()
    response = post(recovery, "/staff/forgot-password", email="unknown@example.com" if ineligible == "unknown" else EMAIL)
    assert response.status_code == 303
    assert response.headers["location"] == "/staff/forgot-password?requested=1"
    page = recovery.client.get(response.headers["location"])
    assert staff_recovery.REQUEST_ACCEPTED in page.text
    with Session(recovery.engine) as session:
        assert not session.exec(select(StaffPasswordRecovery)).all()
        assert not session.exec(select(StaffMailDelivery)).all()


def test_full_http_recovery_revokes_sessions_codes_and_other_links(recovery, monkeypatch):
    with Session(recovery.engine) as session:
        old_session = authenticate_staff(session, login_id="principal", password=OLD_PASSWORD).session_token
        user = session.get(User, recovery.user_id)
        issue_staff_password_reset(session, user=user, actor_user=user, reason="旧コード")
    token = request_link(recovery)
    second_time = utc_now() + timedelta(seconds=61)
    with patch.object(staff_recovery, "utc_now", return_value=second_time):
        second_token = request_link(recovery)
    assert token != second_token
    for _ in range(2):
        page = recovery.client.get("/staff/recover-password")
        assert page.status_code == 200
        assert page.headers["referrer-policy"] == "no-referrer"
        assert "no-store" in page.headers["cache-control"]
    with Session(recovery.engine) as session:
        assert resolve_staff_session(session, old_session) is not None
        assert all(row.consumed_at is None for row in session.exec(select(StaffPasswordRecovery)).all())
    response = complete(recovery, token)
    assert response.status_code == 303
    assert response.headers["location"] == "/staff/login?password_reset=1"
    with Session(recovery.engine) as session:
        assert resolve_staff_session(session, old_session) is None
        credential = session.get(PasswordCredential, recovery.credential_id)
        assert not verify_password(credential.password_hash, OLD_PASSWORD)
        assert verify_password(credential.password_hash, NEW_PASSWORD)
        assert all(item.revoked_at for item in session.exec(select(CredentialActionToken)).all())
        assert all(not row.body for row in session.exec(select(StaffMailDelivery)).all() if row.message_type == "password_recovery")
        notice = session.exec(select(StaffMailDelivery).where(StaffMailDelivery.message_type == "password_reset_completed")).one()
        assert NEW_PASSWORD not in notice.body and "principal" in notice.body
    assert complete(recovery, token).status_code == 400
    assert complete(recovery, second_token).status_code == 400
    recovery.client.get("/staff/login")
    assert post(recovery, "/staff/login", login_id="principal", password=NEW_PASSWORD).status_code == 303
    assert recovery.client.get("/protected").status_code == 200


@pytest.mark.parametrize("password,confirmation", [("short", "short"), (NEW_PASSWORD, "different")])
def test_password_error_preserves_link_for_retry(recovery, password, confirmation):
    token = request_link(recovery)
    assert complete(recovery, token, password=password, password_confirmation=confirmation).status_code == 400
    assert complete(recovery, token).status_code == 303


@pytest.mark.parametrize("change", ["email", "role", "inactive", "disabled", "version", "expired", "sort_order"])
def test_stale_link_cannot_change_password_or_reenable_account(recovery, change):
    token = request_link(recovery)
    with Session(recovery.engine) as session:
        user = session.get(User, recovery.user_id)
        credential = session.get(PasswordCredential, recovery.credential_id)
        if change == "email": user.email = "changed@example.com"
        if change == "role": user.staff_role = "can_edit"
        if change == "inactive": user.is_active = False
        if change == "disabled": credential.disabled_at = utc_now()
        if change == "version": credential.credential_version += 1
        if change == "sort_order": user.staff_sort_order = 200
        if change == "expired":
            record = session.exec(select(StaffPasswordRecovery)).one()
            record.expires_at = utc_now() - timedelta(seconds=1)
            session.add(record)
        session.add(user)
        session.add(credential)
        session.commit()
    assert complete(recovery, token).status_code == 400
    with Session(recovery.engine) as session:
        assert verify_password(session.get(PasswordCredential, recovery.credential_id).password_hash, OLD_PASSWORD)
        staff_recovery.dispatch_pending_staff_mail(session)
        assert session.exec(select(StaffMailDelivery)).one().body == ""


def test_request_limits_do_not_lock_password_login(recovery):
    request_link(recovery)
    for _ in range(3):
        assert post(recovery, "/staff/forgot-password", email=EMAIL.upper()).status_code == 303
    with Session(recovery.engine) as session:
        assert len(session.exec(select(StaffMailDelivery)).all()) == 1
        assert authenticate_staff(session, login_id="principal", password=OLD_PASSWORD)
        assert all(EMAIL not in row.bucket_hash for row in session.exec(select(LoginThrottle)).all())
    start = utc_now()
    for minute in range(1, 7):
        with patch.object(staff_recovery, "utc_now", return_value=start + timedelta(minutes=minute)):
            post(recovery, "/staff/forgot-password", email=EMAIL)
    with Session(recovery.engine) as session:
        assert len(session.exec(select(StaffMailDelivery)).all()) == 5


def test_network_limit_also_counts_unknown_addresses(recovery):
    for number in range(20):
        post(recovery, "/staff/forgot-password", email=f"unknown{number}@example.com")
    post(recovery, "/staff/forgot-password", email=EMAIL)
    with Session(recovery.engine) as session:
        assert not session.exec(select(StaffMailDelivery)).all()


def test_smtp_delivery_retry_and_token_body_cleanup(recovery, monkeypatch):
    token = request_link(recovery)
    monkeypatch.setenv("HOIKUICT_PARENT_MAIL_TRANSPORT", "smtp")
    with Session(recovery.engine) as session:
        with patch.object(staff_recovery, "send_auth_mail", side_effect=RuntimeError("secret SMTP response")):
            staff_recovery.dispatch_pending_staff_mail(session)
        delivery = session.exec(select(StaffMailDelivery)).one()
        assert delivery.status == "pending" and delivery.attempt_count == 1
        assert delivery.failure_code == "RuntimeError"
        delivery.next_retry_at = utc_now() - timedelta(seconds=1)
        session.add(delivery)
        session.commit()
        with patch.object(staff_recovery, "send_auth_mail") as sender:
            staff_recovery.dispatch_pending_staff_mail(session)
        assert token in sender.call_args.kwargs["body"]
        session.expire_all()
        delivery = session.exec(select(StaffMailDelivery)).one()
        assert delivery.status == "sent" and delivery.body == "" and delivery.attempt_count == 2
        with patch.object(staff_recovery, "send_auth_mail") as sender:
            staff_recovery.dispatch_pending_staff_mail(session)
            sender.assert_not_called()


def test_capture_is_local_and_expired_mail_is_erased(recovery):
    token = request_link(recovery)
    with Session(recovery.engine) as session:
        with patch.object(staff_recovery, "send_auth_mail") as sender:
            staff_recovery.dispatch_pending_staff_mail(session)
            sender.assert_not_called()
        delivery = session.exec(select(StaffMailDelivery)).one()
        assert delivery.status == "captured" and token in delivery.body
        delivery.expires_at = utc_now() - timedelta(seconds=1)
        session.add(delivery)
        session.commit()
        staff_recovery.dispatch_pending_staff_mail(session)
        session.expire_all()
        assert session.exec(select(StaffMailDelivery)).one().body == ""


@pytest.mark.parametrize("different_links", [False, True])
def test_concurrent_completion_changes_password_only_once(recovery, different_links):
    first = request_link(recovery)
    second = first
    if different_links:
        with patch.object(staff_recovery, "utc_now", return_value=utc_now() + timedelta(seconds=61)):
            second = request_link(recovery)
    barrier = Barrier(2)
    precomputed = hash_password(NEW_PASSWORD)

    def delayed_hash(_password):
        barrier.wait(timeout=10)
        return precomputed

    def attempt(token):
        with Session(recovery.engine) as session:
            try:
                staff_recovery.complete_admin_password_recovery(
                    session, token=token, password=NEW_PASSWORD, password_confirmation=NEW_PASSWORD,
                )
                return "completed"
            except AuthenticationFailed:
                return "invalid"

    with patch.object(staff_recovery, "hash_password", side_effect=delayed_hash):
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(attempt, [first, second])) == ["completed", "invalid"]


@pytest.mark.parametrize("url", ["http://example.com", "https://example.com/extra", "https://example.com#token", "https://user:pass@example.com", "https://example.com:bad"])
def test_production_recovery_origin_rejects_unsafe_configuration(monkeypatch, url):
    monkeypatch.setenv("HOIKUICT_ENV", "production")
    monkeypatch.setenv("HOIKUICT_STAFF_RECOVERY_BASE_URL", url)
    with pytest.raises(RuntimeError):
        staff_recovery_base_url()


def test_recovery_uses_configured_origin_not_request_host(recovery, monkeypatch):
    monkeypatch.setenv("HOIKUICT_STAFF_RECOVERY_BASE_URL", "https://staff.example.com")
    request_link(recovery)
    with Session(recovery.engine) as session:
        assert "https://staff.example.com/staff/recover-password#" in session.exec(select(StaffMailDelivery)).one().body


def test_shared_smtp_transport_uses_tls_and_configured_sender(monkeypatch):
    for key, value in {"HOIKUICT_SMTP_HOST": "smtp.example.invalid", "HOIKUICT_SMTP_PORT": "587",
                       "HOIKUICT_SMTP_STARTTLS": "1", "HOIKUICT_SMTP_USERNAME": "sender",
                       "HOIKUICT_SMTP_PASSWORD": "synthetic-only", "HOIKUICT_PARENT_MAIL_FROM": "noreply@example.com"}.items():
        monkeypatch.setenv(key, value)
    with patch("auth_mail.smtplib.SMTP") as smtp:
        send_auth_mail(recipient=EMAIL, subject="再設定", body="検証用")
    connection = smtp.return_value.__enter__.return_value
    connection.starttls.assert_called_once()
    connection.login.assert_called_once_with("sender", "synthetic-only")
    message = connection.send_message.call_args.args[0]
    assert message["To"] == EMAIL and message["From"] == "noreply@example.com"
