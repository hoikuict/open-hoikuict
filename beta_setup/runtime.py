"""Run with the bundled interpreter in a fresh application directory.

Private input travels over stdin, never command line arguments or log files.
The application must not be imported before configuring its environment.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time


def configure() -> None:
    root = Path(__file__).resolve().parent
    os.chdir(root)
    sys.path.insert(0, str(root))
    for key in list(os.environ):
        if key.startswith(("HOIKUICT_", "HOIKU_")) or key == "FORWARDED_ALLOW_IPS":
            os.environ.pop(key, None)
    from dotenv import dotenv_values

    settings = dotenv_values(root / ".env.beta.local")
    required = {
        "HOIKUICT_ENV": "development",
        "HOIKUICT_ENABLE_MOCK_AUTH": "0",
        "HOIKUICT_STAFF_AUTH_MODE": "local_password",
        "HOIKUICT_PARENT_AUTH_MODE": "local_password",
        "HOIKUICT_DATABASE_URL": "sqlite:///./hoikuict-beta-auth.db",
        "HOIKUICT_PARENT_MAIL_TRANSPORT": "capture",
        "HOIKUICT_KIOSK_ACCESS_MODE": "disabled",
        "HOIKUICT_PUSH_TRANSPORT": "disabled",
        "HOIKUICT_CSRF_ENFORCE": "1",
        "HOIKUICT_COOKIE_SECURE": "0",
    }
    if any(settings.get(k) != v for k, v in required.items()):
        raise ValueError("unsupported_configuration")
    os.environ.update({k: v for k, v in settings.items() if v is not None})
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def initialize(values: dict) -> None:
    from local_auth import (
        PasswordPolicyError, activate_staff_password, bootstrap_admin,
        validate_new_password,
    )
    from database import engine
    from sqlmodel import Session
    from main import initialize_application

    try:
        validate_new_password(values["password"], login_id=values["login"],
                              email=values["email"], display_name=values["name"])
    except PasswordPolicyError as exc:
        # These are fixed policy messages, not the supplied password.
        print(json.dumps({"ok": False, "code": "password_policy", "message": str(exc)}, ensure_ascii=True), flush=True)
        return
    initialize_application()
    try:
        with Session(engine) as session:
            _, code = bootstrap_admin(
                session, display_name=values["name"], email=values["email"],
                login_id=values["login"], reason=values["reason"],
                actor=values["actor"], approver=values["approver"],
            )
            activate_staff_password(session, activation_code=code,
                                    login_id=values["login"], password=values["password"],
                                    password_confirmation=values["confirm"])
        print(json.dumps({"ok": True}), flush=True)
    finally:
        engine.dispose()


def run_app(values: dict) -> None:
    import socket
    import uvicorn
    from main import app
    from database import engine

    # Bind in the owned process before reporting readiness. A different service's
    # /healthz response must never be mistaken for this application.
    sock = socket.socket()
    if os.name == "nt":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    sock.bind(("127.0.0.1", int(values["port"])))
    sock.listen(128)
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=int(values["port"]),
        access_log=False, log_level="error", proxy_headers=False,
        ws="websockets", loop="asyncio", http="h11",
        timeout_graceful_shutdown=10,
    ))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]})
    thread.start()
    try:
        deadline = time.monotonic() + 90
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("startup_failed")
            time.sleep(.05)
        print(json.dumps({"ok": True, "ready": True}), flush=True)
        # STOP or EOF stops only this owned process, including on launcher exit.
        sys.stdin.readline()
    finally:
        server.should_exit = True
        thread.join(15)
        sock.close()
        engine.dispose()


def main() -> int:
    try:
        raw = sys.stdin.buffer.readline(32769)
        if len(raw) > 32768:
            raise ValueError("input_too_large")
        values = json.loads(raw)
        configure()
        if sys.argv[1:] == ["initialize"]:
            initialize(values)
        elif sys.argv[1:] == ["run"]:
            run_app(values)
        else:
            raise ValueError("invalid_mode")
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "code": type(exc).__name__}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
