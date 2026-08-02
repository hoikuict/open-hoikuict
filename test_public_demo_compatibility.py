import os
import shutil
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

import main
from auth import mock_auth_enabled
from database import get_session
from demo_runtime import get_demo_session_manager, reset_demo_runtime_cache
from models import Child
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
            )
        }
        os.environ["PUBLIC_DEMO_MODE"] = "1"
        os.environ["DEMO_RUNTIME_DIR"] = str(self.runtime_dir)
        os.environ["DEMO_SECURE_COOKIES"] = "0"
        os.environ["HOIKUICT_ENV"] = "production"
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
                child = children[0]
                self.assertIsNotNone(child)
                child.last_name = "SessionOne"
                first_session.add(child)
                first_session.commit()

            with Session(manager.get_engine(second_id)) as second_session:
                child = second_session.exec(select(Child).order_by(Child.id)).first()
                self.assertIsNotNone(child)
                self.assertNotEqual(child.last_name, "SessionOne")

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


if __name__ == "__main__":
    unittest.main()
