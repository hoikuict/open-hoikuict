"""Lifecycle regressions using synthetic accounts and an isolated in-memory DB."""
import csv
import io
from datetime import timedelta

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from auth import Role, StaffUser
from csrf import CSRF_COOKIE_NAME, CsrfTokenMiddleware, verify_csrf
from data_transfer_service import DATASETS, commit_import, preview_import
from local_auth import AuthenticationFailed
from models import (
    Child, ChildStatus, CredentialActionToken, ParentAccount, ParentAccountStatus,
    ParentChildLink, ParentCredentialProvisioningAudit, ParentMailDelivery,
    ParentPushSubscription, PasswordCredential, User,
)
import parent_auth
from parent_account_lifecycle import change_parent_lifecycle, parent_lifecycle_state, StaleParentLifecycle
from test_guardian_account_sync import pilot as pilot_fixture, account_form, create_account
from test_parent_code_mail import active_account
from time_utils import utc_now
import routers.parent_auth as routes


@pytest.fixture
def pilot(monkeypatch):
    yield from pilot_fixture.__wrapped__(monkeypatch)


def page(pilot, account_id):
    response = pilot[0].get(f"/parent-accounts/{account_id}/authentication")
    assert response.status_code == 200, response.text
    return response


def transition(pilot, account_id, action, **overrides):
    form = dict(action=action, reason="本人確認済み・架空の操作", confirmed="yes",
                revision=page(pilot, account_id).context["lifecycle"]["revision"])
    form.update(overrides)
    return pilot[0].post(f"/parent-accounts/{account_id}/authentication/lifecycle", data=form, follow_redirects=False)


def csv_bytes(account_id, status):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=DATASETS["parent_accounts"].headers)
    writer.writeheader()
    writer.writerow({"ID": account_id, "状態": status, "表示名": "CSVの更新名"})
    return buffer.getvalue().encode("utf-8-sig")


def test_confirmation_back_and_empty_reason_do_not_mutate(pilot):
    account_id = active_account(pilot)
    revision = page(pilot, account_id).context["lifecycle"]["revision"]
    assert transition(pilot, account_id, "stop", reason="  ").status_code == 400
    confirmation = transition(pilot, account_id, "stop", confirmed="")
    assert confirmation.status_code == 200 and "修正に戻る" in confirmation.text
    assert confirmation.context["reason"] == "本人確認済み・架空の操作"
    back = transition(pilot, account_id, "stop", confirmed="back")
    assert back.context["lifecycle_values"]["reason"] == confirmation.context["reason"]
    assert page(pilot, account_id).context["lifecycle"]["revision"] == revision


def test_family_can_resume_after_graduation_and_explicitly_add_new_sibling(pilot):
    account_id = active_account(pilot)
    with Session(pilot[1]) as session:
        graduate = session.get(Child, pilot[2]["child"])
        graduate.status = ChildStatus.graduated
        session.add(graduate)
        session.commit()
    assert transition(pilot, account_id, "stop").status_code == 303
    form = account_form(pilot, account_id)
    form["child_ids"] = [pilot[2]["child"], pilot[2]["sibling"]]
    assert pilot[0].post(f"/parent-accounts/{account_id}/edit", data=form, follow_redirects=False).status_code == 303
    assert page(pilot, account_id).context["lifecycle"]["code"] == "stopped"
    assert transition(pilot, account_id, "resume").status_code == 303
    with Session(pilot[1]) as session:
        assert {link.child_id for link in session.exec(select(ParentChildLink)).all()} == set(form["child_ids"])
        assert session.get(Child, pilot[2]["child"]).status == ChildStatus.graduated
        assert parent_auth.authenticate_parent(session, login_id="parent@example.test", password="River!7892Long-Phrase").account.id == account_id


@pytest.mark.parametrize("method", ["invite", "activate"])
def test_stopped_unregistered_account_restarts_initial_setup_in_auth_management(pilot, method):
    account_id = create_account(pilot)
    assert transition(pilot, account_id, "stop").status_code == 303
    assert transition(pilot, account_id, "resume").status_code == 400
    response = pilot[0].post(f"/parent-accounts/{account_id}/authentication/{method}", data={"reason": "初回登録を再案内"})
    assert response.status_code == 200, response.text
    assert page(pilot, account_id).context["lifecycle"]["code"] == ("initial_pending" if method == "activate" else "unregistered")
    with Session(pilot[1]) as session:
        assert session.exec(select(PasswordCredential)).one().password_hash is None
        assert session.get(ParentAccount, account_id).status == ParentAccountStatus.active


