"""Fee-band backups remain usable across the approved additive migration."""
from contextlib import closing
from datetime import date, datetime
import json
import sqlite3
from unittest.mock import patch

import pytest
from sqlmodel import Session, select

import database
import child_records.models  # noqa: F401
from models import AttendanceRecord, Child, ExtendedCareCharge, ExtendedCareFeeRule
from restore_data import inspect_backup, prepare_copy, schema, schema_compatible
from restore_family_archive import compatible, upgrade_copy
import test_annual_restore
from test_restore_runtime import RestoreFixture


class ExtendedCareRestoreTests(RestoreFixture):
    backup = test_annual_restore.AnnualRestoreTests.backup

    def add_fees(self, plan=None, breakdown=None):
        with Session(self.engine) as session:
            child = session.exec(select(Child)).first()
            rule = ExtendedCareFeeRule(name="Fictional fee", effective_from=date(2026, 4, 1),
                                       fee_bands_json=plan)
            attendance = AttendanceRecord(child_id=child.id, attendance_date=date(2026, 9, 1),
                                          check_in_at=datetime(2026, 9, 1, 8),
                                          check_out_at=datetime(2026, 9, 1, 19))
            session.add(rule)
            session.add(attendance)
            session.flush()
            session.add(ExtendedCareCharge(attendance_record_id=attendance.id, child_id=child.id,
                target_date=date(2026, 9, 1), rule_id=rule.id, charge_start_at=datetime(2026, 9, 1, 18),
                auto_amount=400, final_amount=400, fee_breakdown_json=breakdown))
            session.commit()

    def test_old_backup_is_upgraded_only_on_restore_copy(self):
        self.check_old_backup()

    def test_older_annual_and_fee_migrations_are_combined_on_copy(self):
        self.check_old_backup(before_annual=True)

    def check_old_backup(self, before_annual=False):
        self.add_fees()
        live = self.data / "hoikuict.db"
        with closing(sqlite3.connect(live)) as connection:
            connection.execute("ALTER TABLE extended_care_fee_rules DROP COLUMN fee_bands_json")
            connection.execute("ALTER TABLE extended_care_charges DROP COLUMN fee_breakdown_json")
            if before_annual:
                connection.execute("DROP INDEX IF EXISTS ix_plan_documents_annual_sheet_key")
                connection.execute("DROP INDEX IF EXISTS uq_annual_sheet_key")
                connection.execute("ALTER TABLE plan_documents DROP COLUMN annual_sheet")
                connection.execute("ALTER TABLE plan_documents DROP COLUMN annual_sheet_key")
        self.engine.dispose()
        backup = self.backup()
        source = backup / "db/hoikuict.db"
        source_bytes = source.read_bytes()
        with patch.object(database, "engine", self.engine):
            database._migrate_care_certification_and_extended_care_columns()
            if before_annual:
                database._migrate_annual_sheet_columns()
        live_bytes = live.read_bytes()
        assert schema_compatible(source, live)
        inspect_backup(self.paths, backup.name, str(self.actor_id))
        staged = prepare_copy(self.paths, backup.name, "fee-legacy") / "data/hoikuict.db"
        upgrade_copy(staged, schema(live))  # Idempotent on an already upgraded copy.
        with closing(sqlite3.connect(staged)) as connection:
            assert connection.execute("SELECT name,fee_bands_json FROM extended_care_fee_rules").fetchone() == ("Fictional fee", None)
            assert connection.execute("SELECT auto_amount,final_amount,fee_breakdown_json FROM extended_care_charges").fetchone() == (400, 400, None)
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        assert live.read_bytes() == live_bytes and source.read_bytes() == source_bytes
        assert not schema_compatible(live, source)

    def test_saved_plan_and_breakdown_survive_restore_preparation(self):
        plan = json.dumps({"version": 1, "evening": [{"start": "18:00", "end": "19:00", "price": 400}]})
        breakdown = json.dumps({"total": 400, "label": "18–19時"}, ensure_ascii=False)
        self.add_fees(plan, breakdown)
        backup = self.backup()
        source_bytes = (backup / "db/hoikuict.db").read_bytes()
        inspect_backup(self.paths, backup.name, str(self.actor_id))
        staged = prepare_copy(self.paths, backup.name, "fee-saved") / "data/hoikuict.db"
        with closing(sqlite3.connect(staged)) as connection:
            assert connection.execute("SELECT fee_bands_json FROM extended_care_fee_rules").fetchone() == (plan,)
            assert connection.execute("SELECT fee_breakdown_json,final_amount FROM extended_care_charges").fetchone() == (breakdown, 400)
        assert (backup / "db/hoikuict.db").read_bytes() == source_bytes


def fee_schema(rule="", charge=""):
    return [("table", "families", "families", "CREATE TABLE families(id INTEGER)"),
            ("table", "extended_care_fee_rules", "extended_care_fee_rules", "CREATE TABLE extended_care_fee_rules(id INTEGER" + ("," + rule if rule else "") + ")"),
            ("table", "extended_care_charges", "extended_care_charges", "CREATE TABLE extended_care_charges(id INTEGER" + ("," + charge if charge else "") + ")")]


@pytest.mark.parametrize("rule,charge", [
    ("fee_bands_json TEXT", ""),
    ("", "fee_breakdown_json TEXT"),
    ("fee_bands_json TEXT NOT NULL", "fee_breakdown_json TEXT"),
    ("fee_bands_json TEXT DEFAULT '{}'", "fee_breakdown_json TEXT"),
    ("fee_bands_json JSON", "fee_breakdown_json TEXT"),
    ("fee_bands_json VARCHAR(64)", "fee_breakdown_json TEXT"),
    ("fee_bands_json TEXT", "fee_breakdown_json TEXT NOT NULL"),
    ("fee_bands_json TEXT", "fee_breakdown_json TEXT DEFAULT NULL"),
    ("fee_bands_json TEXT", "fee_breakdown_json BLOB"),
    ("fee_bands_json TEXT,unrelated TEXT", "fee_breakdown_json TEXT"),
    ("fee_bands_json TEXT UNIQUE", "fee_breakdown_json TEXT"),
])
def test_partial_or_unapproved_fee_schema_is_rejected(rule, charge):
    assert not compatible(fee_schema(), fee_schema(rule, charge))


def test_fresh_and_migrated_fee_columns_are_compatible_but_cannot_downgrade():
    old = fee_schema()
    migrated = fee_schema("fee_bands_json TEXT", "fee_breakdown_json TEXT")
    fresh = fee_schema("fee_bands_json VARCHAR", "fee_breakdown_json VARCHAR")
    assert compatible(old, migrated) and compatible(old, fresh)
    assert compatible(migrated, fresh) and compatible(fresh, migrated)
    assert not compatible(migrated, old)
    assert not compatible(fresh, old)


def test_unrelated_indexes_are_not_ignored():
    target = fee_schema("fee_bands_json TEXT", "fee_breakdown_json TEXT")
    target.append(("index", "custom_fee_index", "extended_care_fee_rules",
                   "CREATE INDEX custom_fee_index ON extended_care_fee_rules(fee_bands_json)"))
    assert not compatible(fee_schema(), target)
