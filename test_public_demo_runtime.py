import os
import shutil
import time
import unittest
from pathlib import Path

from sqlmodel import Session, select

from database import initialize_demo_template_database
from demo_runtime import DemoSessionManager, DemoSettings
from models import Child


class PublicDemoRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime_dir = Path(os.getcwd()) / f"_demo_runtime_test_{time.time_ns()}"
        self.runtime_dir.mkdir()
        self.settings = DemoSettings(
            enabled=True,
            runtime_dir=self.runtime_dir,
            base_db_path=self.runtime_dir / "demo-template.sqlite3",
            sessions_dir=self.runtime_dir / "sessions",
            session_ttl_seconds=1,
            session_input_limit_bytes=1024,
            max_request_body_bytes=512,
            secure_cookies=False,
            cleanup_interval_seconds=1,
        )
        self.manager = DemoSessionManager(self.settings)
        self.manager.prepare_base_database(initialize_demo_template_database)

    def tearDown(self):
        self.manager.close()
        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    def test_session_databases_are_isolated(self):
        first_engine = self.manager.get_engine("a" * 32)
        second_engine = self.manager.get_engine("b" * 32)

        with Session(first_engine) as session:
            child = session.exec(select(Child).order_by(Child.id)).first()
            self.assertIsNotNone(child)
            child.last_name = "SessionA"
            session.add(child)
            session.commit()

        with Session(second_engine) as session:
            untouched_child = session.exec(select(Child).order_by(Child.id)).first()

        self.assertIsNotNone(untouched_child)
        self.assertNotEqual(untouched_child.last_name, "SessionA")

    def test_input_budget_is_tracked_per_session(self):
        session_id = "c" * 32

        allowed, used = self.manager.reserve_input_budget(session_id, 400)
        self.assertTrue(allowed)
        self.assertEqual(used, 400)

        allowed, used = self.manager.reserve_input_budget(session_id, 500)
        self.assertTrue(allowed)
        self.assertEqual(used, 900)

        allowed, used = self.manager.reserve_input_budget(session_id, 200)
        self.assertFalse(allowed)
        self.assertEqual(used, 900)
        self.assertEqual(self.manager.get_input_usage(session_id), 900)

    def test_cleanup_removes_expired_sessions(self):
        session_id = "d" * 32
        self.manager.ensure_session_database(session_id)

        touch_path = self.settings.sessions_dir / session_id / ".last_seen"
        expired_at = time.time() - 10
        os.utime(touch_path, (expired_at, expired_at))

        self.manager.cleanup_expired_sessions(force=True)

        self.assertFalse((self.settings.sessions_dir / session_id).exists())


if __name__ == "__main__":
    unittest.main()
