"""Regression scenarios for an account explicitly linked to all 98 children."""

from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from local_auth import AuthenticationFailed, hash_password
from models import AuthSession, Child, Family, ParentAccount, ParentChildLink, PasswordCredential, User
from parent_auth import (
    authenticate_parent, complete_parent_action_password, ensure_parent_credential,
    exchange_parent_action_code, issue_parent_password_code, resolve_parent_session, token_hash,
)
from routers.parent_portal import _child_ids, _load_accessible_child
from test_guardian_account_sync import account_form, create_account, pilot as pilot_fixture
from time_utils import utc_now


@pytest.fixture
def pilot(monkeypatch):
    yield from pilot_fixture.__wrapped__(monkeypatch)


@pytest.mark.parametrize("operation", ["unlink_guardian", "unlink_family", "unlink_children", "stop_account", "stop_and_resume"])
def test_family_membership_child_access_and_account_status_are_independent(pilot, operation):
    client, engine, ids, _ = pilot
    account_id = create_account(pilot)
    raw_session = "synthetic-investigation-session"
    with Session(engine) as session:
        session.add_all([
            Child(last_name="架空", first_name=f"園児{number}",
                  last_name_kana="カクウ", first_name_kana=f"エンジ{number}",
                  birth_date=date(2021, 4, 1), enrollment_date=date(2024, 4, 1),
                  family_id=ids["other"])
            for number in range(96)
        ])
        session.flush()
        child_ids = list(session.exec(select(Child.id)).all())
        assert len(child_ids) == 98
        session.add_all([
            ParentChildLink(parent_account_id=account_id, child_id=child_id)
            for child_id in child_ids if child_id != ids["child"]
        ])
        account = session.get(ParentAccount, account_id)
        credential = ensure_parent_credential(session, account)
        credential_id = credential.id
        if operation == "stop_and_resume":
            credential.password_hash = hash_password("Cedar!9274Blue")
            session.add(credential)
        session.add(AuthSession(
            token_hash=token_hash(raw_session), principal_type="parent",
            credential_id=credential.id, parent_account_id=account_id,
            credential_version=credential.credential_version,
            idle_expires_at=utc_now() + timedelta(hours=1),
            absolute_expires_at=utc_now() + timedelta(hours=2),
        ))
        session.commit()
        assert resolve_parent_session(session, raw_session).id == account_id
        assert _child_ids(account) == set(child_ids)

    form = account_form(pilot, account_id)
    form.update(child_ids=child_ids, status="active")
    if operation in {"unlink_guardian", "unlink_family"}:
        form["guardian_link"] = "none"
    if operation == "unlink_family":
        form["family_id"] = ""
    if operation == "unlink_children":
        # Browsers omit the field entirely when every checkbox is unchecked.
        form.pop("child_ids")
    if operation in {"stop_account", "stop_and_resume"}:
        page = client.get(f"/parent-accounts/{account_id}/authentication")
        response = client.post(f"/parent-accounts/{account_id}/authentication/lifecycle", data={
            "action": "stop", "reason": "一時休止", "confirmed": "yes",
            "revision": page.context["lifecycle"]["revision"],
        }, follow_redirects=False)
    else:
        response = client.post(f"/parent-accounts/{account_id}/edit", data=form, follow_redirects=False)
    assert response.status_code == 303, response.text

    page = client.get(f"/parent-accounts/{account_id}/edit")
    assert page.status_code == 200
    expected_child_ids = set() if operation == "unlink_children" else set(child_ids)
    assert page.context["selected_child_ids"] == expected_child_ids
    with Session(engine) as session:
        account = session.get(ParentAccount, account_id)
        assert _child_ids(account) == expected_child_ids
        assert account.family_id == (None if operation == "unlink_family" else ids["family"])
        if operation in {"unlink_guardian", "unlink_family"}:
            family = session.get(Family, ids["family"])
            assert all(p.get("parent_account_id") != account_id for p in family.guardian_profiles())
        if operation == "unlink_children":
            with pytest.raises(HTTPException) as denied:
                _load_accessible_child(account, child_ids[0])
            assert denied.value.status_code == 404
        credential = session.get(PasswordCredential, credential_id)
        if operation in {"stop_account", "stop_and_resume"}:
            assert account.status.value == "inactive"
            assert credential.disabled_at is not None
            assert session.get(AuthSession, token_hash(raw_session)).revoked_at is not None
            assert resolve_parent_session(session, raw_session) is None
        else:
            assert account.status.value == "active"
            assert credential.disabled_at is None
            assert resolve_parent_session(session, raw_session).id == account_id

    if operation == "stop_and_resume":
        page = client.get(f"/parent-accounts/{account_id}/authentication")
        response = client.post(f"/parent-accounts/{account_id}/authentication/lifecycle", data={
            "action": "resume", "reason": "利用再開", "confirmed": "yes",
            "revision": page.context["lifecycle"]["revision"],
        }, follow_redirects=False)
        assert response.status_code == 303, response.text
        with Session(engine) as session:
            account = session.get(ParentAccount, account_id)
            assert account.status.value == "active"
            assert session.get(PasswordCredential, credential_id).disabled_at is None
            login = authenticate_parent(session, login_id=account.email, password="Cedar!9274Blue")
            assert login.account.id == account_id
            assert resolve_parent_session(session, raw_session) is None
            assert _child_ids(account) == set(child_ids)
