from copy import deepcopy
from datetime import date

import pytest
from sqlmodel import Session, select

from child_profile_changes import apply_child_profile_payload, child_data_from_child
from data_transfer_service import build_csv_content, commit_import, preview_import
from family_support import family_form_data_from_family, sync_family_to_children
from models import Child, Family, Guardian, ParentAccount, ParentChildLink
from test_guardian_account_sync import create_account, pilot as pilot_fixture
from test_parent_enrollment import invite, open_form, profile, review


@pytest.fixture
def pilot(monkeypatch):
    yield from pilot_fixture.__wrapped__(monkeypatch)


def seed_guardians(pilot, orders, *, bind_third=False):
    _, engine, ids, _ = pilot
    profiles = [
        {"order": order, "last_name": "検証", "first_name": f"保護者{order}",
         "relationship": "祖母" if order == 3 else "保護者", "phone": f"0900000000{order}",
         "workplace": f"既存の勤務先{order}", "workplace_address": "既存の勤務先住所",
         "workplace_phone": "0311112222", "legacy_note": {"value": f"保持{order}"}}
        for order in orders
    ]
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        if bind_third:
            account = ParentAccount(display_name="検証 保護者3", email="grandparent@example.test", family_id=family.id)
            session.add(account)
            session.flush()
            profiles[-1].update(parent_account_id=account.id, email=account.email)
            session.add(ParentChildLink(parent_account_id=account.id, child_id=ids["child"], relationship_label="祖母"))
        family.shared_profile = {"guardians": profiles, "import_source": {"name": "架空の既存台帳"}}
        session.add(family)
        sync_family_to_children(session, family)
        session.commit()
    return profiles


def assert_preserved(session, ids, orders):
    family = session.get(Family, ids["family"])
    profiles = family.guardian_profiles()
    assert [item["order"] for item in profiles] == orders
    assert family.shared_profile["import_source"] == {"name": "架空の既存台帳"}
    for item in profiles:
        assert item["legacy_note"] == {"value": f"保持{item['order']}"}
    for child_id in (ids["child"], ids["sibling"]):
        guardians = session.exec(select(Guardian).where(Guardian.child_id == child_id).order_by(Guardian.order)).all()
        assert [item.order for item in guardians] == orders
    return family, profiles


