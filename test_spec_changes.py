import json
from datetime import date

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser, get_current_staff_user
from csrf import CSRF_COOKIE_NAME, CsrfTokenMiddleware, verify_csrf
from database import get_session
from data_transfer_service import build_csv_content, build_xlsx_content, commit_import, export_rows, preview_import, template_rows
from family_support import sync_family_to_children
from import_state import ledger_state, state_revision
from models import Child, Classroom, DataTransferLog, Family, Message, ParentAccount, ParentChildLink, PasswordCredential, User
from routers import data_transfers, guardian, meeting_notes, staff_auth, staff_rooms


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOIKUICT_PREVIEW_DIR", str(tmp_path / "previews"))
    monkeypatch.setenv("HOIKUICT_ENV", "development")
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "0")
    monkeypatch.setenv("HOIKUICT_COOKIE_SECURE", "0")
    monkeypatch.setenv("HOIKUICT_KIOSK_ACCESS_MODE", "disabled")
    monkeypatch.setattr(staff_rooms, "MESSAGE_UPLOAD_ROOT", tmp_path / "attachments")
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    SQLModel.metadata.create_all(engine)
    ids = {}
    with Session(engine) as session:
        for key, role in (("admin", "admin"), ("author", "can_edit"), ("other", "can_edit")):
            user = User(email=f"{key}@example.test", display_name="同じ名前", staff_role=role)
            session.add(user)
            session.flush()
            ids[key] = user.id
        family = Family(family_name="検証家", home_address="旧住所", home_phone="0311112222", shared_profile={
            "extra_root": {"keep": True}, "guardians": [
                {"order": 1, "last_name": "検証", "first_name": "一郎", "phone": "09011112222", "workplace": "既存会社", "custom": {"keep": True}},
                {"order": 2, "last_name": "検証", "first_name": "二郎", "phone": "09033334444"},
                {"order": 3, "last_name": "検証", "first_name": "三郎", "relationship": "祖父"},
            ]})
        room = Classroom(name="検証クラス")
        session.add_all([family, room])
        session.flush()
        ids.update(family=family.id, room=room.id)
        for first in ("花子", "太郎"):
            session.add(Child(last_name="検証", first_name=first, last_name_kana="ケンショウ", first_name_kana=first,
                              birth_date=date(2023, 1, 1), enrollment_date=date(2026, 4, 1), family_id=family.id))
        session.flush()
        sync_family_to_children(session, family)
        session.commit()
    current = {"user": StaffUser(role=Role.ADMIN, name="同じ名前", user_id=ids["admin"])}
    app = FastAPI(dependencies=[Depends(verify_csrf)])
    app.add_middleware(CsrfTokenMiddleware)
    for module in (data_transfers, guardian, meeting_notes, staff_auth, staff_rooms):
        app.include_router(module.router)
    def sessions():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_current_staff_user] = lambda: current["user"]
    with TestClient(app) as client:
        yield client, engine, ids, current
    engine.dispose()


def family_file(ids, **values):
    headers = template_rows("families")[0]
    row = {"ID": str(ids["family"]), **values}
    return build_csv_content([headers, [row.get(h, "") for h in headers]])


def preview_token(client, content, dataset="families", filename="family.csv"):
    response = client.post(f"/data-transfers/import/{dataset}/preview", files={"file": (filename, content)})
    assert response.status_code == 200, response.text
    result = response.context["preview_result"]
    assert not result.errors, result.errors
    return result.preview_token, result


def test_family_24_columns_sparse_updates_and_history(env):
    client, engine, ids, _ = env
    data = family_file(ids, **{"住所": "新住所", "保護者①姓": "検証", "保護者①名": "一郎", "保護者①電話番号": "09099998888"})
    with Session(engine) as session:
        before = state_revision(ledger_state(session))
    token, result = preview_token(client, data)
    assert {d["entity"] for d in result.changes} == {"家庭", "園児"}
    with Session(engine) as session:
        assert before == state_revision(ledger_state(session))
        assert len(export_rows(session, "families")[0]) == 24
    response = client.post("/data-transfers/import/families/commit", data={"preview_token": token}, follow_redirects=False)
    assert response.status_code == 303, response.text
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        profiles = family.guardian_profiles()
        assert [p["order"] for p in profiles] == [1, 2, 3]
        assert profiles[0]["phone"] == "09099998888"
        assert profiles[0]["workplace"] == "既存会社"
        assert profiles[0]["custom"] == {"keep": True}
        assert family.shared_profile["extra_root"] == {"keep": True}
        for child in session.exec(select(Child)).all():
            assert child.home_address == "新住所" and len(child.guardians) == 3
        log = session.exec(select(DataTransferLog)).one()
        audit = json.dumps(log.change_metadata, ensure_ascii=False)
        assert "families" in audit and "home_address" in audit
        assert "新住所" not in audit and "09099998888" not in audit
        assert not session.exec(select(ParentAccount)).all()
        assert not session.exec(select(ParentChildLink)).all()


