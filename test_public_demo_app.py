import os
import shutil
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import main
from demo_runtime import get_demo_session_manager, reset_demo_runtime_cache


class PublicDemoAppTests(unittest.TestCase):
    def setUp(self):
        self.runtime_dir = Path(os.getcwd()) / f"_demo_runtime_app_test_{time.time_ns()}"
        self.runtime_dir.mkdir()
        self._original_env = {
            "PUBLIC_DEMO_MODE": os.environ.get("PUBLIC_DEMO_MODE"),
            "DEMO_RUNTIME_DIR": os.environ.get("DEMO_RUNTIME_DIR"),
            "DEMO_SECURE_COOKIES": os.environ.get("DEMO_SECURE_COOKIES"),
            "DEMO_SESSION_TTL_MINUTES": os.environ.get("DEMO_SESSION_TTL_MINUTES"),
            "DEMO_SESSION_INPUT_LIMIT_BYTES": os.environ.get("DEMO_SESSION_INPUT_LIMIT_BYTES"),
            "DEMO_MAX_REQUEST_BODY_BYTES": os.environ.get("DEMO_MAX_REQUEST_BODY_BYTES"),
        }
        os.environ["PUBLIC_DEMO_MODE"] = "1"
        os.environ["DEMO_RUNTIME_DIR"] = str(self.runtime_dir)
        os.environ["DEMO_SECURE_COOKIES"] = "1"
        os.environ["DEMO_SESSION_TTL_MINUTES"] = "120"
        os.environ["DEMO_SESSION_INPUT_LIMIT_BYTES"] = "65536"
        os.environ["DEMO_MAX_REQUEST_BODY_BYTES"] = "16384"
        reset_demo_runtime_cache()

    def tearDown(self):
        try:
            get_demo_session_manager().close()
        except Exception:
            pass
        reset_demo_runtime_cache()

        for key, value in self._original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

        shutil.rmtree(self.runtime_dir, ignore_errors=True)

    @staticmethod
    def _child_form_data() -> dict[str, str]:
        return {
            "last_name": "Demo",
            "first_name": "Kid",
            "last_name_kana": "DEMO",
            "first_name_kana": "KID",
            "birth_date": "2021-01-01",
            "enrollment_date": "2024-04-01",
            "withdrawal_date": "",
            "status": "enrolled",
            "classroom_id": "",
            "allergy": "",
            "medical_notes": "",
            "family_selection": "new",
            "family_name": "Demo Family",
            "home_address": "",
            "home_phone": "",
            "g1_last_name": "",
            "g1_first_name": "",
            "g1_last_name_kana": "",
            "g1_first_name_kana": "",
            "g1_relationship": "母",
            "g1_phone": "",
            "g1_workplace": "",
            "g1_workplace_address": "",
            "g1_workplace_phone": "",
            "g2_last_name": "",
            "g2_first_name": "",
            "g2_last_name_kana": "",
            "g2_first_name_kana": "",
            "g2_relationship": "父",
            "g2_phone": "",
            "g2_workplace": "",
            "g2_workplace_address": "",
            "g2_workplace_phone": "",
        }

    def test_http_preview_keeps_same_demo_session_after_create(self):
        with TestClient(main.app) as client:
            form_response = client.get("/children/new")

            self.assertEqual(form_response.status_code, 200)
            self.assertIn("demo_session_id=", form_response.headers.get("set-cookie", ""))
            self.assertNotIn("Secure", form_response.headers.get("set-cookie", ""))

            initial_session_id = client.cookies.get("demo_session_id")
            self.assertIsNotNone(initial_session_id)

            create_response = client.post("/children/", data=self._child_form_data(), follow_redirects=True)

            self.assertEqual(create_response.status_code, 200)
            self.assertEqual(client.cookies.get("demo_session_id"), initial_session_id)
            self.assertIn("Demo", create_response.text)
            self.assertIn("Kid", create_response.text)

    def test_forwarded_https_requests_keep_secure_cookie(self):
        with TestClient(main.app) as client:
            response = client.get("/children/new", headers={"x-forwarded-proto": "https"})

            self.assertEqual(response.status_code, 200)
            self.assertIn("Secure", response.headers.get("set-cookie", ""))

    def test_meeting_note_websocket_uses_same_demo_session_database(self):
        with TestClient(main.app) as client:
            list_response = client.get("/meeting-notes/")
            self.assertEqual(list_response.status_code, 200)
            self.assertIsNotNone(client.cookies.get("demo_session_id"))

            create_response = client.post("/meeting-notes/", data={"title": "Demo Note"}, follow_redirects=False)
            self.assertEqual(create_response.status_code, 303)

            note_path = create_response.headers["location"]
            note_id = int(note_path.rsplit("/", 1)[-1])

            with client.websocket_connect(f"/meeting-notes/ws/{note_id}") as websocket:
                websocket.send_bytes(b"\x00demo")

    def test_meeting_note_websocket_accepts_demo_session_id_query_param(self):
        with TestClient(main.app) as client:
            client.get("/meeting-notes/")
            session_id = client.cookies.get("demo_session_id")
            self.assertIsNotNone(session_id)

            create_response = client.post("/meeting-notes/", data={"title": "Demo Note"}, follow_redirects=False)
            self.assertEqual(create_response.status_code, 303)
            note_id = int(create_response.headers["location"].rsplit("/", 1)[-1])

            client.cookies.clear()
            with client.websocket_connect(f"/meeting-notes/ws/{note_id}?demo_session_id={session_id}") as websocket:
                websocket.send_bytes(b"\x00demo")

    def test_demo_session_starts_with_default_meeting_note(self):
        with TestClient(main.app) as client:
            response = client.get("/meeting-notes/1")

            self.assertEqual(response.status_code, 200)
            self.assertIn("議事録", response.text)


if __name__ == "__main__":
    unittest.main()
