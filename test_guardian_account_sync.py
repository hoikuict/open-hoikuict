from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
import auth
import database
from family_support import apply_family_shared_data, guardian_account_values
from models import (
    Child, ChildProfileChangeRequest, Family, Guardian, ParentAccount, ParentChildLink,
    ParentMailDelivery, ParentRegistrationRequest, PasswordCredential, User,
)
from parent_auth import (
    authenticate_parent, complete_parent_registration, dispatch_pending_parent_mail,
    exchange_completion_token, exchange_invitation_token, review_parent_registration,
    submit_parent_identity,
)
import routers.children as children_router
import routers.child_change_requests as changes_router
import routers.families as families_router
import routers.parent_accounts as accounts_router
import routers.parent_auth as auth_router
import routers.parent_portal as portal_router


@pytest.fixture
def pilot(monkeypatch):
    for key, value in {
        "HOIKUICT_ENV": "test", "HOIKUICT_ENABLE_MOCK_AUTH": "0",
        "HOIKUICT_PARENT_AUTH_MODE": "local_password", "HOIKUICT_PARENT_MAIL_TRANSPORT": "capture",
        "HOIKUICT_PARENT_REGISTRATION_BASE_URL": "https://testserver",
        "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY": "test-only-throttle-key" * 3,
    }.items():
        monkeypatch.setenv(key, value)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(auth, "_parent_portal_auth_backend", auth.LocalPasswordParentPortalAuthBackend())
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        actor = User(email="staff@example.test", display_name="検証担当", staff_role="admin")
        family = Family(family_name="検証家", home_address="旧住所", shared_profile={"guardians": [
            {"order": 1, "last_name": "検証", "first_name": "花", "last_name_kana": "ケンショウ",
             "first_name_kana": "ハナ", "relationship": "母", "email": "parent@example.test",
             "phone": "09011112222", "workplace": "試験会社", "workplace_address": "勤務先住所",
             "workplace_phone": "0311112222"},
            {"order": 2, "last_name": "検証", "first_name": "太郎", "relationship": "父"},
        ]})
        other = Family(family_name="別家族")
        session.add_all([actor, family, other])
        session.flush()
        children = [Child(last_name="検証", first_name=name, last_name_kana="ケンショウ", first_name_kana=kana,
                          registration_verification_name=f"ケンショウ {kana}", registration_verification_name_type="kana",
                          birth_date=date(2021, 5, 4), enrollment_date=date(2026, 4, 1), family_id=family.id)
                    for name, kana in [("葵", "アオイ"), ("空", "ソラ")]]
        session.add_all(children)
        session.commit()
        ids = dict(family=family.id, other=other.id, child=children[0].id, sibling=children[1].id, actor=actor.id)
    app = FastAPI()
    for module in [accounts_router, auth_router, portal_router, children_router, families_router, changes_router]:
        app.include_router(module.router)
    def get_session():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[accounts_router.get_session] = get_session
    staff = StaffUser(role=Role.ADMIN, name="検証担当", user_id=ids["actor"])
    app.dependency_overrides[accounts_router.get_current_staff_user] = lambda: staff
    with TestClient(app, base_url="https://testserver") as client:
        yield client, engine, ids, app
    engine.dispose()


def create_account(pilot, **changes):
    client, engine, ids, _ = pilot
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        values = guardian_account_values(family, family.guardian_profiles()[0])
    values.update(family_id=str(ids["family"]), guardian_link=f"{ids['family']}:1", child_ids=[ids["child"]])
    values.update(changes)
    response = client.post("/parent-accounts/", data=values, follow_redirects=False)
    assert response.status_code == 303, response.text
    with Session(engine) as session:
        account = session.exec(select(ParentAccount)).one()
        return account.id


def account_form(pilot, account_id):
    with Session(pilot[1]) as session:
        account = session.get(ParentAccount, account_id)
        values = {key: getattr(account, key) or "" for key in (
            "display_name", "email", "phone", "home_address", "workplace", "workplace_address", "workplace_phone",
            "registration_verification_name", "registration_verification_name_type")}
        values.update(family_id=str(account.family_id), guardian_link=f"{account.family_id}:1", child_ids=[pilot[2]["child"]])
        return values


