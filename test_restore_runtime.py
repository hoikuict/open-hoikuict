from __future__ import annotations

from contextlib import closing
from datetime import date, timedelta
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sqlmodel import SQLModel, Session, create_engine
from local_auth import hash_password
from models import AuthSession, Child, PasswordCredential, User
import restore_control as control
from restore_data import RestorePaths, apply_copy, inspect_backup, list_backups, prepare_copy
from scripts.backup_runtime import BackupConfig, create_backup
from scripts.restore_worker import RestoreExecutor
from time_utils import utc_now

SOURCE_SHA = "a" * 40
CURRENT_SHA = "b" * 40
PASSWORD = "RestoreDemo-6429!"


class RestoreFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = hash_password(PASSWORD)

    def setUp(self):
        import child_records.models  # noqa: F401
        import plan_docs.db_models  # noqa: F401
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.data, self.storage = self.root / "data", self.root / "storage"
        self.data.mkdir()
        self.storage.mkdir()
        (self.storage / "example.txt").write_text("saved attachment", encoding="utf-8")
        self.paths = RestorePaths(self.data, self.storage, self.root / "backups", self.root / "staging")
        self.key = self.root / "key"
        self.key.write_bytes(b"k" * 32)
        self.environment = patch.dict(os.environ, {
            "HOIKUICT_ENV": "test", "HOIKUICT_DATABASE_URL": "sqlite:///" + (self.data / "hoikuict.db").as_posix(),
            "HOIKU_FACILITY_BUNREI_DB_PATH": str(self.data / "facility.sqlite"),
            "HOIKUICT_STORAGE_ROOT": str(self.storage), "HOIKUICT_RESTORE_ENABLED": "1",
            "HOIKUICT_RESTORE_CONTROL_DIR": str(self.root / "control"),
            "HOIKUICT_BACKUP_CONTROL_DIR": str(self.data / "backup-control"),
            "HOIKUICT_RESTORE_BACKUP_ROOT": str(self.paths.backups),
            "HOIKUICT_RESTORE_STAGING_ROOT": str(self.paths.staging),
            "HOIKUICT_RESTORE_SIGNING_KEY_FILE": str(self.key),
            "HOIKUICT_RESTORE_COMPATIBLE_GIT_SHAS": SOURCE_SHA + "," + CURRENT_SHA,
            "HOIKUICT_BACKUP_GIT_SHA": CURRENT_SHA, "HOIKUICT_BACKUP_APP_IMAGE": "sha256:" + "e" * 64,
            "HOIKUICT_BACKUP_COMPOSE_SHA256": "c" * 64, "HOIKU_NURSERY_REF": "synthetic",
            "HOIKUICT_BACKUP_CLOUDFLARED_IMAGE": "sha256:" + "f" * 64,
            "HOIKUICT_BACKUP_RECOVERY_KIT_REF": "test-kit",
            "HOIKUICT_BACKUP_BASELINE_REF": "test-baseline",
            "HOIKUICT_COOKIE_SECURE": "false", "HOIKUICT_STAFF_AUTH_MODE": "local_password",
        })
        self.environment.start()
        self.engine = create_engine(os.environ["HOIKUICT_DATABASE_URL"])
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            user = User(email="restore@example.invalid", display_name="架空の管理者", staff_role="admin", is_active=True)
            session.add(user)
            session.commit()
            session.refresh(user)
            self.actor_id = user.id
            credential = PasswordCredential(principal_type="staff", staff_user_id=user.id,
                                            login_id=user.email, login_id_normalized=user.email,
                                            password_hash=self.password_hash, must_change_password=False)
            session.add(credential)
            session.commit()
            session.refresh(credential)
            session.add(AuthSession(token_hash="d" * 64, principal_type="staff", staff_user_id=user.id,
                                    credential_id=credential.id, credential_version=1,
                                    idle_expires_at=utc_now() + timedelta(hours=1), absolute_expires_at=utc_now() + timedelta(hours=12)))
            session.add(Child(last_name="架空", first_name="園児", last_name_kana="カクウ", first_name_kana="エンジ",
                              birth_date=date(2024, 1, 1), enrollment_date=date(2026, 4, 1)))
            session.commit()
        self.engine.dispose()
        with closing(sqlite3.connect(self.data / "facility.sqlite")) as db:
            from plan_docs.services.bunrei import _ensure_facility_table
            _ensure_facility_table(db)
            db.commit()
        (self.data / "backup-control").mkdir()
        control.atomic_json(self.data / "backup-control/schedule.json", {
            "schema_version": 1, "enabled": True, "frequency": "weekly", "run_time": "03:25", "weekday": 4,
        })
        backup = create_backup(BackupConfig(output_root=self.paths.backups, database_url=os.environ["HOIKUICT_DATABASE_URL"],
                                           facility_db=self.data / "facility.sqlite", storage_root=self.storage,
                                           git_sha=SOURCE_SHA, app_image="sha256:" + "e" * 64, compose_sha256="c" * 64,
                                           cloudflared_image="sha256:" + "f" * 64, recovery_kit_ref="test-kit",
                                           actor_ref="test-operator", baseline_ref="test-baseline",
                                           facility_ref="synthetic", quiesced=True))
        self.backup_id = backup.name
        control.atomic_json(self.data / "backup-control/schedule.json", {
            "schema_version": 1, "enabled": True, "frequency": "daily", "run_time": "05:00", "weekday": 0,
        })
        with closing(sqlite3.connect(self.data / "hoikuict.db")) as db:
            db.execute("UPDATE users SET display_name='変更後の管理者'")
            db.commit()
        (self.storage / "current-only.txt").write_text("current only", encoding="utf-8")
        control.ensure_root()
        control.heartbeat("worker")
        control.heartbeat("backup", paused=False)
        control.heartbeat("gateway", mode="normal", healthy=True)

    def tearDown(self):
        self.engine.dispose()
        self.environment.stop()
        self.temp.cleanup()

    def ticket(self):
        result = inspect_backup(self.paths, self.backup_id, str(self.actor_id))
        ticket = control.issue_ticket({**result, "actor_id": str(self.actor_id), "actor_name": "架空管理者", "reason": "検証"})
        control.confirm_ticket(ticket["ticket_id"], str(self.actor_id))
        return ticket

    def queued(self):
        ticket = self.ticket()
        job, token = control.queue_restore(ticket["ticket_id"], str(self.actor_id))
        request = control.read_json(control.control_dir() / "requests" / (job["job_id"] + ".json"))
        return job, token, request

    def display_name(self):
        with closing(sqlite3.connect(self.data / "hoikuict.db")) as db:
            return db.execute("SELECT display_name FROM users").fetchone()[0]


