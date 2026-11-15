from datetime import date, timedelta
import os
from types import SimpleNamespace

import pytest
import child_records.models  # noqa: F401 -- plan foreign-key targets
from sqlmodel import Session, select

from csrf import CSRF_COOKIE_NAME
from models import Child, Classroom, DailyContactEntry, ParentContactFieldSetting, ParentContactFieldAudit
import parent_contact_fields as fields
import test_parent_portal as portal_fixture
import test_settings_sessions as settings_fixture

setup = settings_fixture.setup

DAY = date(2026, 11, 16)


@pytest.fixture
def portal(monkeypatch):
    for key in ("HOIKUICT_ENV", "HOIKUICT_ENABLE_MOCK_AUTH", "HOIKUICT_ENABLE_MOCK_ROLE_OVERRIDE", "HOIKUICT_KIOSK_ACCESS_MODE"):
        monkeypatch.setenv(key, os.environ.get(key, ""))
    test = portal_fixture.ParentPortalTests()
    test.setUp()
    test._login_parent(test.parent_account_id)
    yield test
    test.tearDown()


def configured(portal, *, mode="age", hidden=None, revision=1):
    with Session(portal.engine) as session:
        child = session.get(Child, portal.child_id)
        policy = fields.default_policy()
        policy["mode"] = mode
        key = fields.age_group(child.birth_date, DAY) if mode == "age" else str(child.classroom_id)
        policy[mode][key] = fields.all_fields()
        for group in (hidden if hidden is not None else fields.GROUPS):
            policy[mode][key][group] = False
        setting = session.get(ParentContactFieldSetting, 1) or ParentContactFieldSetting(policy=policy)
        setting.policy, setting.revision = policy, revision
        session.add(setting)
        session.commit()
        return policy


def url(portal, day=DAY):
    return f"/parent-portal/children/{portal.child_id}/contact?date={day}"


def submit(portal, **extra):
    page = portal.client.get(url(portal))
    data = {"date": str(DAY), "attendance_mode": "present", "care_fields_version": "1", "meal_fields_version": "1",
            "contact_revision": page.context["contact_revision"],
            "contact_fields_revision": page.context["contact_fields_revision"], **extra}
    return portal.client.post(url(portal), data=data, follow_redirects=False)


@pytest.mark.parametrize("mode", ["age", "class"])
def test_hidden_input_is_not_validated_or_saved_and_shared_fields_remain(portal, mode):
    configured(portal, mode=mode)
    page = portal.client.get(url(portal))
    assert page.context["field_visibility"] == dict.fromkeys(fields.GROUPS, False)
    response = submit(portal, temperature="99.9", bedtime="bad", stool_count="-1", dinner_appetite="invalid",
                      breakfast_appetite="invalid", cough="forged", condition_note="forged", contact_note="連絡は残す")
    assert response.status_code == 303, response.text
    with Session(portal.engine) as session:
        entry = session.exec(select(DailyContactEntry)).one()
        assert entry.temperature is None and entry.cough is None and entry.condition_note is None
        assert not entry.extra_data.get("bedtime") and not entry.extra_data.get("stool_count")
        assert not entry.extra_data.get("dinner_appetite")
        assert entry.contact_note == "連絡は残す"
        assert not fields.contact_field_enabled(entry, "temperature")
    for path in ["/parent-portal/history", f"/parent-portal/?date={DAY}",
                 f"/daily-contacts/{portal.child_id}?date={DAY}", f"/daily-contacts/?date={DAY}&view=content"]:
        response = portal.client.get(path)
        assert response.status_code == 200
        assert "対象外" in response.text
        assert "forged" not in response.text and "99.9" not in response.text


def test_record_keeps_saved_mask_when_facility_settings_change(portal):
    configured(portal, hidden=["temperature", "dinner"])
    assert submit(portal, mood="良好").status_code == 303
    configured(portal, hidden=["mood"], revision=2)
    existing = portal.client.get(url(portal))
    assert existing.context["field_visibility"]["mood"] is True
    assert existing.context["field_visibility"]["temperature"] is False
    new = portal.client.get(url(portal, DAY + timedelta(days=1)))
    assert new.context["field_visibility"]["mood"] is False
    assert new.context["field_visibility"]["temperature"] is True
    assert submit(portal, mood="ふつう", temperature="bad").status_code == 303


def test_legacy_record_and_validation_error_keep_original_fields(portal):
    with Session(portal.engine) as session:
        entry = DailyContactEntry(child_id=portal.child_id, parent_account_id=portal.parent_account_id,
                                  target_date=DAY, temperature="36.8", extra_data={"dinner_contents": "旧夕食"})
        session.add(entry)
        session.commit()
    configured(portal)
    page = portal.client.get(url(portal))
    assert all(page.context["field_visibility"].values())
    error = submit(portal, attendance_mode="absent", absence_reason="")
    assert all(error.context["field_visibility"].values())
    assert "旧夕食" in page.text
    response = portal.client.post(url(portal), data={"date": str(DAY), "attendance_mode": "present", "temperature": "36.9"}, follow_redirects=False)
    assert response.status_code == 303
    with Session(portal.engine) as session:
        entry = session.exec(select(DailyContactEntry)).one()
        assert entry.temperature == "36.9" and entry.extra_data["dinner_contents"] == "旧夕食"
        assert all(entry.extra_data[fields.SNAPSHOT_KEY]["fields"].values())