@pytest.mark.parametrize("screen", ["family", "child"])
@pytest.mark.parametrize("orders", [[2], [1, 2, 3]])
def test_edit_roundtrip_preserves_hidden_people_attributes_and_bindings(pilot, screen, orders):
    client, engine, ids, _ = pilot
    initial = seed_guardians(pilot, orders, bind_third=3 in orders)
    path = f"/families/{ids['family']}/edit" if screen == "family" else f"/children/{ids['child']}/edit"
    page = client.get(path)
    assert page.status_code == 200
    form = page.context["form_data" if screen == "family" else "family_form_data"]
    if orders == [2]:
        assert form["g1_first_name"] == ""
        assert form["g2_first_name"] == "保護者2"
    posted = {key: value for key, value in form.items() if isinstance(value, str)}
    posted["home_address"] = "更新した住所"
    with Session(engine) as session:
        if screen == "family":
            posted.update(child_ids=[ids["child"], ids["sibling"]], parent_account_ids=[a.id for a in session.exec(select(ParentAccount)).all()])
        else:
            posted.update(child_data_from_child(session.get(Child, ids["child"])))
            posted["family_selection"] = page.context["selected_family_value"]
    saved = client.post(path, data=posted, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    with Session(engine) as session:
        family, profiles = assert_preserved(session, ids, orders)
        assert family.home_address == "更新した住所"
        if 3 in orders:
            assert profiles[2]["parent_account_id"] == initial[2]["parent_account_id"]
            assert session.get(ParentAccount, profiles[2]["parent_account_id"]).family_id == family.id
            assert [link.child_id for link in session.exec(select(ParentChildLink)).all()] == [ids["child"]]


def test_empty_guardian_slots_do_not_delete_existing_people(pilot):
    client, engine, ids, _ = pilot
    seed_guardians(pilot, [1, 2, 3], bind_third=True)
    saved = client.post(f"/families/{ids['family']}/edit", data={
        "family_name": "検証家", "home_address": "住所のみの更新",
        "child_ids": [ids["child"], ids["sibling"]],
    }, follow_redirects=False)
    assert saved.status_code == 303, saved.text
    with Session(engine) as session:
        assert_preserved(session, ids, [1, 2, 3])


def test_approved_child_profile_edit_preserves_unshown_guardians(pilot):
    _, engine, ids, _ = pilot
    seed_guardians(pilot, [1, 2, 3], bind_third=True)
    with Session(engine) as session:
        child = session.get(Child, ids["child"])
        form = family_form_data_from_family(child.family)
        payload = {key: value for key, value in form.items() if isinstance(value, str)}
        payload.update(child_data_from_child(child))
        payload["g1_phone"] = "09099999999"
        apply_child_profile_payload(session, child, payload)
        session.commit()
    with Session(engine) as session:
        _, profiles = assert_preserved(session, ids, [1, 2, 3])
        assert profiles[0]["phone"] == "09099999999"
        assert session.get(ParentAccount, profiles[2]["parent_account_id"]).family_id == ids["family"]


@pytest.mark.parametrize("target_order", [1, 3])
def test_parent_intake_supplements_existing_ledger_without_deleting_others(pilot, target_order):
    client, engine, ids, _ = pilot
    original = seed_guardians(pilot, [1, 2, 3])
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        family.home_phone = "0311111111"
        child = session.get(Child, ids["child"])
        child.extra_data = {"allergy": ["Milk"], "medical_notes": "既存の連絡事項"}
        session.add_all([family, child])
        session.commit()
    registration_id, account_id, token = invite(pilot, child_id=ids["child"], guardian_order=target_order)
    form = open_form(client, token)
    assert "既存の勤務先住所" not in form.text
    submitted = client.post("/parent-portal/register/enrollment", data=profile(
        last_name="検証", first_name="葵", g1_workplace="", g1_workplace_address="", g1_workplace_phone="",
    ))
    assert submitted.status_code == 200
    assert review(client, account_id, registration_id).status_code == 303
    with Session(engine) as session:
        _, profiles = assert_preserved(session, ids, [1, 2, 3])
        for item in profiles:
            if item["order"] == target_order:
                assert item["parent_account_id"] == account_id
                assert item["phone"] == "09012345678"
                assert item["workplace"] == f"既存の勤務先{target_order}"
                assert item["workplace_address"] == "既存の勤務先住所"
            else:
                for key, value in original[item["order"] - 1].items():
                    assert item[key] == value
        assert len(session.exec(select(Child)).all()) == 2
        child = session.get(Child, ids["child"])
        assert child.birth_date == date(2023, 6, 10)
        assert child.extra_data["allergy"] == ["Milk"]
        assert child.extra_data["medical_notes"] == "既存の連絡事項"
        assert child.home_phone == "0311111111"
        assert session.get(Child, ids["sibling"]).birth_date == date(2021, 5, 4)
        assert [link.child_id for link in session.exec(select(ParentChildLink)).all()] == [ids["child"]]


def test_new_parent_intake_saves_all_submitted_child_information(pilot):
    client, engine, _, _ = pilot
    registration_id, account_id, token = invite(pilot)
    open_form(client, token)
    assert client.post("/parent-portal/register/enrollment", data=profile(
        allergy="Egg,Milk", medical_notes="提出した連絡事項", home_phone="0312345678",
    )).status_code == 200
    assert review(client, account_id, registration_id).status_code == 303
    with Session(engine) as session:
        link = session.exec(select(ParentChildLink).where(ParentChildLink.parent_account_id == account_id)).one()
        child = session.get(Child, link.child_id)
        assert child.extra_data["allergy"] == ["Egg", "Milk"]
        assert child.extra_data["medical_notes"] == "提出した連絡事項"
        assert child.home_phone == "0312345678"


def test_existing_ledger_account_registration_preserves_extra_information(pilot):
    _, engine, ids, _ = pilot
    seed_guardians(pilot, [1, 2, 3])
    account_id = create_account(pilot, email="existing@example.test")
    with Session(engine) as session:
        _, profiles = assert_preserved(session, ids, [1, 2, 3])
        assert profiles[0]["parent_account_id"] == account_id
        assert [link.child_id for link in session.exec(select(ParentChildLink)).all()] == [ids["child"]]


def test_existing_four_column_csv_then_edit_keeps_guardians(pilot):
    client, engine, ids, _ = pilot
    seed_guardians(pilot, [1, 2, 3])
    content = build_csv_content([
        ["ID", "家庭名", "住所", "電話番号"],
        [str(ids["family"]), "検証家", "CSVの住所", "0312345678"],
    ])
    with Session(engine) as session:
        preview = preview_import(session, "families", "families.csv", content)
        assert not preview.errors
        assert session.get(Family, ids["family"]).home_address == "旧住所"
        result = commit_import(session, "families", "families.csv", content, actor_name="検証担当")
        assert not result.errors
    page = client.get(f"/families/{ids['family']}/edit")
    form = {key: value for key, value in page.context["form_data"].items() if isinstance(value, str)}
    form["child_ids"] = [ids["child"], ids["sibling"]]
    assert client.post(f"/families/{ids['family']}/edit", data=form, follow_redirects=False).status_code == 303
    with Session(engine) as session:
        family, _ = assert_preserved(session, ids, [1, 2, 3])
        assert family.home_address == "CSVの住所"
        assert family.home_phone == "0312345678"


def test_duplicate_guardian_order_stops_edit_without_overwriting(pilot):
    client, engine, ids, _ = pilot
    profiles = seed_guardians(pilot, [2])
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        family.shared_profile = {"guardians": profiles + [deepcopy(profiles[0])]}
        session.add(family)
        session.commit()
    response = client.post(f"/families/{ids['family']}/edit", data={"family_name": "上書き不可"})
    assert response.status_code == 400
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        assert family.family_name == "検証家"
        assert len(family.guardian_profiles()) == 2