class RestoreDataTests(RestoreFixture):
    def test_inspect_and_apply_copy_preserves_original_backup_and_invalidates_sessions(self):
        original = (self.paths.backups / self.backup_id / "db/hoikuict.db").read_bytes()
        info = inspect_backup(self.paths, self.backup_id, str(self.actor_id))
        self.assertEqual(info["before"]["files"], 2)
        self.assertEqual(info["after"]["files"], 1)
        prepared = prepare_copy(self.paths, self.backup_id, "test-copy")
        self.assertEqual(self.display_name(), "変更後の管理者")
        apply_copy(self.paths, prepared)
        self.assertEqual(self.display_name(), "架空の管理者")
        self.assertFalse((self.storage / "current-only.txt").exists())
        self.assertEqual((self.storage / "example.txt").read_text(), "saved attachment")
        with closing(sqlite3.connect(self.data / "hoikuict.db")) as db:
            self.assertEqual(db.execute("SELECT revoke_reason FROM auth_sessions").fetchone()[0], "backup_restore")
        schedule = control.read_json(self.data / "backup-control/schedule.json")
        self.assertFalse(schedule["enabled"])
        self.assertEqual((schedule["frequency"], schedule["run_time"], schedule["weekday"]), ("weekly", "03:25", 4))
        self.assertEqual(original, (self.paths.backups / self.backup_id / "db/hoikuict.db").read_bytes())

    def test_legacy_backup_remains_eligible_and_restorable(self):
        from test_backup_v2 import legacy
        legacy(self.paths.backups / self.backup_id)
        self.assertTrue(list_backups(self.paths)[0]["eligible"])
        inspect_backup(self.paths, self.backup_id, str(self.actor_id))
        job, _, request = self.queued()
        InProcessExecutor(self.paths).execute(request)
        self.assertEqual(control.read_job(job["job_id"])["state"], "succeeded")
        self.assertEqual(self.display_name(), "架空の管理者")
        self.assertFalse(control.read_json(self.data / "backup-control/schedule.json")["enabled"])

    def test_corrupted_payload_rejected_without_live_change(self):
        (self.paths.backups / self.backup_id / "storage/example.txt").write_text("corrupt")
        with self.assertRaises(control.RestoreError):
            inspect_backup(self.paths, self.backup_id, str(self.actor_id))
        self.assertEqual(self.display_name(), "変更後の管理者")

    def test_schema_or_actor_changes_block_restoration(self):
        with closing(sqlite3.connect(self.data / "hoikuict.db")) as db:
            db.execute("CREATE TABLE new_schema (id INTEGER)")
        with self.assertRaisesRegex(control.RestoreError, "データ構造"):
            inspect_backup(self.paths, self.backup_id, str(self.actor_id))

    def test_path_traversal_and_wrong_facility_rejected(self):
        with self.assertRaises(control.RestoreError):
            inspect_backup(self.paths, "../data", str(self.actor_id))
        with patch.dict(os.environ, {"HOIKU_NURSERY_REF": "different"}):
            with self.assertRaisesRegex(control.RestoreError, "この園"):
                inspect_backup(self.paths, self.backup_id, str(self.actor_id))

    def test_single_use_tickets_and_read_only_viewer_capability(self):
        job, token, request = self.queued()
        self.assertTrue(control.viewer_allowed(job, token))
        self.assertFalse(control.viewer_allowed(job, "invalid"))
        request["backup_id"] = "../data"
        with self.assertRaises(control.RestoreError):
            control.verified(request)
        with self.assertRaises(control.RestoreError):
            self.queued()
        before = control.read_job(job["job_id"])
        renewed = control.grant_viewer(job["job_id"])
        self.assertEqual(before, control.read_job(job["job_id"]))
        self.assertFalse(control.viewer_allowed(job, token))
        self.assertTrue(control.viewer_allowed(job, renewed))

    def test_expired_ticket_inactive_admin_and_offline_worker_are_rejected(self):
        ticket = self.ticket()
        path = control.control_dir() / "tickets" / (ticket["ticket_id"] + ".json")
        control.atomic_json(path, control.signed({**control.read_json(path), "expires": 0}))
        with self.assertRaisesRegex(control.RestoreError, "有効期限"):
            control.queue_restore(ticket["ticket_id"], str(self.actor_id))
        ticket = self.ticket()
        (control.control_dir() / "backup.json").unlink()
        with self.assertRaisesRegex(control.RestoreError, "停止中"):
            control.queue_restore(ticket["ticket_id"], str(self.actor_id))
        with closing(sqlite3.connect(self.data / "hoikuict.db")) as db:
            db.execute("UPDATE users SET is_active=0")
            db.commit()
        with self.assertRaisesRegex(control.RestoreError, "ログイン"):
            inspect_backup(self.paths, self.backup_id, str(self.actor_id))


