from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.requests import Request

import database
from auth import (LOCAL_STAFF_SESSION_COOKIE, Role, StaffUser,
                  configure_auth_backends_from_environment, get_current_staff_user, reset_auth_backends)
from csrf import CSRF_COOKIE_NAME, CsrfTokenMiddleware, verify_csrf
from local_auth import (activate_staff_password, authenticate_staff, create_staff_credential,
                        resolve_staff_session, revoke_session_token)
from models import (AuthSession, PasswordCredential, StaffSessionPolicy, StaffSessionPolicyAudit,
                    StaffSessionTimeout, User)
from routers.settings import router
from routers.staff_auth import local_login_router
from staff_session_settings import SessionPolicy, get_staff_session_policy, save_staff_session_policy
from time_utils import ensure_utc, utc_now

PASSWORD = "Correct horse battery staple 2026!"


@pytest.fixture
def setup(monkeypatch):
    for name, value in {
        "HOIKUICT_ENV": "test", "HOIKUICT_STAFF_AUTH_MODE": "local_password",
        "HOIKUICT_PARENT_AUTH_MODE": "local_password", "HOIKUICT_COOKIE_SECURE": "0",
        "HOIKUICT_ENABLE_MOCK_AUTH": "0", "HOIKUICT_CSRF_ENFORCE": "1",
        "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY": "s" * 40,
        "HOIKUICT_STAFF_SESSION_IDLE_MINUTES": "30", "HOIKUICT_STAFF_SESSION_ABSOLUTE_HOURS": "12",
    }.items():
        monkeypatch.setenv(name, value)
    configure_auth_backends_from_environment()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    with Session(engine) as session:
        actor = User(email="settings@example.com", display_name="設定担当", staff_role="admin")
        session.add(actor)
        session.commit()
        session.refresh(actor)
        principal = StaffUser(role=Role.ADMIN, name=actor.display_name, user_id=actor.id)
        app = FastAPI(dependencies=[Depends(verify_csrf)])
        app.add_middleware(CsrfTokenMiddleware)
        app.include_router(router)
        app.include_router(local_login_router)

        def db_session():
            yield session

        app.dependency_overrides[database.get_session] = db_session
        app.dependency_overrides[get_current_staff_user] = lambda: principal
        with TestClient(app) as client:
            yield app, client, session, actor, principal
    engine.dispose()
    reset_auth_backends()


def post(client, values=None, *, csrf=True):
    client.get("/settings/staff-sessions")
    data = values or {"idle_value": "12", "idle_unit": "hours", "absolute_hours": "12"}
    if csrf:
        data = {**data, "csrf_token": client.cookies[CSRF_COOKIE_NAME]}
    return client.post("/settings/staff-sessions", data=data, follow_redirects=False)


def login(session, actor):
    credential = session.exec(select(PasswordCredential)).first()
    if credential is None:
        _, code = create_staff_credential(session, user=actor, login_id="settings")
        session.commit()
        activate_staff_password(session, activation_code=code, password=PASSWORD, password_confirmation=PASSWORD)
    request = Request({"type": "http", "method": "POST", "path": "/staff/login",
                       "headers": [], "client": ("127.0.0.1", 1234)})
    return authenticate_staff(session, login_id="settings", password=PASSWORD, request=request)


@pytest.mark.parametrize("role,count", [(Role.ADMIN, 9), (Role.CAN_EDIT, 2), (Role.VIEW_ONLY, 2)])
def test_hub_respects_roles_and_opening_does_not_save(setup, role, count):
    app, client, session, actor, principal = setup
    principal.role = role
    response = client.get("/settings")
    assert response.status_code == 200
    assert response.text.count('class="settings-item ') == count
    assert 'href="/classrooms/"' in response.text
    assert 'href="/extended-care-fees/settings"' in response.text
    assert session.get(StaffSessionPolicy, 1) is None
    assert session.exec(select(StaffSessionPolicyAudit)).all() == []
    if role != Role.ADMIN:
        assert 'href="/settings/staff-sessions"' not in response.text