def test_prefill_and_creation_preserve_information_and_explicit_child_access(pilot):
    client, engine, ids, _ = pilot
    response = client.get(f"/parent-accounts/new?family_id={ids['family']}&guardian_order=1&child_id={ids['child']}")
    assert response.status_code == 200
    assert response.context["account"].workplace == "試験会社"
    assert response.context["account"].registration_verification_name == "ケンショウ ハナ"
    assert response.context["selected_child_ids"] == {ids["child"]}
    account_id = create_account(pilot)
    with Session(engine) as session:
        assert session.get(Family, ids["family"]).guardian_profiles()[0]["parent_account_id"] == account_id
        assert [item.child_id for item in session.exec(select(ParentChildLink)).all()] == [ids["child"]]
        assert len(session.exec(select(Guardian)).all()) == 4  # two guardians, two siblings; no duplicate copies
    detail = client.get(f"/children/{ids['child']}")
    assert detail.status_code == 200
    assert "招待・登録状況を確認" in detail.text


def test_staff_account_edits_update_family_and_siblings(pilot):
    client, engine, ids, _ = pilot
    account_id = create_account(pilot)
    values = account_form(pilot, account_id)
    values.update(display_name="検証 華", phone="09033334444", workplace="更新会社", home_address="新住所")
    response = client.post(f"/parent-accounts/{account_id}/edit", data=values, follow_redirects=False)
    assert response.status_code == 303
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        profile = family.guardian_profiles()[0]
        assert (profile["first_name"], profile["phone"], profile["workplace"]) == ("華", "09033334444", "更新会社")
        assert family.home_address == "新住所"
        for child in session.exec(select(Child)).all():
            assert child.home_address == "新住所"
            assert len(child.guardians) == 2
            assert child.guardians[0].workplace == "更新会社"


def test_family_edits_sync_account_and_cancel_old_invitation_without_changing_login(pilot):
    client, engine, ids, _ = pilot
    account_id = create_account(pilot)
    assert client.post(f"/parent-accounts/{account_id}/authentication/invite", data={"reason": "入園"}, follow_redirects=False).status_code == 303
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        profiles = family.guardian_profiles()
        profiles[0].update(phone="09099998888", email="updated@example.test", workplace_address="新勤務先住所")
        apply_family_shared_data(session, family, dict(family_name=family.family_name, home_address="新住所", home_phone="", guardians_data=profiles))
        session.commit()
    with Session(engine) as session:
        account = session.get(ParentAccount, account_id)
        assert (account.email, account.phone, account.workplace_address, account.home_address) == ("updated@example.test", "09099998888", "新勤務先住所", "新住所")
        assert session.exec(select(PasswordCredential)).one().login_id == "parent@example.test"
        assert session.exec(select(ParentRegistrationRequest)).one().status == "cancelled"
        assert session.exec(select(ParentMailDelivery)).one().status == "cancelled"
        assert len(session.exec(select(ParentChildLink)).all()) == 1


def test_separate_household_address_is_preserved(pilot):
    account_id = create_account(pilot, home_address="別居先")
    with Session(pilot[1]) as session:
        family = session.get(Family, pilot[2]["family"])
        apply_family_shared_data(session, family, dict(family_name=family.family_name, home_address="家族の新住所", guardians_data=family.guardian_profiles()))
        session.commit()
        assert session.get(ParentAccount, account_id).home_address == "別居先"


@pytest.mark.parametrize("kind", ["other_family", "already_bound", "duplicate_email"])
def test_invalid_binding_or_duplicate_email_rolls_back(pilot, kind):
    client, engine, ids, _ = pilot
    account_id = create_account(pilot)
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        values = guardian_account_values(family, family.guardian_profiles()[0])
    values.update(family_id=str(ids["family"]), guardian_link=f"{ids['family']}:1", child_ids=[ids["child"]])
    if kind == "other_family":
        values.update(email="second@example.test", family_id=str(ids["other"]))
    elif kind == "already_bound":
        values["email"] = "second@example.test"
    else:
        values.update(email="PARENT@example.test", guardian_link="")
    response = client.post("/parent-accounts/", data=values, follow_redirects=False)
    assert response.status_code == 400
    with Session(engine) as session:
        assert [item.id for item in session.exec(select(ParentAccount)).all()] == [account_id]
        assert len(session.exec(select(ParentChildLink)).all()) == 1


def test_unlink_does_not_delete_child_permission_and_stops_contact_sync(pilot):
    client, engine, ids, _ = pilot
    account_id = create_account(pilot)
    values = account_form(pilot, account_id)
    # The form sends a sentinel to distinguish unlinking from an omitted field.
    values["guardian_link"] = "none"
    assert client.post(f"/parent-accounts/{account_id}/edit", data=values, follow_redirects=False).status_code == 303
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        assert family.guardian_profiles()[0]["parent_account_id"] is None
        assert len(session.exec(select(ParentChildLink)).all()) == 1


