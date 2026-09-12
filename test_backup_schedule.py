from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from backup_jobs import list_backup_jobs
from backup_schedule import (
    JST,
    BackupScheduleError,
    due_schedule_slot,
    load_backup_schedule,
    next_scheduled_run,
    save_backup_schedule,
)
from scripts.backup_worker import (
    BackupWorkerSettings,
    enqueue_due_scheduled_backup,
)


class BackupScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.control_dir = Path(self.temporary_directory.name) / "control"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _save(self, **overrides):
        values = {
            "enabled": True,
            "frequency": "daily",
            "run_time": "02:00",
            "weekday": 0,
            "updated_by_id": None,
            "updated_by_name": "管理者",
            "control_dir": self.control_dir,
        }
        values.update(overrides)
        return save_backup_schedule(**values)

    def test_default_schedule_is_disabled(self) -> None:
        schedule = load_backup_schedule(self.control_dir)

        self.assertFalse(schedule["enabled"])
        self.assertIsNone(next_scheduled_run(schedule))
        self.assertIsNone(due_schedule_slot(schedule))

    def test_daily_schedule_reports_next_run_and_due_slot(self) -> None:
        schedule = self._save()
        before = datetime(2026, 8, 31, 1, 30, tzinfo=JST)
        after = datetime(2026, 8, 31, 2, 1, tzinfo=JST)

        self.assertEqual(
            next_scheduled_run(schedule, now=before),
            datetime(2026, 8, 31, 2, 0, tzinfo=JST),
        )
        self.assertEqual(
            due_schedule_slot(schedule, now=after),
            "daily:2026-08-31:02:00",
        )

    def test_weekly_schedule_only_runs_on_selected_weekday(self) -> None:
        schedule = self._save(frequency="weekly", weekday=0)

        self.assertEqual(
            due_schedule_slot(
                schedule,
                now=datetime(2026, 8, 31, 3, 0, tzinfo=JST),
            ),
            "weekly:2026-08-31:02:00",
        )
        self.assertIsNone(
            due_schedule_slot(
                schedule,
                now=datetime(2026, 9, 1, 3, 0, tzinfo=JST),
            )
        )

    def test_invalid_time_is_rejected(self) -> None:
        with self.assertRaises(BackupScheduleError):
            self._save(run_time="25:00")

    def test_worker_enqueues_each_schedule_slot_once(self) -> None:
        self._save()
        settings = BackupWorkerSettings(
            control_dir=self.control_dir,
            output_root=Path(self.temporary_directory.name) / "sets",
            database_url="sqlite:///unused.db",
            facility_db=Path("unused-facility.db"),
            storage_root=Path("unused-storage"),
            git_sha="a" * 40,
            app_image="test",
            compose_sha256="b" * 64,
        )
        now = datetime(2026, 8, 31, 2, 5, tzinfo=JST)

        self.assertTrue(enqueue_due_scheduled_backup(settings, now=now))
        self.assertFalse(enqueue_due_scheduled_backup(settings, now=now))
        jobs = list_backup_jobs(control_dir=self.control_dir)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["trigger"], "scheduled")
        self.assertEqual(jobs[0]["scheduled_slot"], "daily:2026-08-31:02:00")


if __name__ == "__main__":
    unittest.main()