def test_disabled_parent_registration_link_hidden(setup, monkeypatch):
    monkeypatch.setenv("HOIKUICT_PARENT_AUTH_MODE", "disabled")
    response = setup[1].get("/settings")
    assert response.text.count('class="settings-item ') == 8
    assert 'href="/parent-accounts/registration-qr"' not in response.text


@pytest.mark.parametrize("role,active", [("can_edit", True), ("view_only", True), ("admin", False)])
def test_direct_settings_access_requires_live_admin(setup, role, active):
    app, client, session, actor, principal = setup
    actor.staff_role, actor.is_active = role, active
    session.add(actor)
    session.commit()
    assert client.get("/settings/staff-sessions").status_code == 403
    assert post(client).status_code == 403
    assert session.get(StaffSessionPolicy, 1) is None


def test_unauthenticated_hub_and_form_rejected(setup):
    app, client, session, actor, principal = setup
    app.dependency_overrides.pop(get_current_staff_user)
    assert client.get("/settings").status_code == 401
    assert client.get("/settings/staff-sessions").status_code == 401


def test_save_persists_policy_and_audit_but_not_on_get(setup):
    app, client, session, actor, principal = setup
    assert get_staff_session_policy(session) == SessionPolicy(30, 12)
    assert client.get("/settings/staff-sessions").status_code == 200
    assert session.get(StaffSessionPolicy, 1) is None
    assert post(client).status_code == 303
    session.expire_all()
    assert get_staff_session_policy(session) == SessionPolicy(720, 12)
    audit = session.exec(select(StaffSessionPolicyAudit)).one()
    assert (audit.old_idle_minutes, audit.old_absolute_hours) == (30, 12)
    assert (audit.new_idle_minutes, audit.new_absolute_hours) == (720, 12)
    assert audit.changed_by_user_id == actor.id
    response = client.get("/settings/staff-sessions?saved=true")
    assert "保存しました。次回ログインから適用されます。" in response.text
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("idle,unit,absolute", [
    ("", "minutes", "12"), ("4", "minutes", "12"), ("1441", "minutes", "24"),
    ("12.01", "hours", "24"), ("12", "days", "12"), ("12", "hours", "11"),
    ("30", "minutes", "0"), ("30", "minutes", "25"), ("30", "minutes", "abc"),
])
def test_invalid_values_preserved_without_writes(setup, idle, unit, absolute):
    response = post(setup[1], {"idle_value": idle, "idle_unit": unit, "absolute_hours": absolute})
    assert response.status_code == 400
    assert 'role="alert"' in response.text
    assert f'value="{idle}"' in response.text
    assert setup[2].get(StaffSessionPolicy, 1) is None
    assert setup[2].exec(select(StaffSessionPolicyAudit)).all() == []


def test_missing_csrf_cannot_change_setting(setup):
    assert post(setup[1], csrf=False).status_code == 403
    assert setup[2].get(StaffSessionPolicy, 1) is None


@pytest.mark.parametrize("value,unit,hours,expected", [
    ("0.5", "hours", "12", 30), ("720", "minutes", "12", 720),
    ("0.0833333333", "hours", "1", 5), ("24", "hours", "24", 1440),
])
def test_unit_conversion_and_limits(setup, value, unit, hours, expected):
    response = post(setup[1], {"idle_value": value, "idle_unit": unit, "absolute_hours": hours})
    assert response.status_code == 303
    assert get_staff_session_policy(setup[2]) == SessionPolicy(expected, int(hours))


