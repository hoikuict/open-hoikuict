from contextlib import closing
import sqlite3

from sqlmodel import SQLModel
import child_records.models  # noqa: F401 -- complete metadata for restore fixtures
from models import ParentContactFieldSetting, ParentContactFieldAudit
from restore_data import schema, schema_compatible, prepare_copy
from restore_family_archive import compatible, upgrade_copy
import test_annual_restore
from test_restore_runtime import RestoreFixture

TABLES = (ParentContactFieldSetting, ParentContactFieldAudit)


class ParentContactFieldsRestoreTests(RestoreFixture):
    backup = test_annual_restore.AnnualRestoreTests.backup

    def test_old_backup_adds_only_empty_settings_on_copy(self):
        live = self.data / 'hoikuict.db'
        with closing(sqlite3.connect(live)) as connection:
            for model in reversed(TABLES):
                connection.execute('DROP TABLE ' + model.__tablename__)
        self.engine.dispose()
        backup = self.backup()
        source = backup / 'db/hoikuict.db'
        before = source.read_bytes()
        SQLModel.metadata.create_all(self.engine)
        live_before = live.read_bytes()
        assert schema_compatible(source, live)
        staged = prepare_copy(self.paths, backup.name, 'parent-fields-legacy') / 'data/hoikuict.db'
        upgrade_copy(staged, schema(live))
        with closing(sqlite3.connect(staged)) as connection:
            for model in TABLES:
                assert connection.execute('SELECT COUNT(*) FROM ' + model.__tablename__).fetchone()[0] == 0
            assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        assert source.read_bytes() == before and live.read_bytes() == live_before
        assert not schema_compatible(live, source)

    def test_partial_or_modified_tables_are_rejected(self):
        current = schema(self.data / 'hoikuict.db')
        names = {model.__tablename__ for model in TABLES}
        old = [row for row in current if row[2] not in names]
        assert compatible(old, current)
        assert not compatible(old + [row for row in current if row[2] == 'parent_contact_field_settings'], current)
        modified = [(*row[:3], row[3].replace('revision INTEGER', 'revision VARCHAR'))
                    if row[1] == 'parent_contact_field_settings' else row for row in current]
        assert not compatible(modified, current)