def test_changed_settings_reject_stale_submission_without_partial_save(portal):
    page = portal.client.get(url(portal))
    configured(portal)
    response = portal.client.post(url(portal), data={"date": str(DAY), "attendance_mode": "present",
        "contact_fields_revision": page.context["contact_fields_revision"], "contact_note": "古い画面"}, follow_redirects=False)
    assert response.status_code == 409
    assert "設定が変わりました" in response.text
    with Session(portal.engine) as session:
        assert session.exec(select(DailyContactEntry)).all() == []
    assert portal.client.post(url(portal), data={"date": str(DAY), "attendance_mode": "present"}).status_code == 409


def test_sick_absence_still_requires_temperature_and_symptoms(portal):
    configured(portal)
    error = submit(portal, attendance_mode="absent", absence_reason="absent_sick")
    assert "病欠の場合は現在の体温を入力してください" in error.text
    assert submit(portal, attendance_mode="absent", absence_reason="absent_sick", absence_temperature="38.2",
                  absence_symptoms="発熱").status_code == 303
    with Session(portal.engine) as session:
        entry = session.exec(select(DailyContactEntry)).one()
        assert entry.absence_temperature == "38.2" and entry.absence_symptoms == "発熱"


def test_shown_temperature_and_meal_validation_unchanged(portal):
    configured(portal, hidden=["mood"])
    assert "37.5" in submit(portal, temperature="38.0").context["form_error"]
    assert submit(portal, dinner_appetite="wrong").context["form_error"]
    with Session(portal.engine) as session:
        assert session.exec(select(DailyContactEntry)).all() == []


@pytest.mark.parametrize("birth,day,expected", [
    (date(2023,4,1), date(2026,4,1), "3"), (date(2023,4,2), date(2026,4,1), "2"),
    (date(2023,4,1), date(2026,3,31), "2"), (date(2026,5,1), DAY, "0"),
    (date(2018,1,1), DAY, None), (date(2027,1,1), DAY, None), (None,DAY,None),
])
def test_fiscal_age_boundary(birth, day, expected):
    assert fields.age_group(birth, day) == expected


def settings_data(client, **changes):
    response = client.get("/settings/parent-contact-fields")
    data = {"revision": response.context["revision"], "room_ids": response.context["room_ids"],
            "mode": "age", "action": "save", "csrf_token": client.cookies[CSRF_COOKIE_NAME]}
    for mode, columns in response.context["tables"]:
        for key, _ in columns:
            for group in fields.GROUPS:
                data[f"{mode}_{key}_{group}"] = "show"
    return {**data, **changes}


def test_settings_switch_preview_cancel_and_save_are_separate(setup):
    _, client, session, actor, _ = setup
    room = Classroom(name="混合クラス")
    session.add(room); session.commit(); session.refresh(room)
    data = settings_data(client, action="preview", age_4_temperature="hide", mode="class")
    data[f"class_{room.id}_dinner"] = "hide"
    preview = client.post("/settings/parent-contact-fields", data=data)
    assert preview.status_code == 200
    assert session.get(ParentContactFieldSetting, 1) is None
    assert "sandbox=\"allow-scripts\"" in preview.text
    assert '<script src=' not in preview.context["preview_html"]
    assert 'data-order-editor' in preview.context["preview_html"]
    assert "form-action 'none'" in preview.context["preview_html"]
    assert preview.context["policy"]["age"]["4"]["temperature"] is False
    assert client.get("/settings/parent-contact-fields").context["policy"]["age"]["4"]["temperature"] is True
    data["action"] = "save"
    assert client.post("/settings/parent-contact-fields", data=data, follow_redirects=False).status_code == 303
    policy, revision = fields.get_policy(session)
    assert policy["mode"] == "class" and revision == 1
    assert policy["age"]["4"]["temperature"] is False
    child = SimpleNamespace(classroom_id=room.id, birth_date=date(2021,5,5))
    mask = fields.fields_snapshot(session, child, DAY)["fields"]
    assert mask["temperature"] and not mask["dinner"]
    child.classroom_id = None
    assert all(fields.fields_snapshot(session, child, DAY)["fields"].values())
    assert session.exec(select(ParentContactFieldAudit)).one().changed_by_user_id == actor.id
    assert client.post("/settings/parent-contact-fields", data=data).status_code == 409
    assert len(session.exec(select(ParentContactFieldAudit)).all()) == 1


def test_settings_reject_changed_classes_incomplete_choices_and_csrf(setup):
    _, client, session, _, _ = setup
    data = settings_data(client)
    without_csrf = {key:value for key,value in data.items() if key != "csrf_token"}
    assert client.post("/settings/parent-contact-fields", data=without_csrf).status_code == 403
    assert client.post("/settings/parent-contact-fields", data={**data,"age_0_temperature":"inherit"}).status_code == 400
    session.add(Classroom(name="追加クラス")); session.commit()
    assert client.post("/settings/parent-contact-fields", data=data).status_code == 409
    assert session.get(ParentContactFieldSetting,1) is None


@pytest.mark.parametrize("role,active", [("can_edit",True),("view_only",True),("admin",False)])
def test_settings_requires_current_active_admin(setup, role, active):
    _, client, session, actor, _ = setup
    data = settings_data(client)
    actor.staff_role, actor.is_active = role, active
    session.add(actor); session.commit()
    assert client.get("/settings/parent-contact-fields").status_code == 403
    assert client.post("/settings/parent-contact-fields",data=data).status_code == 403
