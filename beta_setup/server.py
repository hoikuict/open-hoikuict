from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import threading
from urllib.parse import urlsplit

from beta_setup.core import Installer, SetupError, installation


def assets_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "beta_setup" / "ui"
    return Path(__file__).parent / "ui"


class SetupServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, installer: Installer, port: int = 0):
        self.installer = installer
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.url = f"{self.origin}/#{self.token}"


class Handler(BaseHTTPRequestHandler):
    server: SetupServer

    def log_message(self, *args) -> None:
        pass  # Never persist authorization headers, request bodies or tokens.

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(8)

    def respond(self, status: int, content: bytes, kind: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def json(self, value: dict, status: int = 200) -> None:
        self.respond(status, json.dumps(value, ensure_ascii=True).encode())

    def host_valid(self) -> bool:
        return self.headers.get("Host") == urlsplit(self.server.origin).netloc

    def authorized(self, *, mutation: bool = False) -> bool:
        supplied = self.headers.get("Authorization", "")
        if not self.host_valid() or not hmac.compare_digest(supplied, f"Bearer {self.server.token}"):
            self.json({"ok": False, "message": "導入アプリのアイコンから画面を開き直してください。"}, 403)
            return False
        origin = self.headers.get("Origin")
        if (mutation and origin != self.server.origin) or (origin and origin != self.server.origin):
            self.json({"ok": False, "message": "この接続元からは操作できません。"}, 403)
            return False
        return True

    def do_GET(self) -> None:
        if not self.host_valid():
            self.json({"ok": False}, 403)
            return
        path = urlsplit(self.path).path
        if path.startswith("/api/"):
            if not self.authorized():
                return
            if path == "/api/info":
                previous = None
                problem = ""
                try:
                    previous = installation(self.server.installer.home)
                except SetupError as exc:
                    problem = str(exc)
                self.json({"ok": True, "path": str(self.server.installer.home),
                           "platform": sys.platform, "existing": previous,
                           "online": self.server.installer.online,
                           "problem": problem, "status": self.server.installer.snapshot()})
            elif path == "/api/status":
                self.json({"ok": True, **self.server.installer.snapshot()})
            elif path == "/api/release":
                try:
                    self.json({"ok": True, **self.server.installer.check_release()})
                except SetupError as exc:
                    self.json({"ok": False, "message": str(exc), "code": exc.code}, 409)
                except Exception:
                    self.json({"ok": False, "message": "配布情報を確認できませんでした。時間を置いて再試行してください。", "code": "release_invalid"}, 502)
            else:
                self.json({"ok": False}, 404)
            return
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/style.css": ("style.css", "text/css; charset=utf-8"),
                 "/wizard.js": ("wizard.js", "text/javascript; charset=utf-8")}
        if path not in files:
            self.json({"ok": False}, 404)
            return
        name, kind = files[path]
        self.respond(200, (assets_path() / name).read_bytes(), kind)

    def do_POST(self) -> None:
        if not self.authorized(mutation=True):
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json" or self.headers.get("Transfer-Encoding"):
            self.json({"ok": False, "message": "送信形式が不正です。"}, 400)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise ValueError
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, UnicodeError, TimeoutError):
            self.json({"ok": False, "message": "入力を確認してください。"}, 400)
            return
        manager = self.server.installer
        path = urlsplit(self.path).path
        try:
            if path == "/api/preflight":
                self.json({"ok": True, **manager.preflight(payload)})
            elif path == "/api/install":
                manager.begin(payload)
                self.json({"ok": True}, 202)
            elif path == "/api/cancel":
                manager.cancel.set()
                self.json({"ok": True})
            elif path == "/api/launch":
                self.json({"ok": True, **manager.launch(payload)})
            elif path == "/api/stop":
                with manager.guard:
                    if manager.thread and manager.thread.is_alive():
                        raise SetupError("準備中です。中断ボタンを使ってください。", "busy")
                    manager.app.stop()
                self.json({"ok": True})
            elif path == "/api/exit":
                manager.cancel.set()
                self.json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.json({"ok": False}, 404)
        except SetupError as exc:
            self.json({"ok": False, "message": str(exc), "code": exc.code}, 409)
        except Exception:
            self.json({"ok": False, "message": "操作を完了できませんでした。保存先とアプリの状態を確認してください。"}, 500)

    def do_OPTIONS(self) -> None:
        self.json({"ok": False}, 403)
