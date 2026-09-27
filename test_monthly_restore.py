"""Keep old backups usable after the monthly-sheet migration, without rewriting them."""
from contextlib import closing
import json
import os
import sqlite3
from unittest.mock import patch

import pytest
from sqlmodel import Session
import database
import child_records.models  # noqa: F401
from plan_docs.db_models import PlanDocumentRow
from restore_data import inspect_backup, prepare_copy, schema, schema_compatible
from restore_family_archive import compatible, upgrade_copy
from scripts.backup_runtime import BackupConfig, create_backup
from test_restore_runtime import CURRENT_SHA, RestoreFixture


class MonthlyRestoreTests(RestoreFixture):
    def backup(self, *, legacy=False):
        # The production branch still uses format 1; development also validates
        # recovery-kit provenance and its versioned schema contract.
        extra = {}
        if 'schema_contract' in BackupConfig.__dataclass_fields__:
            extra.update(recovery_kit_ref='test-kit',actor_ref='test-operator',baseline_ref='test-baseline')
            if legacy:
                extra['schema_contract'] = 'staff-sessions-20260920'
        return create_backup(BackupConfig(output_root=self.paths.backups,
            database_url=os.environ['HOIKUICT_DATABASE_URL'],facility_db=self.data/'facility.sqlite',
            storage_root=self.storage,git_sha=CURRENT_SHA,app_image='sha256:'+'e'*64,compose_sha256='c'*64,
            cloudflared_image='sha256:'+'f'*64,facility_ref='synthetic',quiesced=True,**extra))

    def add_document(self, sheet=None, key=None):
        with Session(self.engine) as session:
            session.add(PlanDocumentRow(document_type='monthly_plan',status='draft',title='Fictional plan',
                nursery_ref='synthetic',classroom_ref='Fictional class',owner_name='Fictional author',
                sections=[{'body':'Existing plan text'}],monthly_sheet=sheet,monthly_sheet_key=key))
            session.commit()

    def test_pre_monthly_backup_is_inspected_and_upgraded_only_on_copy(self):
        self.add_document()
        live=self.data/'hoikuict.db'
        with closing(sqlite3.connect(live)) as connection:
            connection.execute('DROP INDEX IF EXISTS ix_plan_documents_monthly_sheet_key')
            connection.execute('DROP INDEX IF EXISTS uq_monthly_sheet_key')
            connection.execute('ALTER TABLE plan_documents DROP COLUMN monthly_sheet')
            connection.execute('ALTER TABLE plan_documents DROP COLUMN monthly_sheet_key')
        backup=self.backup(legacy=True)
        original=(backup/'db/hoikuict.db').read_bytes()
        with patch.object(database,'engine',self.engine):
            database._migrate_monthly_sheet_columns()
            database._migrate_monthly_sheet_columns()
        live_before=live.read_bytes()
        assert schema_compatible(backup/'db/hoikuict.db',live)
        inspect_backup(self.paths,backup.name,str(self.actor_id))
        staged=prepare_copy(self.paths,backup.name,'monthly-legacy')/'data/hoikuict.db'
        assert (backup/'db/hoikuict.db').read_bytes()==original
        assert live.read_bytes()==live_before
        assert schema_compatible(staged,live)
        with closing(sqlite3.connect(staged)) as connection:
            row=connection.execute('SELECT sections,monthly_sheet,monthly_sheet_key FROM plan_documents').fetchone()
            assert json.loads(row[0])==[{'body':'Existing plan text'}] and row[1:]==(None,None)
            assert not connection.execute('PRAGMA foreign_key_check').fetchall()
        upgrade_copy(staged,schema(live))
        assert not compatible(schema(live),schema(backup/'db/hoikuict.db'))

    def test_saved_monthly_body_and_provenance_survive_backup_and_prepare(self):
        sheet={'schema_version':1,'fields':{'common:goal':{'body':'Saved body','origins':[
            {'kind':'ai','model':'local-model','text':'Generated original','reference_mode':'conditions_only'},
            {'kind':'original','source_key':'fictional','phrase_id':1,'text':'Original phrase'}]}}}
        self.add_document(sheet,'fictional-key')
        with patch.object(database,'engine',self.engine): database._migrate_monthly_sheet_columns()
        backup=self.backup()
        original=(backup/'db/hoikuict.db').read_bytes()
        inspect_backup(self.paths,backup.name,str(self.actor_id))
        staged=prepare_copy(self.paths,backup.name,'monthly-saved')/'data/hoikuict.db'
        with closing(sqlite3.connect(staged)) as connection:
            row=connection.execute('SELECT monthly_sheet,monthly_sheet_key FROM plan_documents').fetchone()
            assert json.loads(row[0])==sheet and row[1]=='fictional-key'
        assert (backup/'db/hoikuict.db').read_bytes()==original


@pytest.mark.parametrize('declaration,index',[
    ('monthly_sheet JSON',None),
    ('monthly_sheet JSON,monthly_sheet_key VARCHAR',None),
    ("monthly_sheet JSON DEFAULT '{}',monthly_sheet_key VARCHAR",'valid'),
    ('monthly_sheet JSON NOT NULL,monthly_sheet_key VARCHAR','valid'),
    ('monthly_sheet TEXT,monthly_sheet_key VARCHAR','valid'),
    ('monthly_sheet JSON,monthly_sheet_key VARCHAR,unrelated TEXT','valid'),
    ('monthly_sheet JSON,monthly_sheet_key VARCHAR','nonunique'),
    ('monthly_sheet JSON,monthly_sheet_key VARCHAR','wrongpredicate'),
])
def test_partial_or_unrelated_monthly_schema_is_rejected(declaration,index):
    old=[('table','families','families','CREATE TABLE families(id INTEGER)'),
         ('table','plan_documents','plan_documents','CREATE TABLE plan_documents(id INTEGER)')]
    new=[old[0],(*old[1][:3],f'CREATE TABLE plan_documents(id INTEGER,{declaration})')]
    if index:
        sql='CREATE UNIQUE INDEX uq_monthly_sheet_key ON plan_documents(monthly_sheet_key) WHERE monthly_sheet_key IS NOT NULL'
        if index=='nonunique': sql=sql.replace('UNIQUE ','')
        if index=='wrongpredicate': sql=sql.replace('IS NOT NULL','IS NULL')
        new.append(('index','uq_monthly_sheet_key','plan_documents',sql))
    assert not compatible(old,new)


def test_fresh_and_migrated_index_forms_are_equivalent():
    base=[('table','families','families','CREATE TABLE families(id INTEGER)'),
          ('table','plan_documents','plan_documents','CREATE TABLE plan_documents(id INTEGER,monthly_sheet JSON,monthly_sheet_key VARCHAR)')]
    fresh=[*base,('index','ix_plan_documents_monthly_sheet_key','plan_documents',
                 'CREATE UNIQUE INDEX ix_plan_documents_monthly_sheet_key ON plan_documents (monthly_sheet_key)')]
    migrated=[*base,('index','uq_monthly_sheet_key','plan_documents',
                    'CREATE UNIQUE INDEX uq_monthly_sheet_key ON plan_documents(monthly_sheet_key) WHERE monthly_sheet_key IS NOT NULL')]
    assert compatible(fresh,migrated) and compatible(migrated,fresh)
