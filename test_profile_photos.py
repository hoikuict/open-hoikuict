from datetime import date
from io import BytesIO

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from auth import Role, StaffUser, get_current_staff_user
from child_profile_changes import apply_child_profile_payload, child_profile_form_data_from_child
from data_transfer_service import build_csv_content, commit_import, export_rows, preview_import
from database import get_session
import database
from models import Child, ChildProfileChangeRequest, ChildProfileHistory, ChildSex, Family, Guardian, ParentAccount, ParentAccountStatus, ParentChildLink, ProfilePhoto
from routers import child_change_requests, children, families, parent_portal


def image_bytes(color="orange", size=(1200, 800)):
    output = BytesIO()
    exif = Image.Exif()
    exif[0x010E] = "metadata must not survive"
    Image.new("RGB", size, color).save(output, "JPEG", exif=exif)
    return output.getvalue()


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    for router in (children.router, families.router, parent_portal.router, child_change_requests.router):
        app.include_router(router)

    def session_override():
        with Session(engine) as session:
            yield session

    def staff_override(request: Request):
        role = request.headers.get("X-Staff")
        if not role:
            raise HTTPException(401)
        return StaffUser(role=Role(role), name="写真担当")

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_current_staff_user] = staff_override
    monkeypatch.setattr(parent_portal, "get_current_parent_account_id", lambda request: int(request.headers.get("X-Parent", "0")) or None)
    monkeypatch.setattr(parent_portal, "parent_auth_is_mock", lambda: False)
    with Session(engine) as session:
        family = Family(family_name="テスト家", shared_profile={"guardians": [
            {"order": 1, "last_name": "テスト", "first_name": "保護者", "relationship": "母"},
            {"order": 3, "last_name": "テスト", "first_name": "祖母", "relationship": "祖母", "note": "保持する"},
        ]})
        session.add(family)
        session.flush()
        child = Child(last_name="テスト", first_name="園児", last_name_kana="テスト", first_name_kana="エンジ", birth_date=date(2021, 4, 1), enrollment_date=date(2024, 4, 1), family_id=family.id)
        sibling = Child(last_name="テスト", first_name="きょうだい", last_name_kana="テスト", first_name_kana="キョウダイ", birth_date=date(2022, 4, 1), enrollment_date=date(2024, 4, 1), family_id=family.id)
        parent = ParentAccount(display_name="保護者", email="photo@example.test", status=ParentAccountStatus.active, family_id=family.id)
        other = ParentAccount(display_name="別の保護者", email="other@example.test", status=ParentAccountStatus.active)
        session.add_all([child, sibling, parent, other])
        session.flush()
        session.add(ParentChildLink(parent_account_id=parent.id, child_id=child.id))
        session.commit()
        ids = {"child": child.id, "sibling": sibling.id, "family": family.id, "parent": parent.id, "other": other.id}
    with TestClient(app, headers={"X-Staff": "admin"}, follow_redirects=False) as client:
        yield client, engine, ids
    engine.dispose()


def child_form(ids, **updates):
    return {"last_name": "テスト", "first_name": "園児", "last_name_kana": "テスト", "first_name_kana": "エンジ", "birth_date": "2021-04-01", "enrollment_date": "2024-04-01", "family_selection": str(ids["family"]), "g1_last_name": "テスト", "g1_first_name": "保護者", "g1_relationship": "母", **updates}


def test_staff_create_edit_remove_and_private_photos(setup):
    client, engine, ids = setup
    response = client.post("/children/", data=child_form(ids, sex="female"), files={"child_photo": ("photo.jpg", image_bytes(), "image/jpeg"), "g1_photo": ("parent.jpg", image_bytes("blue"), "image/jpeg")})
    assert response.status_code == 303
    with Session(engine) as session:
        child = session.exec(select(Child).order_by(Child.id.desc())).first()
        photo_id, child_id = child.photo_id, child.id
        assert child.sex == ChildSex.female
        guardian_photo = session.get(Family, ids["family"]).guardian_profiles()[0]["photo_id"]
        assert child.photo_id != guardian_photo
        guardians = session.exec(select(Guardian).where(Guardian.order == 1)).all()
        assert len(guardians) == 3
        assert all(guardian.photo_id == guardian_photo for guardian in guardians)
    image_response = client.get(f"/children/photos/{photo_id}")
    assert image_response.status_code == 200
    assert image_response.headers["cache-control"] == "private, no-store"
    with Image.open(BytesIO(image_response.content)) as image:
        assert max(image.size) == 1024
        assert not image.getexif()
    assert client.get(f"/children/{child_id}").status_code == 200
    assert f'/children/photos/{guardian_photo}' in client.get(f"/children/{ids['sibling']}").text
    client.headers.pop("X-Staff")
    assert client.get(f"/children/photos/{photo_id}").status_code == 401
    client.headers["X-Staff"] = "view_only"
    assert client.post(f"/children/{child_id}/edit", data=child_form(ids, sex="male")).status_code == 403
    client.headers["X-Staff"] = "admin"
    assert client.post(f"/children/{child_id}/edit", data=child_form(ids)).status_code == 303
    with Session(engine) as session:
        assert session.get(Child, child_id).sex == ChildSex.female
        assert session.get(Child, child_id).photo_id == photo_id
        assert session.get(Family, ids["family"]).guardian_profiles()[0]["photo_id"] == guardian_photo
    assert client.post(f"/children/{child_id}/edit", data=child_form(ids, child_photo_remove="true", g1_photo_remove="true", sex="not_set")).status_code == 303
    with Session(engine) as session:
        assert session.get(Child, child_id).photo_id is None
        assert session.get(Child, child_id).sex == ChildSex.not_set
        profiles = session.get(Family, ids["family"]).guardian_profiles()
        assert profiles[0]["photo_id"] is None
        assert profiles[1]["note"] == "保持する"
        history = session.exec(select(ChildProfileHistory).where(ChildProfileHistory.child_id == child_id).order_by(ChildProfileHistory.id.desc())).first()
        assert {"photo_id", "g1_photo_id", "sex"} <= history.changes.keys()
        assert client.get(f"/children/{child_id}/history/{history.id}").status_code == 200