def test_new_login_uses_policy_for_both_deadlines_and_cookie(setup):
    app, client, session, actor, principal = setup
    save_staff_session_policy(session, SessionPolicy(720, 12), actor)
    result = login(session, actor)
    record = session.exec(select(AuthSession)).one()
    assert record.idle_expires_at - record.created_at == timedelta(hours=12)
    assert record.absolute_expires_at - record.created_at == timedelta(hours=12)
    assert result.cookie_max_age == 43200
    save_staff_session_policy(session, SessionPolicy(60, 2), actor)
    # Cookie creation must use the result snapshot, even if the policy changed meanwhile.
    from auth import set_local_staff_session_cookie
    from fastapi import Response
    response = Response()
    set_local_staff_session_cookie(response, result.session_token, max_age=result.cookie_max_age)
    assert "Max-Age=43200" in response.headers.getlist("set-cookie")[0]
    client.get("/staff/login")
    response = client.post("/staff/login", data={"login_id": "settings", "password": PASSWORD,
                          "csrf_token": client.cookies[CSRF_COOKIE_NAME]}, follow_redirects=False)
    assert response.status_code == 303
    assert any("Max-Age=7200" in value and LOCAL_STAFF_SESSION_COOKIE in value
               for value in response.headers.get_list("set-cookie"))


@pytest.mark.parametrize("legacy", [False, True])
def test_settings_changes_do_not_change_existing_session_policy(setup, legacy):
    app, client, session, actor, principal = setup
    result = login(session, actor)
    record = session.exec(select(AuthSession)).one()
    if legacy:
        session.delete(session.get(StaffSessionTimeout, record.token_hash))
        session.commit()
    deadline = record.absolute_expires_at
    save_staff_session_policy(session, SessionPolicy(720, 24), actor)
    now = ensure_utc(record.created_at) + timedelta(minutes=10)
    with patch("local_auth.utc_now", return_value=now):
        assert resolve_staff_session(session, result.session_token) is not None
    session.refresh(record)
    assert ensure_utc(record.idle_expires_at) == now + timedelta(minutes=30)
    assert record.absolute_expires_at == deadline


@pytest.mark.parametrize("reason", ["idle", "absolute", "logout", "disabled", "credential_version"])
def test_longer_policy_cannot_restore_invalid_sessions(setup, reason):
    app, client, session, actor, principal = setup
    result = login(session, actor)
    record = session.exec(select(AuthSession)).one()
    now = utc_now()
    if reason == "idle":
        record.idle_expires_at = now - timedelta(seconds=1)
    elif reason == "absolute":
        record.absolute_expires_at = now - timedelta(seconds=1)
    elif reason == "logout":
        revoke_session_token(session, result.session_token)
    elif reason == "disabled":
        actor.is_active = False
        session.add(actor)
    else:
        credential = session.get(PasswordCredential, result.credential.id)
        credential.credential_version += 1
        session.add(credential)
    session.add(record)
    session.commit()
    save_staff_session_policy(session, SessionPolicy(1440, 24), actor)
    assert resolve_staff_session(session, result.session_token) is None


def test_minimum_idle_timeout_refreshes_during_active_use(setup):
    app, client, session, actor, principal = setup
    save_staff_session_policy(session, SessionPolicy(5, 1), actor)
    result = login(session, actor)
    record = session.exec(select(AuthSession)).one()
    start = ensure_utc(record.created_at)
    for minute in (3, 6, 9):
        with patch("local_auth.utc_now", return_value=start + timedelta(minutes=minute)):
            assert resolve_staff_session(session, result.session_token) is not None
    with patch("local_auth.utc_now", return_value=start + timedelta(hours=1)):
        assert resolve_staff_session(session, result.session_token) is None


def test_staff_form_token_lasts_whole_workday_parent_default_unchanged(setup):
    app, client, session, actor, principal = setup
    response = client.get("/settings")
    assert any("Max-Age=28800" in h for h in response.headers.get_list("set-cookie"))
    client.cookies.clear()
    client.cookies.set(LOCAL_STAFF_SESSION_COOKIE, "test-cookie")
    response = client.get("/settings")
    assert any("Max-Age=86400" in h for h in response.headers.get_list("set-cookie"))


def test_main_application_serves_settings_script(setup):
    from main import app

    # No lifespan: this checks real routing without starting workers or migrations.
    client = TestClient(app)
    try:
        response = client.get("/static/js/staff-session-settings.js")
    finally:
        client.close()
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "workday-preset" in response.text