class InProcessExecutor(RestoreExecutor):
    """Model only service acknowledgements; run real DB/file backup and recovery."""
    def pause(self, job_id):
        control.set_maintenance(job_id, "stop")

    def probe(self, job_id):
        control.set_maintenance(job_id, "probe")

    def resume(self, job_id):
        control.set_maintenance(job_id, "resume")


class RestoreExecutorTests(RestoreFixture):
    def test_successful_restore(self):
        job, _, request = self.queued()
        InProcessExecutor(self.paths).execute(request)
        saved = control.read_job(job["job_id"])
        self.assertEqual(saved["state"], "succeeded")
        self.assertIsNone(control.maintenance())
        self.assertIsNone(control.active_job())
        self.assertEqual(self.display_name(), "架空の管理者")
        self.assertTrue((self.paths.backups / saved["rollback_backup"] / "COMPLETE").is_file())
        manifest = control.read_json(self.paths.backups / saved["rollback_backup"] / "manifest.json")
        self.assertEqual(manifest["format_version"], 2)
        self.assertEqual(manifest["actor_ref"], job["job_id"])
        self.assertEqual(manifest["retention_class"], "change")

    def test_failure_after_partial_replacement_rolls_back(self):
        job, _, request = self.queued()
        real_apply = apply_copy
        calls = 0
        def broken_once(paths, prepared):
            nonlocal calls
            calls += 1
            real_apply(paths, prepared)
            if calls == 1:
                raise OSError("synthetic interruption")
        with patch("scripts.restore_worker.apply_copy", side_effect=broken_once):
            InProcessExecutor(self.paths).execute(request)
        self.assertEqual(control.read_job(job["job_id"])["state"], "rolled_back")
        self.assertEqual(self.display_name(), "変更後の管理者")
        self.assertTrue((self.storage / "current-only.txt").is_file())
        self.assertIsNone(control.maintenance())

    def test_failed_rollback_keeps_maintenance_and_blocks_new_jobs(self):
        job, _, request = self.queued()
        with patch("scripts.restore_worker.apply_copy", side_effect=OSError("synthetic failure")):
            InProcessExecutor(self.paths).execute(request)
        self.assertEqual(control.read_job(job["job_id"])["state"], "blocked")
        self.assertEqual(control.maintenance()["mode"], "stop")
        self.assertIsNotNone(control.active_job())

    def test_backup_failure_does_not_replace_data(self):
        job, _, request = self.queued()
        with patch("scripts.restore_worker.fresh_backup", side_effect=OSError("synthetic backup error")):
            InProcessExecutor(self.paths).execute(request)
        self.assertEqual(control.read_job(job["job_id"])["state"], "failed")
        self.assertEqual(self.display_name(), "変更後の管理者")
        self.assertIsNone(control.maintenance())

    def test_restart_after_commit_does_not_roll_back_new_business_writes(self):
        job, _, request = self.queued()
        executor = InProcessExecutor(self.paths)
        with patch("scripts.restore_worker.clear_maintenance", side_effect=SystemExit("power loss")):
            with self.assertRaises(SystemExit):
                executor.execute(request)
        self.assertEqual(control.read_job(job["job_id"])["state"], "committed")
        with closing(sqlite3.connect(self.data / "hoikuict.db")) as db:
            db.execute("UPDATE users SET display_name='切替確定後'")
            db.commit()
        executor.recover(job["job_id"])
        self.assertEqual(control.read_job(job["job_id"])["state"], "succeeded")
        self.assertEqual(self.display_name(), "切替確定後")

    def test_restart_during_copy_recovers_saved_data(self):
        job, _, request = self.queued()
        executor = InProcessExecutor(self.paths)
        with patch("scripts.restore_worker.apply_copy", side_effect=SystemExit("power loss")):
            with self.assertRaises(SystemExit):
                executor.execute(request)
        self.assertEqual(control.read_job(job["job_id"])["phase"], "applying")
        executor.recover(job["job_id"])
        self.assertEqual(control.read_job(job["job_id"])["state"], "rolled_back")
        self.assertEqual(self.display_name(), "変更後の管理者")


if __name__ == "__main__":
    unittest.main()