@pytest.mark.parametrize("values,expected", [
    ({"保護者①電話番号": "09055556666"}, "姓と名"),
    ({"保護者①姓": "別人", "保護者①名": "一郎"}, "氏名が異なり"),
    ({"保護者①姓": "検証", "保護者①名": "一郎", "保護者①メールアドレス": "bad"}, "形式"),
])
def test_family_rejects_ambiguous_or_partial_guardian(env, values, expected):
    _, engine, ids, _ = env
    with Session(engine) as session:
        result = preview_import(session, "families", "f.csv", family_file(ids, **values))
        assert any(expected in e.message for e in result.errors)


def test_family_duplicate_identity_and_wrong_phone_need_id(env):
    _, engine, ids, _ = env
    headers = template_rows("families")[0]
    with Session(engine) as session:
        one = {"ID": str(ids["family"])}
        two = {"家庭名": "検証家", "電話番号": "0311112222"}
        data = build_csv_content([headers, *[[r.get(h, "") for h in headers] for r in (one, two)]])
        assert any("重複" in e.message for e in preview_import(session, "families", "f.csv", data).errors)
        data = family_file({"family": ""}, **{"家庭名": "検証家", "電話番号": "wrong", "保護者①姓": "検証", "保護者①名": "一郎"})
        assert any("家庭ID" in e.message for e in preview_import(session, "families", "f.csv", data).errors)


def test_new_slot_two_shared_email_and_old_four_column(env):
    _, engine, ids, _ = env
    data = family_file({"family": ""}, **{"家庭名": "新規家", "保護者②姓": "新規", "保護者②名": "保護者", "保護者②メールアドレス": "shared@example.test"})
    with Session(engine) as session:
        assert not commit_import(session, "families", "f.csv", data, actor_name="担当者").errors
        family = session.exec(select(Family).where(Family.family_name == "新規家")).one()
        assert [(p["order"], p["relationship"]) for p in family.guardian_profiles()] == [(2, "保護者")]
        old = build_csv_content([["ID", "家庭名", "住所", "電話番号"], [str(ids["family"]), "", "別住所", ""]])
        assert not commit_import(session, "families", "f.csv", old, actor_name="担当者").errors
        assert len(session.get(Family, ids["family"]).guardian_profiles()) == 3


def test_bound_account_email_contact_not_login_and_permissions_preserved(env):
    client, engine, ids, _ = env
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        account = ParentAccount(display_name="検証 一郎", email="contact@example.test", family_id=family.id, home_address="別世帯住所")
        session.add(account)
        session.flush()
        profiles = family.guardian_profiles()
        profiles[0].update(parent_account_id=account.id, email=account.email)
        family.shared_profile = {"guardians": profiles}
        session.add(family)
        child = session.exec(select(Child)).first()
        session.add(ParentChildLink(parent_account_id=account.id, child_id=child.id, relationship_label="保護者"))
        session.add(PasswordCredential(principal_type="parent", parent_account_id=account.id, login_id_normalized="different-login", login_id="different-login"))
        session.commit()
        account_id = account.id
    data = family_file(ids, **{"住所": "共通新住所", "保護者①姓": "検証", "保護者①名": "一郎", "保護者①メールアドレス": "contact@example.test", "保護者①電話番号": "09000009999"})
    token, result = preview_token(client, data)
    assert any(d["entity"] == "保護者アカウント" and d["field"] == "phone" for d in result.changes)
    assert client.post("/data-transfers/import/families/commit", data={"preview_token": token}, follow_redirects=False).status_code == 303
    with Session(engine) as session:
        account = session.get(ParentAccount, account_id)
        assert account.phone == "09000009999" and account.home_address == "別世帯住所"
        assert len(session.exec(select(ParentChildLink)).all()) == 1
        assert session.exec(select(PasswordCredential)).one().login_id == "different-login"
        bad = family_file(ids, **{"保護者①姓": "検証", "保護者①名": "一郎", "保護者①メールアドレス": "new@example.test"})
        assert any("CSVで変更できません" in e.message for e in preview_import(session, "families", "f.csv", bad).errors)


