import os
import sqlite3
import shutil
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

import main
from auth import mock_auth_enabled
from database import get_session
from demo_runtime import get_demo_session_manager, reset_demo_runtime_cache
from models import (
    Child,
    NotificationDeliveryChannel,
    ParentAccount,
    ParentNotification,
    ParentNotificationDelivery,
    ParentNotificationKind,
    ParentPushDeliveryTarget,
    ParentPushDeliveryTargetStatus,
    ParentPushSubscription,
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
                self.assertEqual(len(daily_plans), 6)
                child = children[0]
                self.assertIsNotNone(child)
                child.last_name = "SessionOne"
                first_session.add(child)
                first_session.commit()

            with Session(manager.get_engine(second_id)) as second_session:
                child = second_session.exec(select(Child).order_by(Child.id)).first()
                self.assertIsNotNone(child)
                self.assertNotEqual(child.last_name, "SessionOne")

    def test_staff_login_renders_from_upgraded_demo_snapshot(self):
        with TestClient(main.app) as client:
            response = client.get("/staff/login?redirect=/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("職員ログイン", response.text)

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
