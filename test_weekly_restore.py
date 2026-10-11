"""Weekly data survives recovery; older backups are upgraded only on a copy."""
from contextlib import closing
import json
import os
import sqlite3
from unittest.mock import patch

import database
from plan_docs.db_models import PlanDocumentRow
from restore_data import inspect_backup, prepare_copy, schema, schema_compatible
from restore_family_archive import compatible, upgrade_copy
from scripts.backup_runtime import BackupConfig, create_backup
from sqlmodel import Session
from test_restore_runtime import CURRENT_SHA, RestoreFixture


class WeeklyRestoreTests(RestoreFixture):
    def backup(self, legacy=False):
        extra = {}
        if 'schema_contract' in BackupConfig.__dataclass_fields__:
            extra.update(recovery_kit_ref='test-kit', actor_ref='test-operator', baseline_ref='test-baseline')
            if legacy:
                extra['schema_contract'] = 'reflection-review-20261011'
        return create_backup(BackupConfig(output_root=self.paths.backups,
            database_url=os.environ["HOIKUICT_DATABASE_URL"], facility_db=self.data/"facility.sqlite",
            storage_root=self.storage, git_sha=CURRENT_SHA, app_image="sha256:"+"e"*64,
            compose_sha256="c"*64, cloudflared_image="sha256:"+"f"*64,
            facility_ref="synthetic", quiesced=True, **extra))

    def test_pre_weekly_backup_upgrade_leaves_source_and_old_text_unchanged(self):
        with Session(self.engine) as session:
            session.add(PlanDocumentRow(document_type="weekly_plan", status="draft", title="Old weekly",
                nursery_ref="synthetic", classroom_ref="A", owner_name="Author", sections=[{"body":"Old text"}]))
            session.commit()
        live = self.data/"hoikuict.db"
        with closing(sqlite3.connect(live)) as c:
            c.execute("DROP INDEX IF EXISTS ix_plan_documents_weekly_sheet_key")
            c.execute("DROP INDEX IF EXISTS uq_weekly_sheet_key")
            c.execute("ALTER TABLE plan_documents DROP COLUMN weekly_sheet")
            c.execute("ALTER TABLE plan_documents DROP COLUMN weekly_sheet_key")
        backup = self.backup(legacy=True)
        original = (backup/"db/hoikuict.db").read_bytes()
        with patch.object(database, "engine", self.engine):
            database._migrate_weekly_sheet_columns()
        live_before = live.read_bytes()
        assert schema_compatible(backup/"db/hoikuict.db", live)
        inspect_backup(self.paths, backup.name, str(self.actor_id))
        staged = prepare_copy(self.paths, backup.name, "weekly-legacy")/"data/hoikuict.db"
        assert (backup/"db/hoikuict.db").read_bytes() == original
        assert live.read_bytes() == live_before
        with closing(sqlite3.connect(staged)) as c:
            row = c.execute("SELECT sections,weekly_sheet,weekly_sheet_key FROM plan_documents").fetchone()
            assert json.loads(row[0]) == [{"body":"Old text"}] and row[1:] == (None,None)
            assert not c.execute("PRAGMA foreign_key_check").fetchall()
        upgrade_copy(staged, schema(live))
        assert not compatible(schema(live), schema(backup/"db/hoikuict.db"))

    def test_weekly_body_positions_and_provenance_survive_backup(self):
        sheet = {"schema_version":1, "source":{"rawCells":{"B4":"Original text"}},
                 "fields":{"development-1":{"body":"Edited text\n", "start":18,
                                           "position_ratio":0.2345, "confirmed":True}},
                 "baseline":{"development-1":{"body":"Previous text"}},
                 "origin":{"document_id":99,"revision_id":101}}
        with Session(self.engine) as session:
            session.add(PlanDocumentRow(document_type="weekly_plan", status="draft", title="Weekly",
                nursery_ref="synthetic", classroom_ref="A", owner_name="Author",
                weekly_sheet=sheet, weekly_sheet_key="synthetic-weekly"))
            session.commit()
        with patch.object(database, "engine", self.engine):
            database._migrate_weekly_sheet_columns()
        backup = self.backup()
        inspect_backup(self.paths, backup.name, str(self.actor_id))
        staged = prepare_copy(self.paths, backup.name, "weekly-saved")/"data/hoikuict.db"
        with closing(sqlite3.connect(staged)) as c:
            row = c.execute("SELECT weekly_sheet,weekly_sheet_key FROM plan_documents").fetchone()
            assert json.loads(row[0]) == sheet and row[1] == "synthetic-weekly"


def test_weekly_partial_or_changed_constraints_cannot_be_restored():
    base = [("table","families","families","CREATE TABLE families(id INTEGER)"),
            ("table","plan_documents","plan_documents","CREATE TABLE plan_documents(id INTEGER)")]
    for extra in ("weekly_sheet JSON", "weekly_sheet JSON NOT NULL,weekly_sheet_key VARCHAR",
                  "weekly_sheet TEXT,weekly_sheet_key VARCHAR",
                  "weekly_sheet JSON,weekly_sheet_key VARCHAR,unrelated TEXT"):
        target = [base[0], (*base[1][:3], "CREATE TABLE plan_documents(id INTEGER,"+extra+")"),
            ("index","uq_weekly_sheet_key","plan_documents",
             "CREATE UNIQUE INDEX uq_weekly_sheet_key ON plan_documents(weekly_sheet_key) WHERE weekly_sheet_key IS NOT NULL")]
        assert not compatible(base, target)
