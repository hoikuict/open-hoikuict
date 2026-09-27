"""Sharing schema migration is additive; old backups remain unchanged."""
from contextlib import closing
import sqlite3
from unittest.mock import patch
from datetime import date

import pytest
from sqlmodel import SQLModel, Session, create_engine
import database
import child_records.models
from restore_family_archive import compatible, upgrade_copy
from models import Child


def schema(connection):
    return connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()


def test_old_copy_migrates_and_preserves_legacy_visibility(tmp_path):
    live = tmp_path / "live.sqlite"
    engine = create_engine(f"sqlite:///{live.as_posix()}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        child = Child(last_name="見本", first_name="園児", last_name_kana="ミホン", first_name_kana="エンジ", birth_date=date(2022, 4, 1), enrollment_date=date(2026, 4, 1))
        session.add(child)
        session.flush()
        session.add(child_records.models.ChildObservationLog(child_id=child.id, observed_on=date(2026, 9, 25), child_state="以前の記録", created_by_name="以前の職員"))
        session.commit()
    with closing(sqlite3.connect(live)) as connection:
        connection.execute("ALTER TABLE child_observation_logs DROP COLUMN visibility")
        connection.execute("ALTER TABLE child_observation_logs DROP COLUMN shared_staff_ids")
        old_schema = schema(connection)
        old = tmp_path / "backup.sqlite"
        with closing(sqlite3.connect(old)) as destination:
            connection.backup(destination)
    before = old.read_bytes()
    with patch.object(database, "engine", engine):
        database._migrate_observation_sharing_columns()
        database._migrate_observation_sharing_columns()
    with closing(sqlite3.connect(live)) as connection:
        current_schema = schema(connection)
    assert compatible(old_schema, current_schema)
    staged = tmp_path / "isolated.sqlite"
    staged.write_bytes(before)
    upgrade_copy(staged, current_schema)
    assert old.read_bytes() == before
    with closing(sqlite3.connect(staged)) as connection:
        assert compatible(schema(connection), current_schema)
        columns = {row[1]: row for row in connection.execute("PRAGMA table_info(child_observation_logs)")}
        assert columns["visibility"][3:5] == (0, None)
        assert columns["shared_staff_ids"][3:5] == (0, None)
        assert connection.execute("SELECT child_state, visibility, shared_staff_ids FROM child_observation_logs").fetchone() == ("以前の記録", None, None)
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    upgrade_copy(staged, current_schema)
    engine.dispose()


@pytest.mark.parametrize("declaration", ["visibility VARCHAR", "visibility VARCHAR DEFAULT 'shared', shared_staff_ids JSON", "visibility VARCHAR NOT NULL, shared_staff_ids JSON"])
def test_partial_or_widening_schema_not_accepted(declaration):
    before = [("table", "families", "families", "CREATE TABLE families(id INTEGER)"), ("table", "child_observation_logs", "child_observation_logs", "CREATE TABLE child_observation_logs(id INTEGER)")]
    after = [before[0], (*before[1][:3], f"CREATE TABLE child_observation_logs(id INTEGER, {declaration})")]
    assert not compatible(before, after)
