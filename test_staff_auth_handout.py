"""One-time handout routes against an isolated, authenticated staff database."""
import base64
from datetime import timedelta
from unittest.mock import patch

import pytest
import qrcode
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

import test_local_staff_auth as staff_tests
from csrf import CsrfTokenMiddleware, verify_csrf
from local_auth import _token_hash, activate_staff_password, create_staff_credential
from models import CredentialActionToken, PasswordCredential, StaffCredentialProvisioningAudit, User
from routers.staff_auth import get_session, local_login_router, router
from staff_auth_handout import prepare_staff_code_handout
from time_utils import ensure_utc, format_jst_datetime, utc_now


@pytest.fixture
def staff(monkeypatch):
    case = staff_tests.LocalStaffAuthenticationTests()
    case.setUp()
    try:
        monkeypatch.setenv("HOIKUICT_FACILITY_NAME", "みほん保育園")
        case._activate()
        case._login()
        with Session(case.engine) as session:
            teacher = User(email="hana@example.invalid", display_name="見本 はな", staff_role="can_edit")
            session.add(teacher)
            session.commit()
            case.teacher_id = teacher.id
        yield case
    finally:
        case.tearDown()


def issue(staff, action, **kwargs):
    data = {"reason": "本人確認済み・管理者だけの発行理由", "login_id": "hana-login"}
    return staff.client.post(f"/staff/users/{staff.teacher_id}/authentication/{action}", data=data, **kwargs)


def configure_teacher(staff):
    with Session(staff.engine) as session:
        teacher = session.get(User, staff.teacher_id)
        _, code = create_staff_credential(session, user=teacher, login_id="hana-login")
        session.commit()
        activate_staff_password(session, activation_code=code, password=staff.PASSWORD, password_confirmation=staff.PASSWORD)


def snapshot(staff):
    with Session(staff.engine) as session:
        return [
            [row.model_dump() for row in session.exec(select(model)).all()]
            for model in (PasswordCredential, CredentialActionToken, StaffCredentialProvisioningAudit)
        ]


@pytest.mark.parametrize("action,destination", [("activate", "/staff/activate"), ("reset", "/staff/reset-password")])
def test_print_response_uses_exact_record_and_url_only_qr(staff, action, destination):
    if action == "reset":
        configure_teacher(staff)
    issued_at = utc_now() - timedelta(minutes=7)
    with patch("local_auth.utc_now", return_value=issued_at), patch("staff_auth_handout.qrcode.make", wraps=qrcode.make) as qr:
        response = issue(staff, action, headers={"Host": "forged.example.invalid", "X-Forwarded-Host": "forged.example.invalid"})
    assert response.status_code == 200
    code = staff._action_code_from(response)
    qr.assert_called_once()
    assert qr.call_args.args[0] == "https://staff.example.invalid" + destination
    assert "forged.example.invalid" not in response.text
    assert response.context["destination_url"] == "https://staff.example.invalid" + destination
    assert base64.b64decode(response.context["qr_data_uri"].split(",", 1)[1]).startswith(b"<svg")
    assert response.headers["cache-control"] == "private, no-store"
    assert "QR付き案内を印刷" in response.text
    assert "本人確認済み・管理者だけの発行理由" not in response.text
    assert "hana-login" in response.text and "みほん保育園" in response.text
    assert 'name="password"' not in response.text
    with Session(staff.engine) as session:
        token = session.get(CredentialActionToken, _token_hash(code))
        assert ensure_utc(token.created_at) == issued_at
        assert response.context["expires_at"] == token.expires_at
        assert response.context["issued_at"] == token.created_at
        assert format_jst_datetime(token.expires_at, "%Y年%m月%d日 %H:%M") in response.text
        assert 22 * 60_000 < response.context["remaining_ms"] <= 23 * 60_000
    before = snapshot(staff)
    # Opening the destination or returning to the management page must not issue a code.
    assert staff.client.get(destination).status_code == 200
    management = staff.client.get(f"/staff/users/{staff.teacher_id}/authentication")
    assert code not in management.text
    assert staff.client.get(f"/staff/users/{staff.teacher_id}/authentication/{action}").status_code == 405
    assert snapshot(staff) == before