def test_preview_owner_revision_one_use_and_direct_upload(env):
    client, engine, ids, current = env
    data = family_file(ids, **{"住所": "更新住所"})
    token, _ = preview_token(client, data)
    saved_user = current["user"]
    current["user"] = StaffUser(role=Role.ADMIN, name="同じ名前", user_id=ids["other"])
    url = "/data-transfers/import/families/commit"
    assert client.post(url, data={"preview_token": token}).status_code == 403
    current["user"] = saved_user
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        family.home_phone = "changed-after-preview"
        session.add(family)
        session.commit()
    assert client.post(url, data={"preview_token": token}).status_code == 400
    assert client.post(url, data={"preview_token": token}).status_code == 400
    assert client.post(url, files={"file": ("f.csv", data)}).status_code == 400
    with Session(engine) as session:
        assert session.get(Family, ids["family"]).home_address == "旧住所"


def test_xlsx_cp932_unknown_and_duplicate_columns(env):
    _, engine, ids, _ = env
    rows = [["ID", "家庭名", "住所", "電話番号", "未対応"], [str(ids["family"]), "", "日本語住所", "", "値"]]
    with Session(engine) as session:
        for filename, content in (("f.xlsx", build_xlsx_content(rows, "家庭")), ("f.csv", build_csv_content(rows).decode("utf-8-sig").encode("cp932"))):
            result = preview_import(session, "families", filename, content)
            assert not result.errors and len(result.warnings) == 1
        duplicate = build_csv_content([rows[0] + ["ID"], rows[1] + [""]])
        assert preview_import(session, "families", "f.csv", duplicate).errors


def test_mid_file_exception_rolls_back_every_family(env, monkeypatch):
    import data_transfer_service as service
    _, engine, ids, _ = env
    original = service.apply_family_shared_data
    calls = []
    def fail_second(*args, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            raise RuntimeError("private-data-must-not-be-logged")
        return original(*args, **kwargs)
    monkeypatch.setattr(service, "apply_family_shared_data", fail_second)
    data = build_csv_content([["ID", "家庭名", "住所", "電話番号"], [str(ids["family"]), "", "変更住所", ""], ["", "新規家", "", ""]])
    with Session(engine) as session:
        result = commit_import(session, "families", "f.csv", data, actor_name="担当者")
        assert result.errors and "取り消し" in result.errors[0].message
        assert session.get(Family, ids["family"]).home_address == "旧住所"
        assert len(session.exec(select(Family)).all()) == 1


def test_new_child_gets_family_guardians_and_move_to_empty_family_fails(env):
    _, engine, ids, _ = env
    headers = template_rows("children")[0]
    row = {"姓": "検証", "名": "追加", "姓カナ": "ケンショウ", "名カナ": "ツイカ", "生年月日": "2024-01-01", "入園日": "2026-04-01", "家庭ID": str(ids["family"])}
    with Session(engine) as session:
        result = commit_import(session, "children", "c.csv", build_csv_content([headers, [row.get(h, "") for h in headers]]), actor_name="担当者")
        assert not result.errors, result.errors
        child = session.exec(select(Child).where(Child.first_name == "追加")).one()
        assert len(child.guardians) == 3 and child.home_phone == "0311112222"
        empty = Family(family_name="空の家庭")
        session.add(empty)
        session.commit()
        row.update(ID=str(child.id), 家庭ID=str(empty.id))
        result = preview_import(session, "children", "c.csv", build_csv_content([headers, [row.get(h, "") for h in headers]]))
        assert any("移動先" in e.message for e in result.errors)


def test_staff_import_disable_and_self_protection(env):
    client, engine, ids, current = env
    page = client.get("/data-transfers/?dataset=staff_users")
    assert page.context["selected_dataset"] == "staff_users"
    assert 'action="/data-transfers/import/staff_users/preview"' in page.text
    data = build_csv_content([template_rows("staff_users")[0], ["", "名簿職員", "directory@example.test", "20"]])
    token, _ = preview_token(client, data, "staff_users", "staff.csv")
    assert client.post("/data-transfers/import/staff_users/commit", data={"preview_token": token}, follow_redirects=False).status_code == 303
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == "directory@example.test")).one()
        user_id = user.id
        assert user.staff_role == "view_only" and not user.can_manage_child_records
        assert not session.exec(select(PasswordCredential)).all()
    assert client.post(f"/staff/users/{user_id}/delete", follow_redirects=False).status_code == 303
    assert "名簿職員" not in client.get("/staff/users").text
    assert "名簿職員" in client.get("/staff/users?status=all").text
    assert client.post(f"/staff/users/{ids['admin']}/delete").status_code == 400
    with Session(engine) as session:
        assert session.get(User, user_id).is_active is False
    current["user"] = StaffUser(role=Role.CAN_EDIT, user_id=ids["other"], can_manage_child_records=True)
    assert client.get("/data-transfers/export/staff_users.csv").status_code == 403
    assert client.post(f"/staff/users/{ids['author']}/delete").status_code == 403