@pytest.mark.parametrize("content", [b"<svg onload='alert(1)'></svg>", b"not a jpeg", b"x" * (10 * 1024 * 1024 + 1)], ids=["svg", "corrupt", "oversized"])
def test_invalid_photo_rolls_back_all_changes(setup, content):
    client, engine, ids = setup
    response = client.post(f"/children/{ids['child']}/edit", data=child_form(ids, sex="male"), files={"child_photo": ("photo.jpg", content, "image/jpeg")})
    assert "写真" in response.text
    with Session(engine) as session:
        assert session.get(Child, ids["child"]).sex == ChildSex.not_set
        assert not session.exec(select(ProfilePhoto)).all()


def test_parent_request_approval_scope_and_draft_preservation(setup):
    client, engine, ids = setup
    client.headers["X-Parent"] = str(ids["parent"])
    url = f"/parent-portal/children/{ids['child']}/profile"
    result = client.post(url, data=child_form(ids, sex="male"), files={"child_photo": ("child.jpg", image_bytes(), "image/jpeg"), "g1_photo": ("parent.jpg", image_bytes("green"), "image/jpeg")})
    assert result.status_code == 303
    with Session(engine) as session:
        request = session.exec(select(ChildProfileChangeRequest)).one()
        request_id = request.id
        photo_id = request.request_data["child_data"]["photo_id"]
        guardian_photo = request.request_data["guardians_data"][0]["photo_id"]
        assert session.get(Child, ids["child"]).sex == ChildSex.not_set
        assert session.get(Child, ids["child"]).photo_id is None
    assert client.get(f"/parent-portal/photos/{photo_id}").status_code == 200
    assert f"/parent-portal/photos/{photo_id}" in client.get(url).text
    assert client.post(url, data=child_form(ids, sex="male", home_phone="03-1234-5678")).status_code == 303
    assert photo_id in client.get(f"/child-change-requests/{request_id}").text
    assert client.post(f"/child-change-requests/{request_id}/approve").status_code == 303
    with Session(engine) as session:
        assert session.get(Child, ids["child"]).photo_id == photo_id
        assert session.get(Child, ids["child"]).sex == ChildSex.male
        assert session.get(Family, ids["family"]).guardian_profiles()[0]["photo_id"] == guardian_photo
    client.headers["X-Parent"] = str(ids["other"])
    assert client.get(f"/parent-portal/photos/{photo_id}").status_code == 404
    assert client.get(f"/parent-portal/photos/{guardian_photo}").status_code == 404
    client.headers.pop("X-Parent")
    assert client.get(f"/parent-portal/photos/{photo_id}").status_code == 401


def test_family_photo_edit_and_legacy_request_preserve_photos(setup):
    client, engine, ids = setup
    data = {"family_name": "テスト家", "child_ids": [str(ids["child"]), str(ids["sibling"])], "parent_account_ids": [str(ids["parent"])], "g1_last_name": "テスト", "g1_first_name": "保護者"}
    assert client.post(f"/families/{ids['family']}/edit", data=data, files={"g1_photo": ("p.jpg", image_bytes(), "image/jpeg")}).status_code == 303
    with Session(engine) as session:
        child = session.get(Child, ids["child"])
        photo_id = child.family.guardian_profiles()[0]["photo_id"]
        child.sex = ChildSex.female
        payload = child_profile_form_data_from_child(child)
        for key in ("sex", "photo_id"):
            payload.pop(key, None)
            payload["child_data"].pop(key, None)
        for profile in payload["guardians_data"]:
            profile.pop("photo_id", None)
        apply_child_profile_payload(session, child, payload)
        session.commit()
        assert child.sex == ChildSex.female
        assert child.family.guardian_profiles()[0]["photo_id"] == photo_id


def test_csv_sex_roundtrip_validation_and_omission(setup):
    _, engine, ids = setup
    with Session(engine) as session:
        rows = export_rows(session, "children")
        index = rows[0].index("性別")
        rows[1][index] = "女"
        data = build_csv_content(rows)
        assert not preview_import(session, "children", "children.csv", data).errors
        assert not commit_import(session, "children", "children.csv", data, actor_name="CSV担当").errors
        assert export_rows(session, "children")[1][index] == "女"
        rows[1][index] = "invalid"
        assert preview_import(session, "children", "children.csv", build_csv_content(rows)).errors
        without_sex = [row[:index] + row[index + 1:] for row in rows]
        assert not commit_import(session, "children", "old.csv", build_csv_content(without_sex), actor_name="CSV担当").errors
        assert export_rows(session, "children")[1][index] == "女"


def test_existing_database_migration_is_idempotent(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE children (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO children (id) VALUES (1)"))
    monkeypatch.setattr(database, "engine", engine)
    database._migrate_add_child_columns()
    database._migrate_add_child_columns()
    with engine.connect() as connection:
        assert connection.execute(text("SELECT sex, photo_id FROM children WHERE id = 1")).one() == ("not_set", None)
    engine.dispose()
