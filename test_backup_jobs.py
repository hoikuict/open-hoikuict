from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import Role, StaffUser
from backup_jobs import (
    BackupJobConflict,
    claim_next_backup,
    enqueue_backup,
    finish_backup_job,
    list_backup_jobs,
    worker_status,
    write_worker_heartbeat,
)
from backup_schedule import load_backup_schedule
import routers.backups as backups_router_module
from scripts.backup_worker import BackupWorkerSettings, process_next_backup


class BackupJobStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.control_dir = Path(self.temporary_directory.name) / "control"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_queue_claim_finish_and_prevent_duplicate(self) -> None:
        queued = enqueue_backup(
            requested_by_id="00000000-0000-0000-0000-000000000001",
            requested_by_name="管理者",
            control_dir=self.control_dir,
        )
        with self.assertRaises(BackupJobConflict):
            enqueue_backup(
                requested_by_id=None,
                requested_by_name="別の管理者",
                control_dir=self.control_dir,
            )

        running = claim_next_backup(self.control_dir)
        self.assertIsNotNone(running)
        self.assertEqual(running["job_id"], queued["job_id"])
        self.assertEqual(running["status"], "running")

        finish_backup_job(
            running,
            status="succeeded",
            result={"backup_id": "example", "files_verified": 3},
            control_dir=self.control_dir,
        )
        jobs = list_backup_jobs(control_dir=self.control_dir)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "succeeded")

    def test_worker_heartbeat_reports_online(self) -> None:
        self.assertEqual(
            worker_status(control_dir=self.control_dir)["status"],
            "offline",
        )
        write_worker_heartbeat(self.control_dir)
        self.assertEqual(
            worker_status(control_dir=self.control_dir)["status"],
            "online",
        )

    def test_invalid_request_is_quarantined_without_blocking_valid_job(self) -> None:
        valid = enqueue_backup(
            requested_by_id=None,
            requested_by_name="管理者",
            control_dir=self.control_dir,
        )
        invalid = self.control_dir / "requests" / "000-invalid.json"
        invalid.write_text("not-json\n", encoding="utf-8")

        claimed = claim_next_backup(self.control_dir)

        self.assertEqual(claimed["job_id"], valid["job_id"])
        self.assertEqual(len(list((self.control_dir / "rejected").glob("*.json"))), 1)


class BackupWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.runtime = self.root / "runtime"
        self.data = self.runtime / "data"
        self.storage = self.runtime / "storage"
        self.control = self.data / "backup-control"
        self.output = self.root / "backup-sets"
        self.data.mkdir(parents=True)
        self.storage.mkdir(parents=True)
        self.main_db = self.data / "hoikuict.db"
        self.facility_db = self.data / "facility.sqlite"
        with closing(sqlite3.connect(self.main_db)) as connection:
            connection.execute("CREATE TABLE children (id INTEGER PRIMARY KEY, name TEXT)")
            connection.execute("INSERT INTO children(name) VALUES ('架空 花子')")
            connection.commit()
        with closing(sqlite3.connect(self.facility_db)) as connection:
            connection.execute("CREATE TABLE facility (id INTEGER PRIMARY KEY, name TEXT)")
            connection.execute("INSERT INTO facility(name) VALUES ('架空保育園')")
            connection.commit()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_worker_processes_ui_request_to_verified_backup(self) -> None:
        enqueue_backup(
            requested_by_id=None,
            requested_by_name="管理者",
            control_dir=self.control,
        )
        settings = BackupWorkerSettings(
            control_dir=self.control,
            output_root=self.output,
            database_url=f"sqlite:///{self.main_db}",
            facility_db=self.facility_db,
            storage_root=self.storage,
            git_sha="a" * 40,
            app_image="open-hoikuict@sha256:" + "b" * 64,
            compose_sha256="c" * 64,
            environment="test",
        )

        self.assertTrue(process_next_backup(settings))
        jobs = list_backup_jobs(control_dir=self.control)
        self.assertEqual(jobs[0]["status"], "succeeded")
        backup_id = jobs[0]["result"]["backup_id"]
        self.assertTrue((self.output / backup_id / "COMPLETE").is_file())
        self.assertEqual(jobs[0]["result"]["verification_status"], "ok")


class BackupRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.control_dir = Path(self.temporary_directory.name) / "control"
        self.environment = patch.dict(
            os.environ,
            {"HOIKUICT_BACKUP_CONTROL_DIR": str(self.control_dir)},
        )
        self.environment.start()
        self.app = FastAPI()
        self.app.include_router(backups_router_module.router)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary_directory.cleanup()

    def _authenticate(self, role: Role) -> None:
        self.app.dependency_overrides[
            backups_router_module.get_current_staff_user
        ] = lambda: StaffUser(role=role, name="管理者")

    def test_admin_can_open_page_and_enqueue_backup(self) -> None:
        self._authenticate(Role.ADMIN)
        write_worker_heartbeat(self.control_dir)

        response = self.client.get("/settings/backups")
        self.assertEqual(response.status_code, 200)
        self.assertIn("今すぐバックアップ", response.text)

        response = self.client.post(
            "/settings/backups/create",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        jobs = list_backup_jobs(control_dir=self.control_dir)
        self.assertEqual(jobs[0]["status"], "queued")

    def test_non_admin_is_rejected(self) -> None:
        self._authenticate(Role.CAN_EDIT)

        response = self.client.get("/settings/backups")
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/settings/backups/create")
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            "/settings/backups/schedule",
            data={"enabled": "1", "frequency": "daily", "run_time": "02:00"},
        )
        self.assertEqual(response.status_code, 403)

    def test_offline_worker_does_not_enqueue(self) -> None:
        self._authenticate(Role.ADMIN)

        response = self.client.post(
            "/settings/backups/create",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(list_backup_jobs(control_dir=self.control_dir), [])

    def test_admin_can_save_schedule(self) -> None:
        self._authenticate(Role.ADMIN)

        response = self.client.post(
            "/settings/backups/schedule",
            data={
                "enabled": "1",
                "frequency": "weekly",
                "run_time": "03:15",
                "weekday": "6",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        schedule = load_backup_schedule(self.control_dir)
        self.assertTrue(schedule["enabled"])
        self.assertEqual(schedule["frequency"], "weekly")
        self.assertEqual(schedule["run_time"], "03:15")
        self.assertEqual(schedule["weekday"], 6)


if __name__ == "__main__":
    unittest.main()