@pytest.mark.parametrize("action", ["activate", "reset"])
@pytest.mark.parametrize("url", [None, "javascript:alert(1)", "https://user:password@example.invalid", "https://staff.example.invalid/path", "https://staff.example.invalid?code=SECRET", "https://staff.example.invalid:bad", "https://staff.example.invalid\n.evil.invalid"])
def test_bad_configuration_keeps_existing_codes_and_inputs(staff, monkeypatch, action, url):
    if action == "reset":
        configure_teacher(staff)
    assert issue(staff, action).status_code == 200
    before = snapshot(staff)
    monkeypatch.delenv("HOIKUICT_PARENT_REGISTRATION_BASE_URL", raising=False)
    if url is None:
        monkeypatch.delenv("HOIKUICT_STAFF_RECOVERY_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("HOIKUICT_STAFF_RECOVERY_BASE_URL", url)
    response = issue(staff, action)
    assert response.status_code == 400
    assert "施設URL" in response.text
    assert 'value="本人確認済み・管理者だけの発行理由"' in response.text
    assert "staff-handout-qr" not in response.text
    assert snapshot(staff) == before


def test_initial_input_error_preserves_login_and_reason(staff):
    response = staff.client.post(f"/staff/users/{staff.teacher_id}/authentication/activate", data={"login_id": "principal", "reason": "重複IDの確認"})
    assert response.status_code == 400
    assert 'value="principal"' in response.text
    assert 'value="重複IDの確認"' in response.text
    with Session(staff.engine) as session:
        assert session.exec(select(PasswordCredential).where(PasswordCredential.staff_user_id == staff.teacher_id)).first() is None


def test_existing_url_fallback_and_production_https(monkeypatch):
    monkeypatch.setenv("HOIKUICT_ENV", "production")
    monkeypatch.delenv("HOIKUICT_STAFF_RECOVERY_BASE_URL", raising=False)
    monkeypatch.setenv("HOIKUICT_PARENT_REGISTRATION_BASE_URL", "https://facility.example.invalid/")
    assert prepare_staff_code_handout("activate")["destination_url"] == "https://facility.example.invalid/staff/activate"
    monkeypatch.setenv("HOIKUICT_PARENT_REGISTRATION_BASE_URL", "http://facility.example.invalid")
    with pytest.raises(ValueError, match="施設URL"):
        prepare_staff_code_handout("activate")


@pytest.mark.parametrize("action", ["activate", "reset"])
def test_non_admin_cannot_issue_or_print_codes(staff, action):
    before = snapshot(staff)
    with Session(staff.engine) as session:
        actor = session.get(User, staff.user_id)
        actor.staff_role = "can_edit"
        session.add(actor)
        session.commit()
    response = issue(staff, action)
    assert response.status_code == 403
    assert "credential-action-code" not in response.text
    assert snapshot(staff) == before


@pytest.mark.parametrize("action", ["activate", "reset"])
def test_issuance_requires_csrf_and_still_accepts_valid_form(staff, monkeypatch, action):
    if action == "reset":
        configure_teacher(staff)
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "1")
    app = FastAPI(dependencies=[Depends(verify_csrf)])
    app.add_middleware(CsrfTokenMiddleware)
    app.include_router(router)
    app.include_router(local_login_router)
    app.dependency_overrides[get_session] = staff.app.dependency_overrides[get_session]
    with TestClient(app, cookies=dict(staff.client.cookies)) as client:
        form = client.get(f"/staff/users/{staff.teacher_id}/authentication")
        before = snapshot(staff)
        endpoint = f"/staff/users/{staff.teacher_id}/authentication/{action}"
        data = {"login_id": "hana-login", "reason": "本人確認済み"}
        assert client.post(endpoint, data=data).status_code == 403
        assert snapshot(staff) == before
        data["csrf_token"] = form.context["csrf_token"]
        assert client.post(endpoint, data=data).status_code == 200


def test_html_in_names_is_escaped(staff, monkeypatch):
    monkeypatch.setenv("HOIKUICT_FACILITY_NAME", '<img src=x onerror="alert(1)">')
    with Session(staff.engine) as session:
        teacher = session.get(User, staff.teacher_id)
        teacher.display_name = '<script>alert("name")</script>'
        session.add(teacher)
        session.commit()
    response = issue(staff, "activate")
    assert response.status_code == 200
    assert '<img src=x onerror=' not in response.text
    assert '<script>alert(' not in response.text
    assert '&lt;script&gt;' in response.text and '&lt;img' in response.text