def test_old_activation_and_disable_endpoints_cannot_bypass_lifecycle_confirmation(pilot):
    account_id = active_account(pilot)
    endpoint = f"/parent-accounts/{account_id}/authentication"
    assert pilot[0].post(endpoint + "/disable", data={"reason": "古い画面"}).status_code == 409
    assert transition(pilot, account_id, "stop").status_code == 303
    assert pilot[0].post(endpoint + "/activate", data={"reason": "古い画面"}).status_code == 400
    assert page(pilot, account_id).context["lifecycle"]["code"] == "stopped"


def test_stopped_initial_enrollment_can_resend_without_skipping_intake(pilot):
    from test_parent_enrollment import invite, open_form
    _, account_id, _ = invite(pilot)
    assert transition(pilot, account_id, "stop").status_code == 303
    assert not page(pilot, account_id).context["invitation_issues"]
    with Session(pilot[1]) as session:
        mail = session.exec(select(ParentMailDelivery)).one()
        mail.created_at = utc_now() - timedelta(minutes=2)
        session.add(mail)
        session.commit()
    response = pilot[0].post(f"/parent-accounts/{account_id}/authentication/invite", data={
        "reason": "初回入力を再開", "enrollment_child_name": "入園 はな",
    })
    assert response.status_code == 200, response.text
    with Session(pilot[1]) as session:
        mail = session.exec(select(ParentMailDelivery).order_by(ParentMailDelivery.created_at.desc())).first()
        code = mail.body.split("#")[1].split()[0]
        assert session.exec(select(PasswordCredential)).one().password_hash is None
    open_form(pilot[0], code)


def test_stop_resume_keeps_password_links_and_revokes_every_old_artifact(pilot):
    account_id = active_account(pilot)
    with Session(pilot[1]) as session:
        account = session.get(ParentAccount, account_id)
        login = parent_auth.authenticate_parent(session, login_id=account.email, password="River!7892Long-Phrase")
        old_session = login.session_token
        password_hash = login.credential.password_hash
        code = parent_auth.issue_parent_password_code(session, account=account,
            actor_user=session.get(User, pilot[2]["actor"]), reason="再設定", send_email=True)
        state = parent_auth.exchange_parent_action_code(session, code, "parent_reset")
        session.add(ParentPushSubscription(parent_account_id=account_id, endpoint="https://push.example.test/device",
            endpoint_hash="z" * 64, p256dh_key="synthetic", auth_key="synthetic", environment="test"))
        links_before = [(l.child_id, l.relationship_label, l.is_primary_contact) for l in account.child_links]
        session.commit()
    assert transition(pilot, account_id, "stop").status_code == 303
    with Session(pilot[1]) as session:
        assert session.get(ParentAccount, account_id).status == ParentAccountStatus.inactive
        assert parent_auth.resolve_parent_session(session, old_session) is None
        assert session.exec(select(ParentPushSubscription)).one().status.value == "revoked"
        assert session.exec(select(ParentMailDelivery)).one().status == "cancelled"
        with pytest.raises(AuthenticationFailed):
            parent_auth.authenticate_parent(session, login_id="parent@example.test", password="River!7892Long-Phrase")
    assert transition(pilot, account_id, "resume").status_code == 303
    with Session(pilot[1]) as session:
        credential = session.exec(select(PasswordCredential)).one()
        assert credential.password_hash == password_hash and credential.disabled_at is None
        assert parent_auth.resolve_parent_session(session, old_session) is None
        assert session.exec(select(ParentPushSubscription)).one().status.value == "revoked"
        assert len(session.exec(select(ParentMailDelivery)).all()) == 1  # no normal-resume mail
        assert links_before == [(l.child_id, l.relationship_label, l.is_primary_contact) for l in session.exec(select(ParentChildLink)).all()]
        assert parent_auth.authenticate_parent(session, login_id="parent@example.test", password="River!7892Long-Phrase").account.id == account_id
        with pytest.raises(AuthenticationFailed):
            parent_auth.complete_parent_action_password(session, raw_state=state, purpose="parent_reset",
                password="Another!Password29", password_confirmation="Another!Password29")


def test_legacy_disagreement_uses_one_status_and_requires_explicit_resume(pilot):
    account_id = active_account(pilot)
    with Session(pilot[1]) as session:
        credential = session.exec(select(PasswordCredential)).one()
        credential.disabled_at = utc_now()
        session.add(credential)
        session.commit()
    assert page(pilot, account_id).context["lifecycle"]["label"] == "停止中"
    edit = pilot[0].get(f"/parent-accounts/{account_id}/edit")
    assert edit.context["lifecycle"]["label"] == "停止中" and 'name="status"' not in edit.text
    listing = pilot[0].get("/parent-accounts/")
    assert listing.context["lifecycle_states"][account_id]["label"] == "停止中"
    detail = pilot[0].get(f"/children/{pilot[2]['child']}")
    assert detail.context["parent_lifecycle_states"][account_id]["label"] == "停止中"
    with Session(pilot[1]) as session:
        assert session.exec(select(PasswordCredential)).one().disabled_at is not None
    assert transition(pilot, account_id, "resume").status_code == 303


