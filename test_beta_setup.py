"""Installer boundaries; these tests never import the business application."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from beta_setup.core import (
    Cancelled, FileLock, Installer, SetupError, clean_environment,
    extract_bundle, make_config, normalize, sha256,
)
from beta_setup.server import SetupServer
from scripts.build_beta_bundle import selected


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.target = self.root / "installation"
        self.manager = Installer(self.bundle, self.target)

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def values(self):
        return dict(path=str(self.target), port="18081", name="試用管理者",
                    email="trial@example.test", password="sample four words 123",
                    confirm="sample four words 123")

    def package(self, files):
        archive = self.bundle / "payload.zip"
        with zipfile.ZipFile(archive, "w") as stream:
            for name, value in files.items():
                stream.writestr(name, value)
        manifest = dict(format=1, platform=sys.platform, source_commit="test",
                        archive_sha256=sha256(archive),
                        files={k: hashlib.sha256(v).hexdigest() for k, v in files.items()})
        (self.bundle / "bundle.json").write_text(json.dumps(manifest))
        return manifest

    def test_existing_directory_is_never_overwritten(self):
        self.target.mkdir()
        sentinel = self.target / "data.txt"
        sentinel.write_text("keep")
        with self.assertRaises(SetupError) as error:
            self.manager.begin(self.values())
        self.assertEqual(error.exception.code, "existing_files")
        self.assertEqual(sentinel.read_text(), "keep")

    def test_defaults_and_invalid_paths(self):
        data = normalize(self.values())
        self.assertEqual(data["login"], data["email"])
        self.assertEqual(data["actor"], data["name"])
        self.assertEqual(data["approver"], data["name"])
        for path in ("relative", str(self.target / ".." / "elsewhere"), self.target.anchor):
            with self.subTest(path=path), self.assertRaises(SetupError):
                normalize({**self.values(), "path": path})

    def test_inherited_app_settings_are_removed_and_dotenv_stops_here(self):
        with patch.dict(os.environ, {"HOIKUICT_DATABASE_URL": "real-db", "PYTHONPATH": "real-app",
                                    "HOIKU_DATA_DIR": "real-data", "VIRTUAL_ENV": "real-venv"}):
            environment = clean_environment()
        self.assertNotIn("HOIKUICT_DATABASE_URL", environment)
        self.assertNotIn("HOIKU_DATA_DIR", environment)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("VIRTUAL_ENV", environment)
        make_config(self.root / ".env.beta.local", 18081)
        self.assertTrue((self.root / ".env").is_file())
        settings = dict(line.split("=", 1) for line in (self.root / ".env.beta.local").read_text().splitlines())
        self.assertEqual(settings["HOIKUICT_PARENT_MAIL_TRANSPORT"], "capture")
        self.assertNotEqual(settings["HOIKUICT_SECRET_KEY"], settings["HOIKUICT_LOGIN_THROTTLE_HMAC_KEY"])

    def test_invalid_archive_paths_and_tampering_are_rejected(self):
        for name in ("app/../../escape", "runtime/../escape", "app/C:/escape", "elsewhere/a"):
            with self.subTest(name=name):
                self.package({name: b"bad"})
                with self.assertRaises(SetupError):
                    extract_bundle(self.bundle, self.target, threading.Event())
        self.package({"app/main.py": b"data"})
        with (self.bundle / "payload.zip").open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaises(SetupError):
            extract_bundle(self.bundle, self.target, threading.Event())
        self.assertFalse((self.root / "escape").exists())

    def test_cancel_rolls_back_only_owned_staging_directory(self):
        self.package({"app/main.py": b"data"})
        sibling = self.root / ".installation.setup-existing"
        sibling.mkdir()
        (sibling / "keep").write_text("keep")
        with patch("beta_setup.core.extract_bundle", side_effect=Cancelled):
            self.manager.begin(self.values())
            self.manager.thread.join(10)
        self.assertEqual(self.manager.snapshot()["state"], "cancelled")
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob(".installation.setup-*")), [sibling])

    def test_lock_excludes_second_process_owner(self):
        first, second = FileLock(self.root / "lock"), FileLock(self.root / "lock")
        first.acquire()
        try:
            with self.assertRaises(SetupError):
                second.acquire()
        finally:
            first.close()
        second.acquire()
        second.close()

    def test_payload_selection_excludes_workstation_data(self):
        for name in (".env", "hoikuict.db", "data/facility.sqlite", "storage/upload.pdf",
                     ".local-dev/secret.py", "test_staff_auth.py", "tests/test_other.py"):
            with self.subTest(name=name):
                self.assertFalse(selected(name))
        self.assertTrue(selected("main.py"))
        self.assertTrue(selected("templates/staff_auth/login_password.html"))
        self.assertTrue(selected("gen_bunnrei/bunrei.sqlite"))

    def test_controller_requires_token_host_and_origin(self):
        server = SetupServer(self.manager)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(method, path, headers):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            conn.request(method, path, body="{}" if method == "POST" else None, headers=headers)
            response = conn.getresponse()
            status, body = response.status, response.read()
            conn.close()
            return status, body
        try:
            auth = {"Authorization": f"Bearer {server.token}"}
            self.assertEqual(request("GET", "/api/info", {})[0], 403)
            self.assertEqual(request("GET", "/api/info", auth)[0], 200)
            self.assertEqual(request("GET", "/", {"Host": "attacker.invalid"})[0], 403)
            post = {**auth, "Content-Type": "application/json"}
            self.assertEqual(request("POST", "/api/cancel", post)[0], 403)
            self.assertEqual(request("POST", "/api/cancel", {**post, "Origin": "http://attacker.invalid"})[0], 403)
            self.assertFalse(self.manager.cancel.is_set())
            self.assertEqual(request("POST", "/api/cancel", {**post, "Origin": server.origin})[0], 200)
            self.assertTrue(self.manager.cancel.is_set())
            body = request("GET", "/api/status", auth)[1]
            self.assertNotIn(b"password", body)
            self.assertNotIn(server.token.encode(), body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)


if __name__ == "__main__":
    unittest.main()
