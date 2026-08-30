from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
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
        self.main_connection = sqlite3.connect(self.main_db)
        self.main_connection.execute("PRAGMA journal_mode=WAL")
        self.main_connection.executescript(
            """
            CREATE TABLE parents (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE children (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL REFERENCES parents(id),
                name TEXT NOT NULL
            );
            CREATE TABLE notice_attachments (
                id INTEGER PRIMARY KEY,
                storage_path TEXT NOT NULL,
                file_size INTEGER NOT NULL
            );
            CREATE TABLE message_attachments (
                id INTEGER PRIMARY KEY,
                storage_path TEXT NOT NULL,
                file_size INTEGER NOT NULL
            );
            """
        )
        self.main_connection.execute("INSERT INTO parents(name) VALUES ('架空保護者')")
        self.main_connection.execute(
            "INSERT INTO children(parent_id, name) VALUES (1, '架空園児')"
        )
        self.main_connection.execute(
            "INSERT INTO notice_attachments(storage_path, file_size) VALUES (?, ?)",
            ("notice.pdf", len(self.notice_content)),
        )
        self.main_connection.execute(
            "INSERT INTO message_attachments(storage_path, file_size) VALUES (?, ?)",
            ("message.png", len(self.message_content)),
        )
        self.main_connection.commit()

        with closing(sqlite3.connect(self.facility_db)) as connection:
            connection.execute(
                "CREATE TABLE bunrei_facility (id TEXT PRIMARY KEY, text TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO bunrei_facility(id, text) VALUES ('sample', '架空文例')"
            )
            connection.commit()

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