def test_profile_and_csv_cannot_change_existing_lifecycle(pilot):
    account_id = active_account(pilot)
    form = account_form(pilot, account_id)
    form["status"] = "inactive"
    assert pilot[0].post(f"/parent-accounts/{account_id}/edit", data=form).status_code == 400
    with Session(pilot[1]) as session:
        for importer in (preview_import, commit_import):
            kwargs = {"actor_name": "検証担当"} if importer == commit_import else {}
            result = importer(session, "parent_accounts", "fixture.csv", csv_bytes(account_id, "inactive"), **kwargs)
            assert result.errors and "認証管理" in result.errors[0].message
        assert session.get(ParentAccount, account_id).status == ParentAccountStatus.active
    assert transition(pilot, account_id, "stop").status_code == 303
    form.pop("status")
    form["phone"] = "000-2222-3333"
    assert pilot[0].post(f"/parent-accounts/{account_id}/edit", data=form, follow_redirects=False).status_code == 303
    with Session(pilot[1]) as session:
        account = session.get(ParentAccount, account_id)
        assert account.phone == form["phone"] and account.status == ParentAccountStatus.inactive
        result = commit_import(session, "parent_accounts", "fixture.csv", csv_bytes(account_id, "active"), actor_name="検証担当")
        assert result.errors
        result = commit_import(session, "parent_accounts", "fixture.csv", csv_bytes(account_id, ""), actor_name="検証担当")
        assert not result.errors
        assert session.get(ParentAccount, account_id).status == ParentAccountStatus.inactive


@pytest.mark.parametrize("blocked", ["unregistered", "removed", "requires_reset"])
def test_normal_resume_cannot_bypass_required_setup(pilot, blocked):
    account_id = create_account(pilot) if blocked == "unregistered" else active_account(pilot)
    assert transition(pilot, account_id, "stop").status_code == 303
    with Session(pilot[1]) as session:
        if blocked == "removed":
            account = session.get(ParentAccount, account_id)
            account.email = "removed:fixture"
            session.add(account)
        if blocked == "requires_reset":
            credential = session.exec(select(PasswordCredential)).one()
            credential.must_change_password = True
            session.add(credential)
        session.commit()
    assert transition(pilot, account_id, "resume").status_code == 400


@pytest.mark.parametrize("finish", ["complete", "cancel", "expire"])
def test_reset_resume_waits_for_password_and_cancel_or_expiry_blocks_code(pilot, finish):
    account_id = active_account(pilot)
    assert transition(pilot, account_id, "stop").status_code == 303
    assert transition(pilot, account_id, "reset_resume").status_code == 303
    assert page(pilot, account_id).context["lifecycle"]["code"] == "resume_pending"
    assert transition(pilot, account_id, "resume").status_code == 400
    with Session(pilot[1]) as session:
        assert session.get(ParentAccount, account_id).status == ParentAccountStatus.inactive
        with pytest.raises(AuthenticationFailed):
            parent_auth.authenticate_parent(session, login_id="parent@example.test", password="River!7892Long-Phrase")
        mail = session.exec(select(ParentMailDelivery)).one()
        code = mail.body.split("認証コード：")[1].splitlines()[0]
        parent_auth.dispatch_pending_parent_mail(session)
        assert mail.status == "captured" and "/parent-portal/resume" in mail.body
        if finish == "expire":
            token = session.get(CredentialActionToken, mail.action_token_hash)
            token.expires_at = utc_now() - timedelta(seconds=1)
            session.add(token)
            session.commit()
    verification = pilot[0].post("/parent-portal/resume/verify", data={"reset_code": code})
    if finish == "expire":
        assert verification.status_code == 400
        assert page(pilot, account_id).context["lifecycle"]["code"] == "stopped"
        return
    assert verification.status_code == 200 and "パスワード設定・利用再開" in verification.text
    assert page(pilot, account_id).context["lifecycle"]["code"] == "resume_pending"
    if finish == "cancel":
        assert transition(pilot, account_id, "cancel_pending").status_code == 303
    response = pilot[0].post("/parent-portal/resume/complete", data={
        "password": "Maple!5831Green", "password_confirmation": "Maple!5831Green",
    }, follow_redirects=False)
    assert response.status_code == 303
    assert page(pilot, account_id).context["lifecycle"]["code"] == ("active" if finish == "complete" else "stopped")
    if finish == "complete":
        with Session(pilot[1]) as session:
            assert parent_auth.authenticate_parent(session, login_id="parent@example.test", password="Maple!5831Green").account.id == account_id


