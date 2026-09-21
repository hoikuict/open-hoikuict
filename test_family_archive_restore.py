from contextlib import closing
import os
import sqlite3
from unittest.mock import patch

from sqlmodel import SQLModel

import database
from restore_data import file_hash, inspect_backup, prepare_copy, schema_compatible
from scripts.backup_runtime import BackupConfig, create_backup
from test_restore_runtime import CURRENT_SHA, RestoreFixture


class FamilyArchiveRestoreTests(RestoreFixture):
    def test_pre_archive_backup_is_upgraded_only_on_staged_copy(self):
        live = self.data / "hoikuict.db"
        with closing(sqlite3.connect(live)) as connection:
            connection.execute("DROP TABLE family_archive_logs")
            connection.execute("DROP INDEX ix_families_archived_at")
            connection.execute("ALTER TABLE families DROP COLUMN archived_at")
            connection.execute(
                "INSERT INTO families (family_name,created_at,updated_at) VALUES ('架空家族','2026-01-01','2026-01-01')"
            )
            connection.commit()
        backup = create_backup(
            BackupConfig(
                output_root=self.paths.backups,
                database_url=os.environ["HOIKUICT_DATABASE_URL"],
                facility_db=self.data / "facility.sqlite",
                storage_root=self.storage,
                git_sha=CURRENT_SHA,
                app_image="sha256:" + "e" * 64,
                cloudflared_image="sha256:" + "f" * 64,
                recovery_kit_ref="test-kit", actor_ref="test-operator", baseline_ref="test-baseline",
                schema_contract="staff-sessions-20260920",
                compose_sha256="c" * 64,
                facility_ref="synthetic",
                quiesced=True,
            )
        )
        source = backup / "db/hoikuict.db"
        original_hash = file_hash(source)
        SQLModel.metadata.create_all(self.engine)
        with patch.object(database, "engine", self.engine):
            database._migrate_family_archive()
        self.assertTrue(schema_compatible(source, live))
        inspect_backup(self.paths, backup.name, str(self.actor_id))
        staged = (
            prepare_copy(self.paths, backup.name, "legacy-archive") / "data/hoikuict.db"
        )
        self.assertEqual(file_hash(source), original_hash)
        self.assertTrue(schema_compatible(staged, live))
        with closing(sqlite3.connect(staged)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT family_name,archived_at FROM families"
                ).fetchall(),
                [("架空家族", None)],
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM family_archive_logs"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(), []
            )
        with closing(sqlite3.connect(live)) as connection:
            connection.execute("ALTER TABLE families ADD COLUMN unrelated TEXT")
        self.assertFalse(schema_compatible(source, live))

    def test_archive_schema_drift_and_downgrades_are_not_accepted(self):
        live = self.data / "hoikuict.db"
        source = self.paths.backups / self.backup_id / "db/hoikuict.db"
        with closing(sqlite3.connect(live)) as connection:
            connection.execute(
                "ALTER TABLE family_archive_logs ADD COLUMN unrelated TEXT"
            )
        self.assertFalse(schema_compatible(source, live))

        with closing(sqlite3.connect(live)) as connection:
            connection.execute("DROP TABLE family_archive_logs")
            connection.execute("DROP INDEX ix_families_archived_at")
            connection.execute("ALTER TABLE families DROP COLUMN archived_at")
        self.assertFalse(schema_compatible(source, live))

    def test_fresh_and_migrated_archive_column_orders_are_compatible(self):
        live = self.data / "hoikuict.db"
        source = self.paths.backups / self.backup_id / "db/hoikuict.db"
        with closing(sqlite3.connect(live)) as connection:
            connection.execute("DROP INDEX ix_families_archived_at")
            connection.execute("ALTER TABLE families DROP COLUMN archived_at")
        with patch.object(database, "engine", self.engine):
            database._migrate_family_archive()
        self.assertTrue(schema_compatible(source, live))