def test_message_owner_uses_user_id_and_preserves_replies(env):
    client, engine, ids, current = env
    current["user"] = StaffUser(role=Role.CAN_EDIT, name="同じ名前", user_id=ids["author"])
    assert client.post("/staff-rooms/messages", data={"body": "削除する本文"}, follow_redirects=False).status_code == 303
    with Session(engine) as session:
        message = session.exec(select(Message)).one()
        message_id = message.id
        assert message.author_user_id == ids["author"]
        session.add(Message(room_id=ids["room"], parent_message_id=message_id, author_name="返信者", body="残す返信"))
        session.commit()
    assert f"/messages/{message_id}/delete" in client.get("/staff-rooms/partials/timeline").text
    current["user"] = StaffUser(role=Role.CAN_EDIT, name="同じ名前", user_id=ids["other"])
    assert client.post(f"/staff-rooms/messages/{message_id}/delete").status_code == 403
    current["user"] = StaffUser(role=Role.CAN_EDIT, name="同じ名前", user_id=ids["author"])
    assert client.post(f"/staff-rooms/messages/{message_id}/delete", follow_redirects=False).status_code == 303
    thread = client.get(f"/staff-rooms/threads/{message_id}")
    assert "削除する本文" not in thread.text and "残す返信" in thread.text


def test_csrf_meeting_save_and_import_enforced(env, monkeypatch):
    client, engine, ids, _ = env
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "1")
    client.get("/meeting-notes/")
    token = client.cookies[CSRF_COOKIE_NAME]
    assert client.post("/meeting-notes/").status_code == 403
    created = client.post("/meeting-notes/", headers={"X-CSRF-Token": token}, follow_redirects=False)
    assert created.status_code == 303
    note_id = int(created.headers["location"].rsplit("/", 1)[-1])
    detail = client.get(f"/meeting-notes/{note_id}")
    assert "'X-CSRF-Token': document.querySelector" in detail.text
    payload = {"title": "保存確認", "content_base64": "AQID", "plain_text": "保存本文"}
    assert client.post(f"/meeting-notes/api/{note_id}/save", json=payload).status_code == 403
    assert client.post(f"/meeting-notes/api/{note_id}/save", json=payload, headers={"X-CSRF-Token": token}).status_code == 200
    assert client.post("/data-transfers/import/families/preview", files={"file": ("f.csv", family_file(ids))}).status_code == 403


def test_kiosk_setup_explains_disabled_without_exposing_children(env):
    client, _, _, _ = env
    page = client.get("/guardian/setup")
    assert page.status_code == 200 and "現在は無効" in page.text
    assert client.get("/guardian/").status_code == 404