def test_stale_confirmation_and_double_submit_are_rejected(pilot):
    account_id = active_account(pilot)
    revision = page(pilot, account_id).context["lifecycle"]["revision"]
    assert transition(pilot, account_id, "stop", revision=revision).status_code == 303
    assert transition(pilot, account_id, "stop", revision=revision).status_code == 409
    with Session(pilot[1]) as session:
        assert len(session.exec(select(ParentCredentialProvisioningAudit).where(ParentCredentialProvisioningAudit.operation == "stop")).all()) == 1
    revision = page(pilot, account_id).context["lifecycle"]["revision"]
    form = account_form(pilot, account_id)
    form["phone"] = "000-3333-4444"
    assert pilot[0].post(f"/parent-accounts/{account_id}/edit", data=form, follow_redirects=False).status_code == 303
    assert transition(pilot, account_id, "resume", revision=revision).status_code == 409


def test_failed_mail_validation_rolls_back_and_preserves_reason(pilot, monkeypatch):
    account_id = active_account(pilot)
    assert transition(pilot, account_id, "stop").status_code == 303
    revision = page(pilot, account_id).context["lifecycle"]["revision"]
    monkeypatch.setenv("HOIKUICT_PARENT_MAIL_TRANSPORT", "disabled")
    response = transition(pilot, account_id, "reset_resume")
    assert response.status_code == 400 and response.context["lifecycle_values"]["reason"]
    assert page(pilot, account_id).context["lifecycle"]["revision"] == revision
    with Session(pilot[1]) as session:
        assert not session.exec(select(ParentMailDelivery)).all()
    monkeypatch.setenv("HOIKUICT_PARENT_MAIL_TRANSPORT", "capture")
    assert transition(pilot, account_id, "reset_resume").status_code == 303


def test_database_failure_retains_stopped_state_and_allows_retry(pilot, monkeypatch):
    account_id = active_account(pilot)
    assert transition(pilot, account_id, "stop").status_code == 303
    original = Session.commit
    def fail_commit(session):
        raise OperationalError("synthetic failure", {}, Exception("fixture"))
    monkeypatch.setattr(Session, "commit", fail_commit)
    response = transition(pilot, account_id, "resume")
    assert response.status_code == 503 and response.context["lifecycle"]["code"] == "stopped"
    assert response.context["lifecycle_values"]["reason"]
    monkeypatch.setattr(Session, "commit", original)
    assert transition(pilot, account_id, "resume").status_code == 303


def test_lifecycle_requires_admin_and_csrf(pilot, monkeypatch):
    account_id = active_account(pilot)
    revision = page(pilot, account_id).context["lifecycle"]["revision"]
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "1")
    app = FastAPI(dependencies=[Depends(verify_csrf)])
    app.add_middleware(CsrfTokenMiddleware)
    app.include_router(routes.router)
    app.dependency_overrides.update(pilot[3].dependency_overrides)
    endpoint = f"/parent-accounts/{account_id}/authentication/lifecycle"
    with TestClient(app, base_url="https://testserver") as client:
        client.get(f"/parent-accounts/{account_id}/authentication")
        form = dict(action="stop", reason="検証", revision=revision, confirmed="yes")
        assert client.post(endpoint, data=form).status_code == 403
        form["csrf_token"] = client.cookies.get(CSRF_COOKIE_NAME)
        app.dependency_overrides[routes.get_current_staff_user] = lambda: StaffUser(
            role=Role.CAN_EDIT, name="台帳担当", can_manage_child_records=True, user_id=pilot[2]["actor"])
        assert client.post(endpoint, data=form).status_code == 403
    assert page(pilot, account_id).context["lifecycle"]["code"] == "active"


def test_database_claim_rejects_stale_session(pilot):
    account_id = active_account(pilot)
    with Session(pilot[1]) as stale:
        account = stale.get(ParentAccount, account_id)
        revision = parent_lifecycle_state(stale, account)["revision"]
        assert transition(pilot, account_id, "stop").status_code == 303
        with pytest.raises(StaleParentLifecycle):
            change_parent_lifecycle(stale, account, stale.get(User, pilot[2]["actor"]),
                                    action="stop", reason="古い確認", revision=revision)
        stale.rollback()
