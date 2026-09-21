"""Synthetic end-to-end drill; no production paths or external delivery configuration.

Run in a disposable container with --network none, or an unused local port 8001.
Exercises the real app process, gateway, backup worker and restore worker together.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time


def wait_for(predicate, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    raise AssertionError("Synthetic restore drill timed out")


def main():
    with tempfile.TemporaryDirectory(prefix="hoikuict-restore-drill-") as temporary:
        root = Path(temporary).resolve()
        for name in ("data", "storage", "backups", "staging", "control"):
            (root / name).mkdir()
        (root / "key").write_bytes(os.urandom(32))
        os.environ.update({
            "HOIKUICT_ENV": "test", "HOIKUICT_DATABASE_URL": "sqlite:///" + (root / "data/hoikuict.db").as_posix(),
            "HOIKU_FACILITY_BUNREI_DB_PATH": str(root / "data/facility.sqlite"),
            "HOIKUICT_STORAGE_ROOT": str(root / "storage"), "HOIKUICT_PREVIEW_DIR": str(root / "data/previews"),
            "HOIKUICT_RESTORE_ENABLED": "1", "HOIKUICT_RESTORE_CONTROL_DIR": str(root / "control"),
            "HOIKUICT_RESTORE_STAGING_ROOT": str(root / "staging"), "HOIKUICT_RESTORE_BACKUP_ROOT": str(root / "backups"),
            "HOIKUICT_RESTORE_SIGNING_KEY_FILE": str(root / "key"),
            "HOIKUICT_RESTORE_COMPATIBLE_GIT_SHAS": "a" * 40 + "," + "b" * 40,
            "HOIKUICT_BACKUP_GIT_SHA": "b" * 40, "HOIKUICT_BACKUP_APP_IMAGE": "synthetic-drill",
            "HOIKUICT_BACKUP_COMPOSE_SHA256": "c" * 64, "HOIKU_NURSERY_REF": "synthetic-drill",
            "HOIKUICT_BACKUP_CONTROL_DIR": str(root / "data/backup-control"),
            "HOIKUICT_BACKUP_OUTPUT_ROOT": str(root / "backups"),
            "HOIKUICT_COOKIE_SECURE": "0", "HOIKUICT_CSRF_ENFORCE": "1",
            "HOIKUICT_STAFF_AUTH_MODE": "local_password", "HOIKUICT_PARENT_AUTH_MODE": "local_password",
            "HOIKUICT_ENABLE_MOCK_AUTH": "0", "HOIKUICT_ENABLE_MOCK_ROLE_OVERRIDE": "0",
            "HOIKUICT_KIOSK_ACCESS_MODE": "disabled", "HOIKUICT_PUSH_TRANSPORT": "disabled",
            "HOIKUICT_PARENT_MAIL_TRANSPORT": "disabled", "HOIKUICT_STAFF_MAIL_TRANSPORT": "disabled",
            "HOIKUICT_ALLOWED_ORIGINS": "http://testserver", "FORWARDED_ALLOW_IPS": "127.0.0.1",
            "HOIKUICT_SECRET_KEY": "synthetic-only-" + "s" * 40,
            "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY": "synthetic-only-" + "t" * 40,
        })
        # All application imports happen after fixing the isolated paths.
        from main import initialize_application
        from database import engine
        from sqlmodel import Session
        from models import Child, MeetingNote, PasswordCredential, User
        from local_auth import hash_password
        from scripts.backup_runtime import BackupConfig, create_backup
        from scripts.restore_gateway import Supervisor, create_gateway
        from fastapi.testclient import TestClient
        from restore_control import read_job, service_state, viewer_cookie
        initialize_application()
        password = "Synthetic-Restore-7301!"
        with Session(engine) as session:
            actor = User(email="drill@example.invalid", display_name="架空の管理者", staff_role="admin", is_active=True)
            session.add(actor)
            session.commit()
            session.refresh(actor)
            session.add(PasswordCredential(principal_type="staff", staff_user_id=actor.id,
                                          login_id=actor.email, login_id_normalized=actor.email,
                                          password_hash=hash_password(password), must_change_password=False))
            session.add(Child(last_name="架空", first_name="園児", last_name_kana="カクウ", first_name_kana="エンジ",
                              birth_date=date(2024, 1, 1), enrollment_date=date(2026, 4, 1)))
            session.add(MeetingNote(id=1, title="架空の議事録"))
            session.commit()
        engine.dispose()
        # Bootstrap normalization must precede the source snapshot, as in production.
        initialize_application()
        engine.dispose()
        (root / "storage/example.txt").write_text("saved synthetic attachment")
        backup = create_backup(BackupConfig(output_root=root / "backups", database_url=os.environ["HOIKUICT_DATABASE_URL"],
                                           facility_db=root / "data/facility.sqlite", storage_root=root / "storage",
                                           git_sha="a" * 40, app_image="synthetic-drill", compose_sha256="c" * 64,
                                           facility_ref="synthetic-drill", quiesced=True))
        (root / "storage/after.txt").write_text("created after backup")
        with closing(sqlite3.connect(root / "data/hoikuict.db")) as db:
            db.execute("UPDATE users SET display_name='変更後の管理者' WHERE email='drill@example.invalid'")
            db.commit()
        processes = []
        supervisor = Supervisor()
        try:
            with (root / "worker.log").open("w", encoding="utf-8") as logs:
                for module in ("scripts.backup_worker", "scripts.restore_worker"):
                    processes.append(subprocess.Popen([sys.executable, "-m", module], stdout=logs, stderr=logs))
                with TestClient(create_gateway(supervisor), follow_redirects=False, headers={"Accept": "text/html"}) as client:
                    wait_for(lambda: supervisor.serving() and service_state("worker")["online"] and service_state("backup")["online"])
                    assert client.get("/healthz").status_code == 200
                    assert client.get("/settings/backups/restore").status_code in {303, 307}
                    client.get("/staff/login")
                    def post(path, **fields):
                        return client.post(path, data={"csrf_token": client.cookies.get("hoikuict_csrf"), **fields})
                    login = post("/staff/login", login_id="drill@example.invalid", password=password)
                    assert login.status_code == 303, (login.status_code, login.text[:200])
                    assert client.get("/settings/backups/restore").status_code == 200
                    assert client.post("/settings/backups/restore/inspect", data={"backup_id": backup.name}).status_code == 403
                    # Preserve the existing realtime collaboration protocol through the gateway.
                    with client.websocket_connect("/meeting-notes/ws/1", headers={"Origin": "http://testserver"}) as first:
                        with client.websocket_connect("/meeting-notes/ws/1", headers={"Origin": "http://testserver"}) as second:
                            first.send_bytes(b"synthetic-collaboration")
                            assert second.receive_bytes() == b"synthetic-collaboration"
                    selected = post("/settings/backups/restore/inspect", backup_id=backup.name, reason="架空データでの検証")
                    assert selected.status_code == 303, selected.text[:200]
                    ticket_id = selected.headers["location"].rsplit("/", 1)[1]
                    assert client.get(selected.headers["location"]).status_code == 200
                    assert "架空データでの検証" in client.get("/settings/backups/restore", params={"ticket_id": ticket_id}).text
                    assert post("/settings/backups/restore/execute", ticket_id=ticket_id, password=password).status_code == 400
                    assert post("/settings/backups/restore/confirm", ticket_id=ticket_id).status_code == 400
                    assert post("/settings/backups/restore/confirm", ticket_id=ticket_id, acknowledged="yes").status_code == 200
                    assert post("/settings/backups/restore/execute", ticket_id=ticket_id, password="wrong-synthetic").status_code == 400
                    response = post("/settings/backups/restore/execute", ticket_id=ticket_id, password=password)
                    assert response.status_code == 303, response.text[:200]
                    location = response.headers["location"]
                    job_id = location.rsplit("/", 1)[1]
                    assert client.cookies.get(viewer_cookie(job_id))
                    observed_maintenance = False
                    deadline = time.monotonic() + 150
                    while time.monotonic() < deadline:
                        progress = client.get(location)
                        assert progress.status_code == 200
                        status = read_job(job_id)["state"]
                        if client.get("/healthz").status_code == 503:
                            observed_maintenance = True
                            assert client.post("/settings/backups/restore/execute").status_code == 503
                        if status in {"succeeded", "failed", "rolled_back", "blocked"}:
                            assert status == "succeeded", read_job(job_id)["message"]
                            break
                        time.sleep(0.5)
                    else:
                        raise AssertionError("Restore completion timed out")
                    assert observed_maintenance
                    assert "復元が完了しました" in client.get(location).text
                    wait_for(lambda: client.get("/healthz").status_code == 200)
                    assert client.get("/settings/backups/restore").status_code in {303, 307}
                    assert not (root / "storage/after.txt").exists()
                    with closing(sqlite3.connect(root / "data/hoikuict.db")) as db:
                        assert db.execute("SELECT display_name FROM users WHERE email='drill@example.invalid'").fetchone()[0] == "架空の管理者"
                        assert db.execute("SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL").fetchone()[0] == 0
                    assert not json.loads((root / "data/backup-control/schedule.json").read_text())["enabled"]
                    client.get("/staff/login")
                    login = post("/staff/login", login_id="drill@example.invalid", password=password)
                    assert login.status_code == 303, (login.status_code, login.text[:200])
                    assert client.get("/settings/backups/restore").status_code == 200
                    assert client.get("/settings/backups/restore/resume/" + job_id).status_code == 303
                    assert client.get(location).status_code == 200
                    saved = client.cookies.get(viewer_cookie(job_id))
                    client.cookies.delete(viewer_cookie(job_id))
                    assert client.get(location).status_code == 403
                    assert saved
                    print("RESTORE_DRILL=" + json.dumps({"verified": True, "restore": "succeeded", "maintenance": True,
                          "csrf": True, "password_reauthentication": True, "relogin": True, "websocket": True,
                          "progress_capability": True, "schedule_disabled": True}), flush=True)
        finally:
            supervisor.stop()
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
            engine.dispose()


if __name__ == "__main__":
    main()
