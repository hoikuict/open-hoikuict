import os
import html
import json
import re
import sqlite3
import shutil
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, select

import main
from auth import mock_auth_enabled
from database import get_session
from demo_runtime import get_demo_session_manager, reset_demo_runtime_cache
from models import (
    CareTimeCategory,
    Child,
    Classroom,
    Family,
    FamilyArchiveLog,
    ChildCareCertification,
    DocumentReviewRequest,
    ExtendedCareCalculationSetting,
    ExtendedCareFeeRule,
    NotificationDeliveryChannel,
    ParentAccount,
    ParentNotification,
    ParentNotificationDelivery,
    ParentNotificationKind,
    ParentPushDeliveryTarget,
    ParentPushDeliveryTargetStatus,
    ParentPushSubscription,
    StaffClassroomAssignment,
    User,
)
from parent_push_runtime import run_parent_push_worker_once
from plan_docs.contracts import DocumentType
from plan_docs.db_models import PlanDocumentRow
from security_config import validate_runtime_security
from starlette.requests import HTTPConnection


class PublicDemoCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.runtime_dir = Path.cwd() / f"_demo_runtime_compat_{time.time_ns()}"
        self.runtime_dir.mkdir()
        self.original_env = {
            name: os.environ.get(name)
            for name in (
                "PUBLIC_DEMO_MODE",
                "DEMO_RUNTIME_DIR",
                "DEMO_SECURE_COOKIES",
                "HOIKUICT_ENV",
                "HOIKUICT_SECRET_KEY",
                "HOIKUICT_ENABLE_MOCK_AUTH",
                "HOIKUICT_PUSH_TRANSPORT",
            )
        }
        os.environ["PUBLIC_DEMO_MODE"] = "1"
        os.environ["DEMO_RUNTIME_DIR"] = str(self.runtime_dir)
        os.environ["DEMO_SECURE_COOKIES"] = "0"
        os.environ["HOIKUICT_ENV"] = "production"
        os.environ["HOIKUICT_PUSH_TRANSPORT"] = "capture"
        os.environ.pop("HOIKUICT_SECRET_KEY", None)
        os.environ.pop("HOIKUICT_ENABLE_MOCK_AUTH", None)
        reset_demo_runtime_cache()

    def tearDown(self):
        try:
            get_demo_session_manager().close()
        except Exception:
            pass
        reset_demo_runtime_cache()
        for name, value in self.original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def test_existing_demo_yaml_security_defaults_are_accepted(self):
        validate_runtime_security()
        self.assertTrue(mock_auth_enabled())

    def test_public_demo_keeps_mock_auth_and_does_not_start_password_mail_workers(self):
        from security_config import parent_auth_mode, staff_auth_mode

        with (
            patch.dict(os.environ, {"HOIKUICT_STAFF_AUTH_MODE": "local_password", "HOIKUICT_PARENT_AUTH_MODE": "local_password"}),
            patch.object(main, "parent_mail_worker_loop") as parent_mail,
            patch.object(main, "staff_mail_worker_loop") as staff_mail,
        ):
            with TestClient(main.app) as client:
                self.assertEqual(client.get("/staff/login").status_code, 200)
                self.assertEqual(staff_auth_mode(), "mock")
                self.assertEqual(parent_auth_mode(), "mock")
            parent_mail.assert_not_called()
            staff_mail.assert_not_called()

    def _login_admin(self, client):
        from csrf import CSRF_COOKIE_NAME

        response = client.get("/staff/login")
        session_id = response.headers["X-Demo-Session-Id"]
        with Session(get_demo_session_manager().get_engine(session_id)) as session:
            admin = session.exec(select(User).where(User.staff_role == "admin")).first()
            admin_id = str(admin.id)
        response = client.post("/staff/login", data={"user_id": admin_id},
                               headers={"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)})
        self.assertEqual(response.status_code, 200)
        return session_id

    def _form_token(self, response, name):
        self.assertEqual(response.status_code, 200)
        token = re.search(r'name="' + name + r'" value="([^"]+)"', response.text)
        self.assertIsNotNone(token)
        return html.unescape(token.group(1))

    def test_linked_family_archive_and_parent_login_remain_session_isolated(self):
        from csrf import CSRF_COOKIE_NAME

        with TestClient(main.app, base_url="https://testserver") as client:
            first_id = self._login_admin(client)
            manager = get_demo_session_manager()
            with Session(manager.get_engine(first_id)) as session:
                account = session.exec(select(ParentAccount).where(ParentAccount.family_id.is_not(None))).first()
                family_id, parent_id = account.family_id, account.id
                family = session.get(Family, family_id)
                children_before = [(child.id, child.status, child.family_id) for child in family.children]
                parents_before = [(parent.id, parent.status, parent.family_id) for parent in family.parent_accounts]
                family_updated_at = family.updated_at
            self.assertTrue(children_before)
            url = f"/families/{family_id}/archive"
            token = self._form_token(client.get(url), "review_token")
            csrf = client.cookies.get(CSRF_COOKIE_NAME)
            headers = {"X-CSRF-Token": csrf}
            response = client.post(url, data={"review_token": token}, headers=headers, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(client.get(f"/families/{family_id}/edit").status_code, 200)
            self.assertEqual(client.get(f"/parent-portal/mock-login/{parent_id}").status_code, 200)
            self.assertEqual(client.get("/parent-portal/").status_code, 200)
            with Session(manager.get_engine(first_id)) as session:
                family = session.get(Family, family_id)
                self.assertTrue(family.is_archived)
                self.assertEqual(family.updated_at, family_updated_at)
                self.assertEqual([(c.id, c.status, c.family_id) for c in family.children], children_before)
                self.assertEqual([(p.id, p.status, p.family_id) for p in family.parent_accounts], parents_before)
            first_cookies = dict(client.cookies)
            client.cookies.clear()
            second_id = self._login_admin(client)
            self.assertNotEqual(first_id, second_id)
            # Even with the same seeded actor and copied CSRF cookie, a review from
            # another visitor may not mutate this visitor's corresponding family.
            client.cookies.set(CSRF_COOKIE_NAME, csrf, domain="testserver.local", path="/")
            response = client.post(url, data={"review_token": token}, headers=headers, follow_redirects=False)
            self.assertEqual(response.status_code, 409)
            with Session(manager.get_engine(second_id)) as session:
                self.assertFalse(session.get(Family, family_id).is_archived)
                self.assertEqual(session.exec(select(FamilyArchiveLog)).all(), [])
            client.cookies.clear()
            client.cookies.update(first_cookies)
            restore_url = f"/families/{family_id}/restore"
            token = self._form_token(client.get(restore_url), "review_token")
            response = client.post(restore_url, data={"review_token": token},
                                   headers={"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            with Session(manager.get_engine(first_id)) as session:
                self.assertFalse(session.get(Family, family_id).is_archived)
                self.assertEqual(len(session.exec(select(FamilyArchiveLog)).all()), 2)

    def test_csv_preview_is_bound_to_its_demo_session(self):
        from csrf import CSRF_COOKIE_NAME
        from data_transfer_service import build_csv_content, export_rows
        from routers import data_transfers

        with patch.object(data_transfers, "PREVIEW_DIR", self.runtime_dir / "previews"), TestClient(main.app, base_url="https://testserver") as client:
            first_id = self._login_admin(client)
            with Session(get_demo_session_manager().get_engine(first_id)) as session:
                rows = export_rows(session, "families")
                content = build_csv_content(rows[:2])
            response = client.post("/data-transfers/import/families/preview",
                                   files={"file": ("families.csv", content, "text/csv")},
                                   headers={"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)})
            token = self._form_token(response, "preview_token")
            first_cookies = dict(client.cookies)
            client.cookies.clear()
            self.assertNotEqual(self._login_admin(client), first_id)
            preview_url = "/data-transfers/?dataset=families&preview=" + token
            self.assertEqual(client.get(preview_url).status_code, 403)
            response = client.post("/data-transfers/import/families/commit", data={"preview_token": token},
                                   headers={"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)})
            self.assertEqual(response.status_code, 403)
            client.cookies.clear()
            client.cookies.update(first_cookies)
            self.assertEqual(client.get(preview_url).status_code, 200)

    def test_settings_keep_global_maintenance_unavailable_in_public_demo(self):
        from csrf import CSRF_COOKIE_NAME
        from restore_control import enabled

        with patch.dict(os.environ, {"HOIKUICT_RESTORE_ENABLED": "1"}), TestClient(main.app, base_url="https://testserver") as client:
            self._login_admin(client)
            self.assertFalse(enabled())
            response = client.get("/settings")
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('href="/settings/backups', response.text)
            self.assertEqual(client.get("/settings/backups/restore").status_code, 404)
            response = client.post("/settings/backups/restore/execute",
                                   headers={"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(client.get("/settings/staff-sessions").status_code, 200)
            self.assertEqual(client.get("/static/js/staff-session-settings.js").status_code, 200)

    def test_http_clients_receive_isolated_demo_sessions(self):
        with TestClient(main.app) as client:
            first_response = client.get("/healthz")
            client.cookies.clear()
            second_response = client.get("/healthz")

            self.assertEqual(first_response.status_code, 200)
            self.assertEqual(second_response.status_code, 200)
            first_id = first_response.headers["X-Demo-Session-Id"]
            second_id = second_response.headers["X-Demo-Session-Id"]
            self.assertNotEqual(first_id, second_id)

            manager = get_demo_session_manager()
            with Session(manager.get_engine(first_id)) as first_session:
                children = first_session.exec(select(Child).order_by(Child.id)).all()
                self.assertEqual(len(children), 100)
                daily_plans = first_session.exec(
                    select(PlanDocumentRow).where(
                        PlanDocumentRow.document_type == DocumentType.DAILY_PLAN.value
                    )
                ).all()
                template = Path(__file__).parent / "demo_data" / "demo-template.sqlite3"
                with sqlite3.connect(template.resolve().as_uri() + "?mode=ro", uri=True) as packaged:
                    expected = packaged.execute(
                        "SELECT COUNT(*) FROM plan_documents WHERE document_type = ?",
                        (DocumentType.DAILY_PLAN.value,),
                    ).fetchone()[0]
                self.assertEqual(len(daily_plans), expected)
                child = children[0]
                self.assertIsNotNone(child)
                child.last_name = "SessionOne"
                first_session.add(child)
                first_session.commit()

            with Session(manager.get_engine(second_id)) as second_session:
                child = second_session.exec(select(Child).order_by(Child.id)).first()
                self.assertIsNotNone(child)
                self.assertNotEqual(child.last_name, "SessionOne")

    def test_monthly_sheets_keep_visitor_data_separate_and_load_versioned_assets(self):
        from csrf import CSRF_COOKIE_NAME

        with TestClient(main.app, base_url="https://testserver") as client:
            first_id = self._login_admin(client)
            manager = get_demo_session_manager()
            with Session(manager.get_engine(first_id)) as session:
                classroom = session.exec(select(Classroom).order_by(Classroom.id)).first()
                classroom_id = classroom.id
            params = {"classroom_id": classroom_id, "target_month": "2026-10", "age": 3}
            response = client.get("/plans/monthly-library/context", params=params)
            self.assertEqual(response.status_code, 200, response.text)
            context = response.json()
            self.assertFalse(context["editable"])
            with Session(manager.get_engine(first_id)) as session:
                admin = session.exec(select(User).where(User.staff_role == "admin")).first()
                session.add(StaffClassroomAssignment(staff_user_id=admin.id, classroom_id=classroom_id,
                    starts_on=date(2026, 10, 1), ends_on=date(2026, 10, 31)))
                session.commit()
            context = client.get("/plans/monthly-library/context", params=params).json()
            self.assertTrue(context["editable"])
            payload = {key: context[key] for key in (
                "document_id", "lock_version", "classroom_id", "target_month", "age", "owner_name", "base_token")}
            payload["fields"] = {"group:food": {"body": "最初の利用者だけの架空月案"}}
            saved = client.post("/plans/monthly-library/save", json=payload,
                                headers={"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)})
            self.assertEqual(saved.status_code, 200, saved.text)
            document_id = saved.json()["document_id"]
            page = client.get("/plans/monthly-library", params={"document_id": document_id})
            self.assertEqual(page.status_code, 200)
            asset = re.search(r'src="(/static/js/monthly-library\.js\?v=[a-f0-9]{16})"', page.text)
            self.assertIsNotNone(asset)
            self.assertIn("主任印", client.get(asset.group(1)).text)
            client.cookies.clear()
            second_id = self._login_admin(client)
            self.assertNotEqual(first_id, second_id)
            with Session(manager.get_engine(second_id)) as session:
                admin = session.exec(select(User).where(User.staff_role == "admin")).first()
                session.add(StaffClassroomAssignment(staff_user_id=admin.id, classroom_id=classroom_id,
                    starts_on=date(2026, 10, 1), ends_on=date(2026, 10, 31)))
                session.commit()
            replay = client.post("/plans/monthly-library/save", json=payload,
                headers={"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)})
            self.assertEqual(replay.status_code, 409)
            context = client.get("/plans/monthly-library/context", params=params).json()
            self.assertIsNone(context["document_id"])
            self.assertEqual(context["sheet"]["fields"], {})
            self.assertEqual(client.get("/plans/monthly-library", params={
                "document_id": document_id}).status_code, 404)
            with Session(manager.get_engine(first_id)) as session:
                self.assertEqual(session.get(PlanDocumentRow, document_id).monthly_sheet["fields"]
                                 ["group:food"]["body"], "最初の利用者だけの架空月案")

    def test_staff_login_renders_from_upgraded_demo_snapshot(self):
        with TestClient(main.app) as client:
            response = client.get("/staff/login?redirect=/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("職員ログイン", response.text)

    def test_annual_weekly_and_reflections_stay_in_their_demo_session(self):
        from csrf import CSRF_COOKIE_NAME
        from test_annual_library import source_fixture

        source_path = self.runtime_dir / "annual-source.json"
        source_path.write_text(json.dumps(source_fixture(), ensure_ascii=False), encoding="utf-8")
        environment = {"HOIKU_NURSERY_REF": "デモ検証園", "HOIKU_ANNUAL_LIBRARY_SOURCES": json.dumps({
            "デモ検証園": [{"id": "fixture", "path": str(source_path)}]})}
        with patch.dict(os.environ, environment), TestClient(main.app, base_url="https://testserver") as client:
            first_id = self._login_admin(client)
            manager = get_demo_session_manager()
            with Session(manager.get_engine(first_id)) as session:
                classroom = session.exec(select(Classroom).order_by(Classroom.id)).first()
                classroom_id = classroom.id
                admin = session.exec(select(User).where(User.staff_role == "admin")).first()
                admin_name = admin.display_name
                teacher = User(email="annual-demo-test@example.invalid", display_name="架空の年案担任")
                session.add(teacher); session.flush()
                for user_id in (teacher.id, admin.id):
                    session.add(StaffClassroomAssignment(staff_user_id=user_id, classroom_id=classroom_id,
                        starts_on=date(2000, 1, 1)))
                session.commit()
            headers = {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}
            params = {"classroom_id": classroom_id, "school_year": 2026, "source_key": "fixture"}
            response = client.get("/plans/annual-library/context", params=params)
            self.assertEqual(response.status_code, 200, response.text)
            boot = response.json()
            self.assertIn("架空の年案担任", boot["owner_name"])
            self.assertNotIn(admin_name, boot["owner_name"])
            payload = {key: boot[key] for key in ("document_id", "lock_version", "classroom_id", "school_year", "owner_name")}
            payload.update(owner_name="手入力した架空担任", origin=boot["sheet"]["origin"], source_digest=boot["sheet"]["source_digest"],
                fields={key: {name: value[name] for name in ("body", "start", "confirmed")} for key, value in boot["sheet"]["fields"].items()})
            saved = client.post("/plans/annual-library/save", json=payload, headers=headers)
            self.assertEqual(saved.status_code, 200, saved.text)
            annual_id = saved.json()["document_id"]
            self.assertEqual(client.get("/plans/annual-library/context", params=params).json()["owner_name"], "手入力した架空担任")
            reflected = client.post(f"/plans/documents/{annual_id}/reflections", headers=headers,
                json={"entries": [{"period": 0, "version": 0, "values": ["この利用者だけの架空反省", "遊びの振り返り"]}]})
            self.assertEqual(reflected.status_code, 200, reflected.text)
            requested = client.post(f"/plans/documents/{annual_id}/reflections/0/request", headers=headers,
                data={"version": reflected.json()["0"]["version"]}, follow_redirects=False)
            self.assertEqual(requested.status_code, 303, requested.text)
            review_url = requested.headers["location"]
            weekly_ids = []
            for age in (0, 3):
                query = {"classroom_id": classroom_id, "month": "2026-10", "age": age}
                response = client.get("/plans/weekly-library/context", params=query)
                self.assertEqual(response.status_code, 200, response.text)
                context = response.json()
                item = {key: context["records"][0][key] for key in ("week_start", "document_id", "lock_version", "sheet", "owner_name")}
                item["sheet"]["aim"] = "この利用者だけの架空週案"
                saved = client.post("/plans/weekly-library/save", json={**query, "items": [item]}, headers=headers)
                self.assertEqual(saved.status_code, 200, saved.text)
                weekly_ids.append(saved.json()["records"][0]["document_id"])
            for kind in ("monthly", "weekly"):
                self.assertEqual(client.get(f"/plans/{kind}-plans/", params=query).status_code, 200)
            client.cookies.clear()
            second_id = self._login_admin(client)
            self.assertNotEqual(first_id, second_id)
            self.assertEqual(client.get("/plans/annual-library", params={"document_id": annual_id}).status_code, 404)
            self.assertEqual(client.get(review_url).status_code, 404)
            for document_id in weekly_ids:
                self.assertEqual(client.get(f"/plans/documents/{document_id}").status_code, 404)
            for age in (0, 3):
                current = client.get("/plans/weekly-library/context", params={**query, "age": age}).json()
                self.assertTrue(all(record["document_id"] is None for record in current["records"]))

    def test_packaged_snapshot_gets_care_certification_demo_data(self):
        with TestClient(main.app) as client:
            response = client.get("/healthz")
            self.assertEqual(response.status_code, 200)
            session_id = response.headers["X-Demo-Session-Id"]

        manager = get_demo_session_manager()
        with Session(manager.get_engine(session_id)) as session:
            certifications = session.exec(select(ChildCareCertification)).all()
            categories = {item.care_time_category for item in certifications}
            rules = session.exec(
                select(ExtendedCareFeeRule).where(ExtendedCareFeeRule.care_time_category.is_not(None))
            ).all()
            setting = session.exec(select(ExtendedCareCalculationSetting)).one()
            self.assertEqual(len(certifications), 100)
            self.assertEqual(categories, {CareTimeCategory.standard, CareTimeCategory.short})
            self.assertEqual(len(rules), 2)
            self.assertEqual(setting.mode, "category_aware")

    def test_database_dependency_uses_request_demo_session(self):
        main.initialize_application()
        session_id = "a" * 32
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
        }
        connection = HTTPConnection(scope)
        connection.state.demo_session_id = session_id
        dependency = get_session(connection)
        session = next(dependency)
        try:
            expected = get_demo_session_manager().get_engine(session_id)
            self.assertIs(session.get_bind(), expected)
        finally:
            dependency.close()

    def test_current_workflows_render_and_reviews_stay_in_their_demo_session(self):
        from csrf import CSRF_COOKIE_NAME
        from routers import document_reviews

        with patch.object(document_reviews, "UPLOAD_ROOT", self.runtime_dir / "review-files"):
            with TestClient(main.app, base_url="https://testserver") as client:
                response = client.get("/staff/login")
                first_id = response.headers["X-Demo-Session-Id"]
                manager = get_demo_session_manager()
                with Session(manager.get_engine(first_id)) as session:
                    admin = session.exec(select(User).where(User.staff_role == "admin")).first()
                    admin_id = str(admin.id)
                headers = {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}
                response = client.post("/staff/login", data={"user_id": admin_id, "redirect_to": "/"}, headers=headers)
                self.assertEqual(response.status_code, 200)
                for path in ("/", "/document-reviews/", "/notices", "/families/", "/parent-accounts", "/staff/users", "/staff-rooms/", "/meeting-notes/", "/data-transfers/", "/extended-care-fees/settings", "/settings/guardian-terminals"):
                    with self.subTest(path=path):
                        response = client.get(path)
                        self.assertEqual(response.status_code, 200)
                        self.assertIn('href="/document-reviews/"', response.text)
                        self.assertNotIn('href="/settings/backups"', response.text)
                        self.assertNotRegex(response.text, r'href="/parent-accounts/[^"?]+/authentication')
                self.assertEqual(client.get("/settings/backups").status_code, 404)
                self.assertEqual(client.post("/settings/backups/create", headers={"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}).status_code, 404)
                headers = {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}
                response = client.post(
                    "/document-reviews/", data={"title": "セッション内の確認依頼", "body": "架空の確認本文"},
                    files={"attachments": ("review.txt", b"isolated attachment", "text/plain")},
                    headers=headers,
                )
                self.assertEqual(response.status_code, 200)
                review_path = response.url.path
                self.assertIn("架空の確認本文", response.text)
                self.assertEqual(client.get(review_path + "/attachments/0").content, b"isolated attachment")
                response = client.post(review_path + "/decision", data={"decision": "approved", "note": "確認完了"}, headers=headers)
                self.assertEqual(response.status_code, 200)
                client.cookies.clear()
                response = client.get("/staff/login")
                second_id = response.headers["X-Demo-Session-Id"]
                self.assertNotEqual(first_id, second_id)
                headers = {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE_NAME)}
                client.post("/staff/login", data={"user_id": admin_id}, headers=headers)
                self.assertEqual(client.get(review_path).status_code, 404)
                self.assertEqual(client.get(review_path + "/attachments/0").status_code, 404)
                with Session(manager.get_engine(second_id)) as session:
                    self.assertEqual(session.exec(select(DocumentReviewRequest)).all(), [])
                with Session(manager.get_engine(first_id)) as session:
                    self.assertEqual(session.exec(select(DocumentReviewRequest)).one().status, "approved")

    def test_packaged_snapshot_supports_all_current_model_columns(self):
        packaged = Path(__file__).parent / "demo_data" / "demo-template.sqlite3"
        original = packaged.read_bytes()
        main.initialize_application()
        with sqlite3.connect(get_demo_session_manager().settings.base_db_path) as snapshot:
            for table_name, table in SQLModel.metadata.tables.items():
                with self.subTest(table=table_name):
                    actual = {row[1] for row in snapshot.execute(f'PRAGMA table_info("{table_name}")')}
                    self.assertTrue({column.name for column in table.columns} <= actual,
                                    f"{table_name}: missing {sorted({column.name for column in table.columns} - actual)}")
            self.assertEqual(snapshot.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(snapshot.execute("PRAGMA foreign_key_check").fetchall(), [])
            indexes = {row[1]: row[2] for row in snapshot.execute("PRAGMA index_list(plan_documents)")}
            for kind in ("monthly", "annual", "weekly"):
                self.assertEqual(indexes[f"uq_{kind}_sheet_key"], 1)
        self.assertEqual(packaged.read_bytes(), original)

    def test_packaged_demo_database_is_migrated_for_review_outcomes(self):
        main.initialize_application()
        base_path = get_demo_session_manager().settings.base_db_path
        connection = sqlite3.connect(base_path)
        try:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(plan_review_notifications)"
                )
            }
        finally:
            connection.close()

        self.assertTrue(
            {
                "notification_kind",
                "decision_status",
                "decided_by_name",
                "decision_comment",
            }.issubset(columns)
        )

    def test_packaged_demo_database_is_upgraded_for_parent_push(self):
        main.initialize_application()
        base_path = get_demo_session_manager().settings.base_db_path
        connection = sqlite3.connect(base_path)
        try:
            delivery_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(parent_notification_deliveries)"
                )
            }
            table_names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            user_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(users)")
            }
            billing_line_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(billing_charge_lines)"
                )
            }
            extended_care_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(extended_care_charges)"
                )
            }
        finally:
            connection.close()

        self.assertTrue(
            {
                "expires_at",
                "targets_resolved_at",
                "planning_lease_expires_at",
                "completed_at",
                "accepted_at",
                "shown_at",
                "clicked_at",
            }.issubset(delivery_columns)
        )
        self.assertTrue(
            {
                "parent_push_subscriptions",
                "parent_push_preferences",
                "parent_push_delivery_targets",
                "parent_push_delivery_attempts",
            }.issubset(table_names)
        )
        self.assertIn("can_manage_billing_accounts", user_columns)
        self.assertIn("source_reference", billing_line_columns)
        self.assertTrue(
            {
                "billing_charge_line_id",
                "transferred_amount",
                "transferred_at",
                "transferred_by_user_id",
                "transferred_by_name",
            }.issubset(extended_care_columns)
        )

    def test_worker_engine_enumeration_does_not_extend_session_ttl(self):
        main.initialize_application()
        manager = get_demo_session_manager()
        session_id = "c" * 32
        manager.ensure_session_database(session_id)
        last_seen = manager.settings.sessions_dir / session_id / ".last_seen"
        before = last_seen.stat().st_mtime_ns

        engines = manager.active_session_engines()

        self.assertIn(session_id, {item[0] for item in engines})
        self.assertEqual(last_seen.stat().st_mtime_ns, before)

    def test_worker_processes_deliveries_inside_each_isolated_session_database(self):
        main.initialize_application()
        manager = get_demo_session_manager()
        session_ids = ("d" * 32, "e" * 32)
        now = datetime.now(timezone.utc)

        for index, session_id in enumerate(session_ids):
            with Session(manager.get_engine(session_id)) as session:
                parent = session.exec(select(ParentAccount).order_by(ParentAccount.id)).first()
                self.assertIsNotNone(parent)
                notification = ParentNotification(
                    parent_account_id=parent.id,
                    kind=ParentNotificationKind.attendance_confirmation_request,
                    title="セッション分離テスト",
                    body="テスト本文",
                    source_type="public_demo_test",
                    source_id=f"session-{index}",
                )
                session.add(notification)
                session.flush()
                session.add(
                    ParentNotificationDelivery(
                        notification_id=notification.id,
                        channel=NotificationDeliveryChannel.push,
                        expires_at=now + timedelta(hours=1),
                    )
                )
                session.add(
                    ParentPushSubscription(
                        parent_account_id=parent.id,
                        endpoint=f"https://push.example.test/demo-session-{index}",
                        endpoint_hash=f"demo-session-hash-{index}",
                        p256dh_key="p256dh",
                        auth_key="auth",
                        environment="production",
                        is_test_device=True,
                    )
                )
                session.commit()

        self.assertEqual(run_parent_push_worker_once(), 2)

        for session_id in session_ids:
            with Session(manager.get_engine(session_id)) as session:
                targets = session.exec(select(ParentPushDeliveryTarget)).all()
                self.assertEqual(len(targets), 1)
                self.assertEqual(
                    targets[0].status,
                    ParentPushDeliveryTargetStatus.accepted,
                )


if __name__ == "__main__":
    unittest.main()
