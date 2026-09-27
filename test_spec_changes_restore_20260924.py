"""Old backups must remain usable after the approved additive columns and tables."""
from contextlib import closing
from datetime import date
import os
import sqlite3
from unittest.mock import patch

from sqlmodel import Session, SQLModel, select

import database
from guardian_hours import closing_time
from models import AttendanceVerificationHistory, Child, DailyContactReply
from restore_data import file_hash, inspect_backup, prepare_copy, schema_compatible
from restore_family_archive import SPEC_COLUMNS, upgrade_copy
from scripts.backup_runtime import BackupConfig, create_backup
from test_restore_runtime import CURRENT_SHA, RestoreFixture


def remove_spec(connection):
    connection.execute("DROP TABLE guardian_hours_settings")
    connection.execute("DROP TABLE guardian_hours_audits")
    for table, fields in SPEC_COLUMNS.items():
        for name in fields:
            connection.execute(f"ALTER TABLE {table} DROP COLUMN {name}")


class SpecRestoreTests(RestoreFixture):
    def legacy_restore(self, *, pre_archive=False):
        live = self.data / "hoikuict.db"
        with Session(self.engine) as session:
            child = session.exec(select(Child)).one()
            session.add(DailyContactReply(child_id=child.id, target_date=date(2026, 9, 23), status="published",
                                          message="公開済みの記録", field_values={"temperature":"36.5"}))
            session.add(AttendanceVerificationHistory(child_id=child.id, target_date=date(2026, 9, 23),
                                                       status="present", updated_by_name="記録した職員"))
            session.commit()
        with closing(sqlite3.connect(live)) as connection:
            remove_spec(connection)
            if pre_archive:
                connection.execute("DROP TABLE family_archive_logs")
                connection.execute("DROP INDEX ix_families_archived_at")
                connection.execute("ALTER TABLE families DROP COLUMN archived_at")
        # The development branch also requires provenance fields absent on the pilot.
        metadata = {key: value for key, value in {
            "recovery_kit_ref":"test-kit", "actor_ref":"test-operator", "baseline_ref":"test-baseline",
            "schema_contract":"staff-sessions-20260920",
        }.items() if key in BackupConfig.__dataclass_fields__}
        backup = create_backup(BackupConfig(output_root=self.paths.backups,
            database_url=os.environ["HOIKUICT_DATABASE_URL"], facility_db=self.data / "facility.sqlite",
            storage_root=self.storage, git_sha=CURRENT_SHA, app_image="sha256:" + "e" * 64,
            cloudflared_image="sha256:" + "f" * 64, compose_sha256="c" * 64,
            facility_ref="synthetic", quiesced=True, **metadata))
        source = backup / "db/hoikuict.db"
        before = file_hash(source)
        SQLModel.metadata.create_all(self.engine)
        with patch.object(database, "engine", self.engine):
            database._migrate_family_archive()
            database._migrate_spec_20260924_columns()
        self.assertTrue(schema_compatible(source, live))
        inspect_backup(self.paths, backup.name, str(self.actor_id))
        staged = prepare_copy(self.paths, backup.name, "old-spec24") / "data/hoikuict.db"
        self.assertEqual(before, file_hash(source))
        self.assertTrue(schema_compatible(staged, live))
        with closing(sqlite3.connect(staged)) as connection:
            self.assertEqual(connection.execute("SELECT message,pending_draft FROM daily_contact_replies").fetchall(),
                             [("公開済みの記録", None)])
            self.assertEqual(connection.execute("SELECT updated_by_name,reason,previous_status,actor_user_id FROM attendance_verification_histories").fetchall(),
                             [("記録した職員", None, None, None)])
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM guardian_hours_settings").fetchone()[0], 0)
            schema = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
            dump = list(connection.iterdump())
        upgrade_copy(staged, schema)
        with closing(sqlite3.connect(staged)) as connection:
            self.assertEqual(dump, list(connection.iterdump()))
        with Session(self.engine) as session:
            self.assertEqual(closing_time(session), "19:00")

    def test_pre_spec_backup_is_restorable_without_changing_the_original(self):
        self.legacy_restore()

    def test_pre_archive_and_pre_spec_backup_can_be_upgraded_together(self):
        self.legacy_restore(pre_archive=True)

    def test_schema_downgrade_is_rejected(self):
        live = self.data / "hoikuict.db"
        source = self.paths.backups / self.backup_id / "db/hoikuict.db"
        with closing(sqlite3.connect(live)) as connection:
            remove_spec(connection)
        self.assertFalse(schema_compatible(source, live))

    def test_partial_spec_migration_and_unknown_schema_are_rejected(self):
        live = self.data / "hoikuict.db"
        source = self.paths.backups / self.backup_id / "db/hoikuict.db"
        for statement in ("ALTER TABLE daily_contact_replies DROP COLUMN pending_draft",
                          "ALTER TABLE daily_contact_replies ADD COLUMN pending_draft TEXT"):
            with closing(sqlite3.connect(live)) as connection:
                connection.execute(statement)
            self.assertFalse(schema_compatible(source, live))

    def test_new_tables_with_unrelated_columns_are_rejected(self):
        live = self.data / "hoikuict.db"
        source = self.paths.backups / self.backup_id / "db/hoikuict.db"
        with closing(sqlite3.connect(live)) as connection:
            connection.execute("ALTER TABLE guardian_hours_audits ADD COLUMN unexpected TEXT")
        self.assertFalse(schema_compatible(source, live))
