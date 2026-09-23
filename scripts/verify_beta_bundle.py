"""Opt-in real executable smoke test, always in a new UUID-named workspace.

Creates only fictional records. Does not print or persist the test password.
"""
from __future__ import annotations

import argparse
import hashlib
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sqlite3
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor
import uuid


class Controller:
    def __init__(self, executable: Path, home: Path, *, bundle: Path | None = None):
        self.home = home
        self.process = subprocess.Popen(
            [str(executable), "--no-browser", "--home", str(home), *(["--bundle", str(bundle)] if bundle else [])],
            cwd=executable.parent, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.session_file = home.parent / f".{home.name}.launcher/session.json"
        deadline = time.monotonic() + 40
        while not self.session_file.exists():
            assert self.process.poll() is None, "Launcher exited early"
            assert time.monotonic() < deadline, "Launcher startup timed out"
            time.sleep(.1)
        data = json.loads(self.session_file.read_text(encoding="utf-8"))
        parsed = urlsplit(data["url"])
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.token = parsed.fragment
        self.http = build_opener()

    def call(self, name, values=None):
        headers = {"Authorization": f"Bearer {self.token}"}
        data = None
        if values is not None:
            headers.update({"Origin": self.origin, "Content-Type": "application/json"})
            data = json.dumps(values).encode()
        with self.http.open(Request(self.origin + "/api/" + name, data=data, headers=headers), timeout=120) as response:
            return json.load(response)

    def install(self, values):
        if self.call("info").get("online"):
            values = {**values, "release_revision": self.call("release")["revision"]}
        self.call("install", values)
        deadline = time.monotonic() + 600
        last = None
        while time.monotonic() < deadline:
            status = self.call("status")
            step = status["state"], status["progress"]
            if step != last:
                print(json.dumps({"state": step[0], "progress": step[1]}, ensure_ascii=True), flush=True)
                last = step
            if status["state"] != "installing":
                # Cleanup is completed before another install can start.
                while list(self.home.parent.glob(f".{self.home.name}.setup-*")):
                    assert time.monotonic() < deadline, "Rollback timed out"
                    time.sleep(.1)
                return status
            time.sleep(.3)
        raise AssertionError("Installation timed out")

    def close(self):
        if self.process.poll() is None:
            self.call("exit", {})
            self.process.wait(timeout=40)
        assert self.process.returncode == 0
        assert not self.session_file.exists()


def login(base, login_id, password):
    jar = CookieJar()
    http = build_opener(HTTPCookieProcessor(jar))
    with http.open(base + "/staff/login", timeout=20) as response:
        page = response.read().decode()
    token = re.search(r'name="csrf_token" value="([^"]+)"', page)[1]
    fields = dict(login_id=login_id, password=password, csrf_token=token, redirect_to="/classrooms/")
    with http.open(Request(base + "/staff/login", data=urlencode(fields).encode(),
                           headers={"Origin": base}), timeout=20) as response:
        assert urlsplit(response.url).path == "/classrooms/", "Login failed"
    return http


def audit_database(home, password=""):
    with sqlite3.connect(Path(home) / "app/hoikuict-beta-auth.db") as db:
        assert db.execute("select count(*) from users").fetchone()[0] == 1
        assert db.execute("select count(*) from initial_admin_bootstrap_audits").fetchone()[0] == 1
        assert db.execute("select count(*) from children").fetchone()[0] == 0
        assert db.execute("select count(*) from families").fetchone()[0] == 0
        stored = db.execute("select password_hash from password_credentials").fetchone()[0]
        assert stored.startswith("$argon2") and (not password or password not in stored)
        assert db.execute("select count(*) from credential_action_tokens where consumed_at is null").fetchone()[0] == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--skip-weak-password", action="store_true",
                        help="Skip the separately verified rollback case")
    parser.add_argument("--online", action="store_true", help="Download the published GitHub release through the actual executable")
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    home = workspace / ("validation-" + uuid.uuid4().hex)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    executable = "OpenHoikuICT.exe" if os.name == "nt" else "OpenHoikuICT"
    password = secrets.token_urlsafe(24)
    values = dict(path=str(home), port=str(port), name="架空の試用管理者", email="trial@example.test",
                  password="password", confirm="password")
    controller = Controller(bundle / executable, home, bundle=None if args.online else bundle)
    try:
        assert not controller.call("info")["existing"]
        assert not controller.call("preflight", values)["existing"]
        if not args.skip_weak_password:
            failed = controller.install(values)
            assert failed["state"] == "error" and failed["code"] == "password_policy", failed
            assert not home.exists(), "Failed installation was committed"
            print("Weak password rejected; staging rolled back", flush=True)
        values.update(password=password, confirm=password)
        status = controller.install(values)
        assert status["state"] == "complete", status
        values.clear()
        config = home / "app/.env.beta.local"
        config_hash = hashlib.sha256(config.read_bytes()).hexdigest()
        assert b"HOIKUICT_PARENT_MAIL_TRANSPORT=capture" in config.read_bytes()
        marker = home / "installation.json"
        marker_hash = hashlib.sha256(marker.read_bytes()).hexdigest()
        try:
            controller.call("install", dict(path=str(home), port=str(port), name="Other", email="other@example.test",
                                            password=password, confirm=password))
        except HTTPError as error:
            assert error.code == 409
        else:
            raise AssertionError("Existing installation was not protected")
        assert hashlib.sha256(marker.read_bytes()).hexdigest() == marker_hash
        launched = controller.call("launch", {})
        base = launched["url"].removesuffix("/staff/login")
        http = login(base, "trial@example.test", password)
        with http.open(base + "/healthz", timeout=20) as response:
            assert json.load(response)["status"] == "ok"
        with http.open(base + "/initial-ledger/", timeout=20) as response:
            assert "初期台帳" in response.read().decode(), "Initial ledger feature missing"
        with http.open(base + "/parent-accounts/", timeout=20) as response:
            assert response.status == 200, "Parent accounts feature unavailable"
        with http.open(base + "/classrooms/new", timeout=20) as response:
            page = response.read().decode()
        # The shared page script normally copies this meta value into forms.
        token = re.search(r'name="csrf-token" content="([^"]+)"', page)[1]
        record = "試用確認クラス"
        with http.open(Request(base + "/classrooms/", data=urlencode(dict(name=record, display_order=1, csrf_token=token)).encode(),
                               headers={"Origin": base}), timeout=20) as response:
            assert record in response.read().decode()
        controller.call("stop", {})
        assert not controller.call("status")["running"]
        print("Real login, health check, record creation and stop passed", flush=True)
    finally:
        controller.close()

    # Reopen the copied launcher using only the installed folder.
    controller = Controller(home / executable, home)
    try:
        assert controller.call("info")["existing"]["login"] == "trial@example.test"
        base = controller.call("launch", {})["url"].removesuffix("/staff/login")
        http = login(base, "trial@example.test", password)
        with http.open(base + "/classrooms/", timeout=20) as response:
            assert record in response.read().decode()
        controller.call("stop", {})
    finally:
        controller.close()
    assert hashlib.sha256(config.read_bytes()).hexdigest() == config_hash
    audit_database(home, password)
    print(json.dumps({"passed": True, "installation": str(home), "weak_password_checked": not args.skip_weak_password, "checks": [
        "no overwrite", "real login", "healthz", "record save",
        "installed launcher restart", "data persisted", "keys unchanged", "hashed credential",
        "bootstrap audit", "no demo children or families", "controller exit",
        "initial ledger available", "parent account list available",
    ]}), flush=True)


if __name__ == "__main__":
    main()
