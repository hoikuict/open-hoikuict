from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.backup_runtime import (
    BackupConfig,
    BackupError,
    create_backup,
    verify_backup_set,
)


class BackupRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.runtime = self.root / "runtime"
        self.data = self.runtime / "data"
        self.storage = self.runtime / "storage"
        self.output = self.root / "backup"
        self.data.mkdir(parents=True)
        (self.storage / "notice_attachments").mkdir(parents=True)
        (self.storage / "message_attachments").mkdir(parents=True)
        self.main_db = self.data / "hoikuict.db"
        self.facility_db = self.data / "facility.sqlite"
        self.notice_content = b"notice-pdf"
        self.message_content = b"message-image"
        (self.storage / "notice_attachments" / "notice.pdf").write_bytes(
            self.notice_content
        )
        (self.storage / "message_attachments" / "message.png").write_bytes(
            self.message_content
        )
        from test_backup_support import full_databases
        full_databases(self.main_db, self.facility_db, attachments=True)
        self.main_connection = sqlite3.connect(self.main_db)
        self.main_connection.execute("PRAGMA journal_mode=WAL")

    def tearDown(self) -> None:
        self.main_connection.close()
        self.temporary_directory.cleanup()

    def _config(self, **overrides) -> BackupConfig:
        values = {
            "output_root": self.output,
            "database_url": f"sqlite:///{self.main_db}",
            "facility_db": self.facility_db,
            "storage_root": self.storage,
            "git_sha": "a" * 40,
            "app_image": "open-hoikuict@sha256:" + "b" * 64,
            "compose_sha256": "c" * 64,
            "cloudflared_image": "cloudflared@sha256:" + "d" * 64,
            "environment": "test",
            "facility_ref": "架空保育園",
            "quiesced": True,
            "recovery_kit_ref": "test-kit",
            "actor_ref": "test-operator",
            "baseline_ref": "test-baseline",
        }
        values.update(overrides)
        return BackupConfig(**values)

    def test_create_and_verify_backup_with_wal_and_attachments(self) -> None:
        backup_path = create_backup(self._config())

        self.assertTrue((backup_path / "COMPLETE").is_file())
        self.assertFalse((backup_path / "db" / "hoikuict.db-wal").exists())
        self.assertEqual(
            (backup_path / "storage" / "notice_attachments" / "notice.pdf").read_bytes(),
            self.notice_content,
        )
        result = verify_backup_set(backup_path)
        self.assertEqual(result["status"], "ok")

        manifest = json.loads((backup_path / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["table_counts"]["children"], 1)
        self.assertEqual(manifest["provenance"]["git_sha"], "a" * 40)
        self.assertNotIn("架空保護者", json.dumps(manifest, ensure_ascii=False))

    def test_missing_attachment_rejects_backup(self) -> None:
        (self.storage / "notice_attachments" / "notice.pdf").unlink()

        with self.assertRaisesRegex(BackupError, "整合性検査"):
            create_backup(self._config())

        partial_directories = list(self.output.glob(".*.partial"))
        self.assertEqual(len(partial_directories), 1)
        self.assertTrue((partial_directories[0] / "FAILED.json").is_file())
        self.assertFalse((partial_directories[0] / "COMPLETE").exists())

    def test_tampered_payload_is_rejected(self) -> None:
        backup_path = create_backup(self._config())
        attachment = backup_path / "storage" / "message_attachments" / "message.png"
        attachment.write_bytes(b"tampered")

        with self.assertRaisesRegex(BackupError, "SHA-256"):
            verify_backup_set(backup_path)

    def test_tampered_complete_marker_is_rejected(self) -> None:
        backup_path = create_backup(self._config())
        (backup_path / "COMPLETE").write_text("different-backup\n", encoding="utf-8")

        with self.assertRaisesRegex(BackupError, "COMPLETE marker"):
            verify_backup_set(backup_path)

    def test_missing_storage_root_rejects_backup(self) -> None:
        missing_storage = self.root / "missing-storage"

        with self.assertRaisesRegex(BackupError, "storage root"):
            create_backup(self._config(storage_root=missing_storage))

    def test_unsafe_attachment_path_rejects_backup(self) -> None:
        self.main_connection.execute(
            "UPDATE notice_attachments SET storage_path = '../outside.pdf'"
        )
        self.main_connection.commit()

        with self.assertRaisesRegex(BackupError, "整合性検査"):
            create_backup(self._config())

    def test_requires_quiesced_acknowledgement(self) -> None:
        with self.assertRaisesRegex(BackupError, "--quiesced"):
            create_backup(self._config(quiesced=False))

    def test_source_write_lock_can_replace_quiesced_source(self) -> None:
        backup_path = create_backup(
            self._config(quiesced=False, lock_source_writes=True)
        )

        manifest = json.loads((backup_path / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["source"]["method"],
            "sqlite_online_backup_with_source_write_lock",
        )

    def test_rejects_backup_output_inside_runtime(self) -> None:
        with self.assertRaisesRegex(BackupError, "runtime DBまたはstorage配下"):
            create_backup(self._config(output_root=self.data / "backups"))

        with self.assertRaisesRegex(BackupError, "runtime DBまたはstorage配下"):
            create_backup(self._config(output_root=self.runtime))

    def test_rejects_non_sqlite_database_url(self) -> None:
        with self.assertRaisesRegex(BackupError, "file-based SQLite"):
            create_backup(self._config(database_url="postgresql://example.invalid/app"))


if __name__ == "__main__":
    unittest.main()
