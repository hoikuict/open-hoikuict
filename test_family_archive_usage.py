"""Exercise normal family workflows through the routes after list-only archiving."""

from datetime import date
import html
import re

import pytest
from sqlmodel import Session, select

from data_transfer_service import (
    build_csv_content,
    commit_import,
    preview_import,
    template_rows,
)
from models import (
    Child,
    Family,
    ParentAccount,
    ParentChildLink,
    ParentEnrollment,
    ParentRegistrationRequest,
)
from parent_notification_service import notify_attendance_confirmation_needed
import test_guardian_account_sync as guardian_tests
import test_parent_enrollment as intake_tests


@pytest.fixture
def pilot(monkeypatch):
    # Route authentication is supplied by the existing isolated test fixture.
    # CSRF/session binding is covered with real middleware in test_family_archive.
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "0")
    monkeypatch.setenv(
        "HOIKUICT_SECRET_KEY", "archive-usage-synthetic-test-key-0123456789"
    )
    yield from guardian_tests.pilot.__wrapped__(monkeypatch)


def change_visibility(pilot, action="archive"):
    client, _, ids, _ = pilot
    url = f"/families/{ids['family']}/{action}"
    page = client.get(url)
    assert page.status_code == 200, page.text
    token = re.search(r'name="review_token" value="([^"]+)"', page.text)
    assert token, page.text
    response = client.post(
        url,
        data={"review_token": html.unescape(token.group(1))},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text


@pytest.mark.parametrize("when", ["before_registration", "after_login"])
def test_parent_registration_login_profile_approval_and_notifications_continue(
    pilot, when
):
    client, engine, ids, _ = pilot
    if when == "before_registration":
        change_visibility(pilot)
    # Includes account creation, invitation, password setup, login, parent form,
    # staff approval, and contact synchronization to the family and sibling.
    guardian_tests.test_invitation_registration_and_approved_enrollment_input(pilot)
    if when == "after_login":
        change_visibility(pilot)
    assert (
        client.get(f"/parent-portal/children/{ids['child']}/profile").status_code == 200
    )
    with Session(engine) as session:
        account = session.exec(select(ParentAccount)).one()
        notifications = notify_attendance_confirmation_needed(
            session,
            child=session.get(Child, ids["child"]),
            target_date=date(2026, 9, 22),
            source_id="archive-usage-test",
            created_by_name="検証担当",
        )
        session.commit()
        assert [item.parent_account_id for item in notifications] == [account.id]
        assert session.get(Family, ids["family"]).is_archived
        assert len(session.exec(select(ParentChildLink)).all()) == 1


@pytest.mark.parametrize(
    "when", ["before_invitation", "during_input", "after_submission"]
)
def test_initial_input_and_approval_continue_without_reinvitation(pilot, when):
    client, engine, ids, _ = pilot
    if when == "before_invitation":
        change_visibility(pilot)
    registration_id, account_id, token = intake_tests.invite(
        pilot,
        child_id=ids["child"],
        guardian_order=1,
    )
    intake_tests.open_form(client, token)
    if when == "during_input":
        change_visibility(pilot)
        change_visibility(pilot, "restore")
        change_visibility(pilot)
    response = client.post(
        "/parent-portal/register/enrollment",
        data=intake_tests.profile(last_name="検証", first_name="葵"),
    )
    assert response.status_code == 200, response.text
    if when == "after_submission":
        change_visibility(pilot)
    response = intake_tests.review(client, account_id, registration_id)
    assert response.status_code == 303, response.text
    with Session(engine) as session:
        assert session.get(ParentEnrollment, registration_id).applied_at is not None
        assert (
            session.get(ParentRegistrationRequest, registration_id).status == "approved"
        )
        assert session.get(Family, ids["family"]).is_archived
        assert session.get(Child, ids["sibling"]).home_address == "検証用の住所"
        assert len(session.exec(select(Child)).all()) == 2


def test_actual_content_changes_still_require_review(pilot):
    change_visibility(pilot)
    intake_tests.test_changed_ledger_blocks_approval_without_overwriting(pilot)


def test_family_parent_child_edit_pages_and_family_choices_remain_available(pilot):
    client, engine, ids, _ = pilot
    account_id = guardian_tests.create_account(pilot)
    change_visibility(pilot)
    for path in [
        f"/families/{ids['family']}/edit",
        f"/children/{ids['child']}/edit",
        f"/parent-accounts/{account_id}/edit",
        "/children/new",
        "/parent-accounts/new",
    ]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, (path, response.text)
        assert "家庭一覧でアーカイブ済み" in response.text, path
    values = guardian_tests.account_form(pilot, account_id)
    values.update(phone="09033334444", home_address="アーカイブ後の住所")
    response = client.post(
        f"/parent-accounts/{account_id}/edit", data=values, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    with Session(engine) as session:
        assert session.get(Family, ids["family"]).home_address == "アーカイブ後の住所"
        assert session.get(Child, ids["sibling"]).home_address == "アーカイブ後の住所"
    child_form = client.get(f"/children/{ids['child']}/edit").context
    values = dict(child_form["family_form_data"])
    values.update(
        last_name="検証",
        first_name="葵",
        last_name_kana="ケンショウ",
        first_name_kana="アオイ",
        birth_date="2021-05-04",
        enrollment_date="2026-04-01",
        family_selection=str(ids["family"]),
        allergy="検証用の追記",
    )
    response = client.post(
        f"/children/{ids['child']}/edit", data=values, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    with Session(engine) as session:
        assert session.get(Child, ids["child"]).get_field("allergy") == "検証用の追記"
        assert session.get(Child, ids["child"]).family_id == ids["family"]
        assert session.get(Family, ids["family"]).is_archived


def test_child_parent_and_link_csv_updates_keep_archive_state(pilot):
    _, engine, ids, _ = pilot
    account_id = guardian_tests.create_account(pilot)
    change_visibility(pilot)
    with Session(engine) as session:
        link_id = session.exec(select(ParentChildLink)).one().id
    changes = [
        ("children", {"ID": str(ids["child"]), "名": "葵更新"}),
        ("parent_accounts", {"ID": str(account_id), "電話番号": "09055556666"}),
        (
            "parent_child_links",
            {"ID": str(link_id), "続柄": "保護者", "主連絡先": "はい"},
        ),
    ]
    for dataset, row in changes:
        headers = template_rows(dataset)[0]
        assert set(row).issubset(headers)
        content = build_csv_content(
            [headers, [row.get(header, "") for header in headers]]
        )
        with Session(engine) as session:
            result = preview_import(session, dataset, "test.csv", content)
            assert not result.errors, result.errors
            result = commit_import(
                session,
                dataset,
                "test.csv",
                content,
                actor_name="検証",
                expected_revision=result.revision,
            )
            assert not result.errors, result.errors
            assert session.get(Family, ids["family"]).is_archived
    with Session(engine) as session:
        assert session.get(Child, ids["child"]).first_name == "葵更新"
        assert session.get(ParentAccount, account_id).phone == "09055556666"
        assert session.get(ParentChildLink, link_id).is_primary_contact