def test_added_columns_migrate_idempotently(env, monkeypatch):
    import database
    _, engine, _, _ = env
    monkeypatch.setattr(database, "engine", engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE data_transfer_logs")
        connection.exec_driver_sql("CREATE TABLE data_transfer_logs (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("DROP TABLE messages")
        connection.exec_driver_sql("CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)")
    for _ in range(2):
        database._migrate_data_transfer_audit()
        database._migrate_add_message_columns()
    with engine.begin() as connection:
        assert "change_metadata" in {r[1] for r in connection.exec_driver_sql("PRAGMA table_info(data_transfer_logs)")}
        assert "author_user_id" in {r[1] for r in connection.exec_driver_sql("PRAGMA table_info(messages)")}


@pytest.mark.parametrize("problem", ["duplicate_order", "missing_account", "wrong_family", "duplicate_account"])
def test_family_binding_inconsistency_rejected_before_write(env, problem):
    _, engine, ids, _ = env
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        profiles = family.guardian_profiles()
        if problem == "duplicate_order":
            profiles[1]["order"] = 1
        elif problem == "missing_account":
            profiles[0]["parent_account_id"] = 99999
        else:
            account = ParentAccount(display_name="検証 一郎", email="bound@example.test", family_id=family.id if problem == "duplicate_account" else None)
            session.add(account)
            session.flush()
            profiles[0].update(parent_account_id=account.id, email=account.email)
            if problem == "duplicate_account":
                profiles[1].update(parent_account_id=account.id, email=account.email)
        family.shared_profile = {"guardians": profiles}
        session.add(family)
        session.commit()
        result = preview_import(session, "families", "f.csv", family_file(ids, **{"住所": "変更不可"}))
        assert result.errors
        assert session.get(Family, family.id).home_address == "旧住所"


def test_same_preview_cannot_commit_concurrently(env):
    from concurrent.futures import ThreadPoolExecutor
    client, engine, ids, _ = env
    token, _ = preview_token(client, family_file(ids, **{"住所": "一度だけ更新"}))
    def submit():
        return client.post("/data-transfers/import/families/commit", data={"preview_token": token}, follow_redirects=False).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(results) == [303, 400]
    with Session(engine) as session:
        assert len(session.exec(select(DataTransferLog).where(DataTransferLog.result == "success")).all()) == 1


def test_attachment_hidden_after_message_deletion(env):
    from models import MessageAttachment
    client, engine, _, _ = env
    assert client.post("/staff-rooms/messages", data={"body": "添付あり"}, files={"attachments": ("notes.txt", b"private attachment", "text/plain")}, follow_redirects=False).status_code == 303
    with Session(engine) as session:
        attachment = session.exec(select(MessageAttachment)).one()
        attachment_id, message_id = attachment.id, attachment.message_id
    url = f"/staff-rooms/attachments/{attachment_id}"
    assert client.get(url).status_code == 200
    assert client.post(f"/staff-rooms/messages/{message_id}/delete", follow_redirects=False).status_code == 303
    assert client.get(url).status_code == 404


def test_old_csv_keeps_guardians_held_only_by_child(env):
    _, engine, ids, _ = env
    with Session(engine) as session:
        family = session.get(Family, ids["family"])
        family.shared_profile = {"guardians": []}
        family.home_address = None
        family.home_phone = None
        session.add(family)
        session.commit()
        data = build_csv_content([["ID", "家庭名", "住所", "電話番号"], [str(ids["family"]), "変更家庭名", "", ""]])
        result = commit_import(session, "families", "f.csv", data, actor_name="担当者")
        assert not result.errors
        for child in session.exec(select(Child)).all():
            assert len(child.guardians) == 3
            assert child.home_address == "旧住所" and child.home_phone == "0311112222"


def test_reimport_creates_no_duplicates_and_shared_mail_does_not_bind(env):
    _, engine, _, _ = env
    data = family_file({"family": ""}, **{"家庭名": "共用メール家庭", "電話番号": "0312349876",
         "保護者①姓": "検証", "保護者①名": "父", "保護者①メールアドレス": "shared@example.test",
         "保護者②姓": "検証", "保護者②名": "母", "保護者②メールアドレス": "shared@example.test"})
    with Session(engine) as session:
        for _ in range(2):
            assert not commit_import(session, "families", "f.csv", data, actor_name="担当者").errors
        families = session.exec(select(Family).where(Family.family_name == "共用メール家庭")).all()
        assert len(families) == 1 and len(families[0].guardian_profiles()) == 2
        assert all(not p["parent_account_id"] for p in families[0].guardian_profiles())
        assert not session.exec(select(ParentAccount)).all()