def test_invitation_registration_and_approved_enrollment_input(pilot):
    client, engine, ids, _ = pilot
    account_id = create_account(pilot)
    response = client.post(f"/parent-accounts/{account_id}/authentication/invite", data={"reason": "入園時の登録"}, follow_redirects=False)
    assert response.status_code == 303
    with Session(engine) as session:
        mail = session.exec(select(ParentMailDelivery)).one()
        invitation = mail.body.split("#", 1)[1].split()[0]
        assert mail.recipient == "parent@example.test"
        dispatch_pending_parent_mail(session)
        assert mail.status == "captured"
        state = exchange_invitation_token(session, invitation)
        registration = submit_parent_identity(session, raw_state=state, guardian_name="ケンショウ ハナ", child_name="ケンショウ アオイ", child_birth_date=date(2021, 5, 4))
        assert registration.status == "pending_review"
        token = review_parent_registration(session, registration=registration, actor_user=session.get(User, ids["actor"]), approve=True, reason="照合確認")
        state = exchange_completion_token(session, token)
        complete_parent_registration(session, raw_state=state, password="Cedar!9274Blue", password_confirmation="Cedar!9274Blue")
        login = authenticate_parent(session, login_id="parent@example.test", password="Cedar!9274Blue")
        session_token = login.session_token
    client.cookies.set("hoikuict_parent_session", session_token)
    client.cookies.set("__Host-hoikuict_parent_session", session_token)
    response = client.get("/parent-portal/profile", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/parent-portal/children/profile"
    # Old direct-profile submissions cannot bypass the family approval flow.
    response = client.post("/parent-portal/profile", data={"email": "bypass@example.test"}, follow_redirects=False)
    assert response.headers["location"] == "/parent-portal/children/profile"
    profile = client.get(f"/parent-portal/children/{ids['child']}/profile")
    assert profile.status_code == 200
    values = {key: value for key, value in profile.context["form_data"].items() if isinstance(value, (str, int))}
    values.update(g1_phone="09077778888", g1_workplace="保護者入力会社", home_address="入園時住所")
    response = client.post(f"/parent-portal/children/{ids['child']}/profile", data=values, follow_redirects=False)
    assert response.status_code == 303, response.text
    with Session(engine) as session:
        assert session.get(ParentAccount, account_id).workplace == "試験会社"
        pending = session.exec(select(ChildProfileChangeRequest)).one()
        # A draft from before the staff binding must not erase today's binding.
        payload = dict(pending.request_data)
        payload["guardians_data"] = [dict(item, parent_account_id=None) for item in payload["guardians_data"]]
        pending.request_data = payload
        session.add(pending)
        session.commit()
        request_id = pending.id
    response = client.post(f"/child-change-requests/{request_id}/approve", data={"review_note": "入園時確認"}, follow_redirects=False)
    assert response.status_code == 303, response.text
    with Session(engine) as session:
        account = session.get(ParentAccount, account_id)
        assert account.workplace == "保護者入力会社"
        assert account.phone == "09077778888"
        assert session.get(Child, ids["sibling"]).home_address == "入園時住所"
        assert account.email == "parent@example.test"
    status = client.get(f"/parent-accounts/{account_id}/authentication")
    assert status.status_code == 200
    assert "メールの配送状況" in status.text and "テスト保存済み" in status.text
    assert invitation not in status.text and token not in status.text


def test_unauthorized_staff_cannot_create_account_from_guardian(pilot):
    client, _, ids, app = pilot
    app.dependency_overrides[accounts_router.get_current_staff_user] = lambda: StaffUser(role=Role.VIEW_ONLY)
    response = client.get(f"/parent-accounts/new?family_id={ids['family']}&guardian_order=1")
    assert response.status_code == 403


def test_invitation_page_explains_missing_child_verification_before_sending(pilot):
    client, engine, ids, _ = pilot
    account_id = create_account(pilot)
    with Session(engine) as session:
        child = session.get(Child, ids["child"])
        child.registration_verification_name = None
        session.add(child)
        session.commit()
    response = client.get(f"/parent-accounts/{account_id}/authentication")
    assert response.status_code == 200
    assert "招待前に登録情報を確認" in response.text
    assert f'/children/{ids["child"]}/edit' in response.text
    assert response.context["invitation_issues"]
    assert client.post(f"/parent-accounts/{account_id}/authentication/invite", data={"reason": "入園"}).status_code == 400
    with Session(engine) as session:
        assert not session.exec(select(ParentMailDelivery)).all()
