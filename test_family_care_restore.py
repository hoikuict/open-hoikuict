from contextlib import closing
import sqlite3

from sqlmodel import SQLModel

from family_care_service import TABLES
from restore_data import schema, schema_compatible, inspect_backup, prepare_copy
from restore_family_archive import compatible, upgrade_copy
import test_annual_restore
from test_restore_runtime import RestoreFixture


class FamilyCareRestoreTests(RestoreFixture):
    backup = test_annual_restore.AnnualRestoreTests.backup

    def test_old_backup_gains_only_empty_tables_on_copy(self):
        live=self.data/'hoikuict.db'
        with closing(sqlite3.connect(live)) as connection:
            for model in reversed(TABLES): connection.execute('DROP TABLE '+model.__tablename__)
        self.engine.dispose()
        backup=self.backup(legacy=True); source=backup/'db/hoikuict.db'; before=source.read_bytes()
        SQLModel.metadata.create_all(self.engine)
        live_before=live.read_bytes()
        assert schema_compatible(source,live)
        inspect_backup(self.paths,backup.name,str(self.actor_id))
        staged=prepare_copy(self.paths,backup.name,'family-care-legacy')/'data/hoikuict.db'
        upgrade_copy(staged,schema(live))
        with closing(sqlite3.connect(staged)) as connection:
            for model in TABLES: assert connection.execute('SELECT COUNT(*) FROM '+model.__tablename__).fetchone()[0]==0
            assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        assert source.read_bytes()==before and live.read_bytes()==live_before
        assert not schema_compatible(live,source)

    def test_partial_or_changed_table_schema_is_rejected(self):
        current=schema(self.data/'hoikuict.db')
        names={model.__tablename__ for model in TABLES}
        old=[row for row in current if row[2] not in names]
        assert compatible(old,current)
        partial=old+[row for row in current if row[2]=='family_care_audits']
        assert not compatible(partial,current)
        changed=[(*row[:3],row[3].replace('mode VARCHAR(16)','mode VARCHAR(99)')) if row[1]=='family_care_child_settings' else row for row in current]
        assert not compatible(changed,current)

    def test_family_records_survive_backup_copy(self):
        live=self.data/'hoikuict.db'
        with closing(sqlite3.connect(live)) as c:
            c.execute("INSERT INTO families(id,family_name,created_at,updated_at) VALUES(920,'架空家族','2026-01-01','2026-01-01')")
            c.execute("INSERT INTO family_care_certifications(family_id,effective_from,data,is_active,updated_at) VALUES(920,'2026-10-01','{}',1,'2026-10-01')")
            c.commit()
        backup=self.backup(); staged=prepare_copy(self.paths,backup.name,'family-care-saved')/'data/hoikuict.db'
        with closing(sqlite3.connect(staged)) as c:
            assert c.execute('SELECT family_id,data FROM family_care_certifications').fetchone()==(920,'{}')
