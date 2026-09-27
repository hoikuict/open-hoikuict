"""Release checks using synthetic data and the application's security/backup paths."""
from datetime import date
from io import BytesIO
from pathlib import Path
import sqlite3

from fastapi import Depends, FastAPI, UploadFile
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from sqlmodel import Session, create_engine, select

from csrf import CSRF_COOKIE_NAME, CsrfTokenMiddleware, verify_csrf
import database
from models import Child, ChildProfileChangeRequest, ChildSex, Family, Guardian, ParentChildLink
from profile_photos import normalize_photo, save_photo
from routers import children
from scripts.backup_runtime import BackupConfig, create_backup, verify_backup_set
from test_profile_photos import child_form, image_bytes, setup


@pytest.fixture
def photo_state(monkeypatch):
    yield from setup.__wrapped__(monkeypatch)


def test_photo_multipart_requires_valid_csrf(photo_state, monkeypatch):
    client, engine, ids = photo_state
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "1")
    secure_app = FastAPI(dependencies=[Depends(verify_csrf)])
    secure_app.add_middleware(CsrfTokenMiddleware)
    secure_app.include_router(children.router)
    secure_app.dependency_overrides = client.app.dependency_overrides.copy()
    with TestClient(secure_app, base_url="https://testserver", headers={"X-Staff": "admin"}, follow_redirects=False) as secure:
        url = f"/children/{ids['child']}/edit"
        assert secure.get(url).status_code == 200
        files = {"child_photo": ("photo.jpg", image_bytes(), "image/jpeg")}
        assert secure.post(url, data=child_form(ids), files=files).status_code == 403
        token = secure.cookies[CSRF_COOKIE_NAME]
        assert secure.post(url, data=child_form(ids, csrf_token=token, sex="female"), files=files).status_code == 303
    with Session(engine) as session:
        assert session.get(Child, ids["child"]).photo_id
        assert session.get(Child, ids["child"]).sex == ChildSex.female


def test_photos_follow_explicit_links_and_pending_request_status(photo_state):
    client, engine, ids = photo_state
    client.headers["X-Parent"] = str(ids["parent"])
    files = {"child_photo": ("p.jpg", image_bytes(), "image/jpeg")}
    assert client.post(f"/children/{ids['sibling']}/edit", data=child_form(ids), files=files).status_code == 303
    with Session(engine) as session:
        sibling_photo = session.get(Child, ids["sibling"]).photo_id
    assert client.get(f"/parent-portal/photos/{sibling_photo}").status_code == 404

    url = f"/parent-portal/children/{ids['child']}/profile"
    assert client.post(url, data=child_form(ids), files=files).status_code == 303
    with Session(engine) as session:
        draft = session.exec(select(ChildProfileChangeRequest)).one()
        draft_id, draft_photo = draft.id, draft.request_data["child_data"]["photo_id"]
    assert client.get(f"/parent-portal/photos/{draft_photo}").status_code == 200
    assert client.post(f"/child-change-requests/{draft_id}/reject").status_code == 303
    assert client.get(f"/parent-portal/photos/{draft_photo}").status_code == 404
    assert client.post(f"/children/{ids['child']}/edit", data=child_form(ids), files=files).status_code == 303
    with Session(engine) as session:
        current_photo = session.get(Child, ids["child"]).photo_id
        link = session.exec(select(ParentChildLink).where(ParentChildLink.parent_account_id == ids["parent"])).one()
        session.delete(link)
        session.commit()
    assert client.get(f"/parent-portal/photos/{current_photo}").status_code == 404


@pytest.mark.parametrize("format", ["PNG", "WEBP"])
def test_supported_photos_are_normalized_without_metadata(format):
    source = BytesIO()
    Image.new("RGBA", (40, 60), (255, 0, 0, 0)).save(source, format)
    source.seek(0)
    result = normalize_photo(UploadFile(file=source, filename=f"photo.{format.lower()}"))
    with Image.open(BytesIO(result)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_old_schema_upgrade_and_photo_backup_restore(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    storage = runtime / "storage"
    storage.mkdir()
    main_db = runtime / "main.db"
    engine = create_engine(f"sqlite:///{main_db}")
    monkeypatch.setattr(database, "engine", engine)
    database.create_db_and_tables()
    with Session(engine) as session:
        family = Family(family_name="架空家族")
        session.add(family)
        session.flush()
        child = Child(last_name="架空", first_name="園児", last_name_kana="カクウ", first_name_kana="エンジ", birth_date=date(2021, 4, 1), enrollment_date=date(2024, 4, 1), family_id=family.id)
        session.add(child)
        session.flush()
        session.add(Guardian(child_id=child.id, last_name="架空", first_name="保護者"))
        session.commit()
        child_id = child.id
    engine.dispose()
    # Reconstruct the exact pre-feature columns, retaining all prior row values.
    with sqlite3.connect(main_db) as connection:
        connection.execute("ALTER TABLE children DROP COLUMN sex")
        connection.execute("ALTER TABLE children DROP COLUMN photo_id")
        connection.execute("ALTER TABLE guardians DROP COLUMN photo_id")
        connection.execute("DROP TABLE profile_photos")
        before_child = connection.execute("SELECT * FROM children").fetchall()
        before_guardian = connection.execute("SELECT * FROM guardians").fetchall()
        child_columns = [row[1] for row in connection.execute("PRAGMA table_info(children)")]
        guardian_columns = [row[1] for row in connection.execute("PRAGMA table_info(guardians)")]
    database.create_db_and_tables()
    database.create_db_and_tables()
    with sqlite3.connect(main_db) as connection:
        assert connection.execute('SELECT ' + ', '.join('"' + c + '"' for c in child_columns) + ' FROM children').fetchall() == before_child
        assert connection.execute('SELECT ' + ', '.join('"' + c + '"' for c in guardian_columns) + ' FROM guardians').fetchall() == before_guardian
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    photo = image_bytes()
    with Session(engine) as session:
        child = session.get(Child, child_id)
        assert child.sex == ChildSex.not_set
        child.photo_id = save_photo(session, photo, child_id=child.id)
        child.sex = ChildSex.female
        session.add(child)
        session.commit()
        photo_id = child.photo_id
    engine.dispose()
    facility_db = runtime / "facility.sqlite"
    with sqlite3.connect(facility_db) as connection:
        from plan_docs.services.bunrei import _ensure_facility_table
        _ensure_facility_table(connection)
    config = BackupConfig(output_root=tmp_path / "backups", database_url=f"sqlite:///{main_db}", facility_db=facility_db, storage_root=storage, git_sha="a" * 40, app_image="test@sha256:" + "b" * 64, compose_sha256="c" * 64, quiesced=True, environment="test", cloudflared_image="cloudflared@sha256:" + "d" * 64, recovery_kit_ref="test-kit", actor_ref="test-operator", baseline_ref="test-baseline")
    backup = create_backup(config)
    assert verify_backup_set(backup)["status"] == "ok"
    restored = tmp_path / "restored.db"
    restored.write_bytes((Path(backup) / "db" / "hoikuict.db").read_bytes())
    with sqlite3.connect(restored) as connection:
        assert connection.execute("SELECT sex, photo_id FROM children WHERE id = ?", (child_id,)).fetchone() == ("female", photo_id)
        assert connection.execute("SELECT content FROM profile_photos WHERE id = ?", (photo_id,)).fetchone()[0] == photo
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
