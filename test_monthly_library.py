"""Isolated integration tests; never open the nursery's working database."""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import child_records.models  # noqa: F401
import database
from csrf import CsrfTokenMiddleware, verify_csrf
from models import Child, Classroom
from plan_docs.auth_adapter import StaffUser, resolve_plan_docs_staff_user
from plan_docs.contracts import DocumentStatus, DocumentType, Role
from plan_docs.db_models import PlanDocumentRow, PlanRevisionRow
from plan_docs.models import PlanDocument, SectionBlock
from plan_docs.routers.monthly_library import router
from plan_docs.routers.documents import router as documents_router
from plan_docs.services.monthly_library import previous_months
from plan_docs.store import SqlModelDocumentRepository


class MonthlyLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.corpus = Path(self.temp.name) / "phrases.sqlite"
        with closing(sqlite3.connect(self.corpus)) as con:
            con.executescript('''
                CREATE TABLE source(id INTEGER PRIMARY KEY, rel_path TEXT);
                CREATE TABLE cell(id INTEGER PRIMARY KEY, source_id INTEGER, sheet TEXT);
                CREATE TABLE phrase(id INTEGER PRIMARY KEY, cell_id INTEGER, source_id INTEGER,
                    text TEXT, norm TEXT, age INTEGER, month INTEGER, year INTEGER,
                    item TEXT, section TEXT, ryoiki TEXT);
                INSERT INTO source VALUES(1, 'fictional/2025-10.xls');
                INSERT INTO cell VALUES(1, 1, 'Sheet1');
            ''')
            rows = [
                (1, "手洗いを楽しむ。ＡＢＣ", 1, "生活・健康", "個人別", None),
                (2, "手洗いを楽しむ。ＡＢＣ", 1, "生活・健康", "個人別", None),
                (3, "クラスの評価", 1, "評価・反省", "クラス全体", None),
                (4, "個人の評価", 1, "評価・反省", "個人別", None),
                (5, "食育の環境", 3, "環境構成", "食育", None),
                (6, "食育の項目", 3, "食育", "クラス全体", None),
                (7, "健康の援助", 3, "援助・配慮", "教育", "健康"),
                (8, "表現の援助", 3, "援助・配慮", "教育", "表現"),
                (9, "別年齢", 2, "生活・健康", "個人別", None),
                (10, "気持ちを受け止める", 3, "援助・配慮", "養護", "情緒の安定"),
            ]
            con.executemany("INSERT INTO phrase VALUES(?,1,1,?,?,?,10,2025,?,?,?)",
                            [(i, text, text, age, item, section, domain) for i,text,age,item,section,domain in rows])
            con.commit()
        self.corpus_bytes = self.corpus.read_bytes()
        self.env = patch.dict('os.environ', {
            "HOIKU_MONTHLY_LIBRARY_SOURCES": json.dumps({"test-nursery": {"id":"fixture", "path":str(self.corpus)}}),
            "HOIKUICT_ENV":"production", "HOIKUICT_SECRET_KEY":"monthly-library-test-only",
            "HOIKUICT_CSRF_ENFORCE":"1",
        })
        self.env.start()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread":False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.add_all([Classroom(id=1, name="A組"), Classroom(id=2,name="B組")])
            for i in (1,2):
                session.add(Child(id=i,last_name="架空",first_name=str(i),last_name_kana="カクウ",
                    first_name_kana=str(i),birth_date=date(2024,5,1),enrollment_date=date(2024,6,1),classroom_id=1))
            session.commit()
        self.user=StaffUser(role=Role.CAN_EDIT, actor_ref="staff:test",nursery_ref="test-nursery",
                            classroom_refs=("A組",),name="架空職員")
        self.app=FastAPI(dependencies=[Depends(verify_csrf)])
        self.app.add_middleware(CsrfTokenMiddleware)
        self.app.include_router(router,prefix="/plans")
        self.app.include_router(documents_router,prefix="/plans")
        self.app.dependency_overrides[resolve_plan_docs_staff_user]=lambda:self.user
        def session_override():
            with Session(self.engine) as session: yield session
        self.app.dependency_overrides[database.get_session]=session_override
        self.client=TestClient(self.app, base_url="https://testserver")
        self.client.get('/plans/monthly-library')
        self.client.headers['X-CSRF-Token']=self.client.cookies.get('hoikuict_csrf')

    def tearDown(self):
        self.assertEqual(self.corpus_bytes,self.corpus.read_bytes(),"phrase corpus must be read-only")
        self.client.close(); self.engine.dispose(); self.env.stop(); self.temp.cleanup()

    def context(self, month="2026-10", age=1, classroom=1):
        return self.client.get('/plans/monthly-library/context',params={
            "classroom_id":classroom,"target_month":month,"age":age})

    def payload(self, context, fields=None):
        return {key:context[key] for key in ('document_id','lock_version','classroom_id','target_month','age','owner_name')} | {
            'fields':fields if fields is not None else context['sheet']['fields']}

    def save(self,payload):
        return self.client.post('/plans/monthly-library/save',json=payload)

    def candidates(self, field, age=1, keyword="", classroom=1):
        return self.client.get('/plans/monthly-library/candidates',params={
            'classroom_id':classroom,'target_month':'2026-10','age':age,'field':field,'keyword':keyword})

    def test_empty_sheet_and_versions_and_calendar(self):
        context=self.context().json()
        self.assertEqual(context['sheet']['fields'],{})
        self.assertEqual([c['ref'] for c in context['sheet']['children']],['child:1','child:2'])
        self.assertEqual(context['sheet']['template_id'],'infant-1')
        self.assertIn('child:1:review',context['definitions'])
        group=self.context('2028-02',3).json()
        self.assertIn('event:29',group['definitions']); self.assertNotIn('event:30',group['definitions'])
        self.assertIn('group:food',group['definitions']); self.assertNotIn('group:food:goal',group['definitions'])
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(PlanDocumentRow)).all(),[])

    def test_search_scope_dedup_normalization_and_short_words(self):
        rows=self.candidates('child:1:life',keyword='手 abc').json()['items']
        self.assertEqual(len(rows),1); self.assertEqual(rows[0]['phrase_id'],2)
        self.assertEqual(rows[0]['relative_path'],'fictional/2025-10.xls')
        self.assertEqual(self.candidates('child:1:life',keyword='手 ない').json()['items'],[])
        self.assertEqual(self.candidates('child:1:review').json()['items'][0]['phrase_id'],4)
        self.assertEqual(self.candidates('common:review').json()['items'][0]['phrase_id'],3)
        self.assertEqual({o['phrase_id'] for o in self.candidates('group:food',3).json()['items']},{5,6})
        self.assertEqual(self.candidates('group:health:support',3).json()['items'][0]['phrase_id'],7)
        self.assertEqual(self.candidates('group:care:support',3).json()['items'][0]['phrase_id'],10)

    def test_save_roundtrip_sources_revision_and_conflict(self):
        context=self.context().json()
        fields={'child:1:life':{'body':'手入力\n○手洗いを楽しむ。ＡＢＣ',
            'origins':[{'source_key':'fixture','phrase_id':2}]},'child:2:play':{'body':'別の園児'}}
        response=self.save(self.payload(context,fields)); self.assertEqual(response.status_code,200,response.text)
        saved=response.json(); self.assertEqual(saved['lock_version'],1)
        origin=saved['sheet']['fields']['child:1:life']['origins'][0]
        self.assertEqual(origin['kind'],'original'); self.assertEqual(origin['cell_id'],1)
        self.assertEqual(self.context().json()['sheet']['fields'],saved['sheet']['fields'])
        stale=self.payload(saved,{'child:1:life':{'body':'変更'}})
        result=self.save(stale); self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.save(stale).status_code,409)
        self.assertEqual(self.save(self.payload(context,fields)).status_code,409)
        with Session(self.engine) as session:
            versions=session.exec(select(PlanRevisionRow)).all()
            self.assertEqual(len(versions),2)
            self.assertEqual(versions[0].snapshot['monthly_sheet']['fields']['child:2:play']['body'],'別の園児')
        document_id=saved['document_id']
        self.assertEqual(self.client.get(f'/plans/documents/{document_id}/edit',follow_redirects=False).status_code,303)
        detail=self.client.get(f'/plans/documents/{document_id}')
        self.assertEqual(detail.status_code,200,detail.text)
        self.assertIn('monthly-library-boot',detail.text)

    def test_reject_forged_fields_sources_and_foreign_document(self):
        context=self.context().json()
        for fields in ({'child:999:life':{'body':'wrong'}},
                       {'child:1:life':{'body':'wrong','origins':[{'source_key':'fixture','phrase_id':3}]}},
                       {'child:1:life':{'body':'wrong','origins':[{'source_key':'other','phrase_id':2}]}}):
            self.assertEqual(self.save(self.payload(context,fields)).status_code,422)
        saved=self.save(self.payload(context,{'common:goal':{'body':'目標'}})).json()
        payload=self.payload(saved,{}); payload['target_month']='2026-11'
        self.assertEqual(self.save(payload).status_code,404)
        self.user.nursery_ref='other'
        self.assertEqual(self.client.get('/plans/monthly-library',params={'document_id':saved['document_id']}).status_code,404)

    def test_auth_permissions_and_csrf(self):
        self.assertEqual(self.context(classroom=2).status_code,403)
        self.assertEqual(self.candidates('common:goal',classroom=2).status_code,403)
        payload=self.payload(self.context().json(),{})
        self.user.role=Role.VIEW_ONLY
        self.assertEqual(self.save(payload).status_code,403)
        self.user.role=Role.CAN_EDIT
        token=self.client.headers.pop('X-CSRF-Token')
        self.assertEqual(self.save(payload).status_code,403)
        self.client.headers['X-CSRF-Token']=token
        self.user.actor_ref=None
        self.assertEqual(self.client.get('/plans/monthly-library',follow_redirects=False).status_code,303)
        self.assertEqual(self.candidates('child:1:life').history[0].status_code,303)

    def test_history_cross_year_class_change_missing_and_legacy(self):
        self.assertEqual(previous_months('2027-01'),['2026-10','2026-11','2026-12'])
        self.save(self.payload(self.context().json(),{
            'child:1:life':{'body':'10月の計画'},'child:1:review':{'body':'10月の実施後反省'},
            'child:2:life':{'body':'他の園児'}})).json()
        with Session(self.engine) as session:
            child=session.get(Child,1); child.classroom_id=2; session.add(child);session.commit()
            repo=SqlModelDocumentRepository(session)
            repo.create(PlanDocument(id=0,document_type=DocumentType.INDIVIDUAL_PLAN,title='旧個人計画',
                status=DocumentStatus.DRAFT,nursery_ref='test-nursery',classroom_ref='A組',
                actor_ref='staff:test',owner_name='架空職員',target_month='2026-12',child_ref='child:1',
                sections=[SectionBlock('individual_goal_care','養護のねらい','元の項目',[],[])]))
        self.user.classroom_refs=('A組','B組')
        args={'classroom_id':2,'target_month':'2027-01','age':2,'child_ref':'child:1'}
        result=self.client.get('/plans/monthly-library/history',params=args).json()
        self.assertEqual(result['months'][0]['records'][0]['fields']['life']['body'],'10月の計画')
        self.assertEqual(result['months'][0]['records'][0]['fields']['review']['body'],'10月の実施後反省')
        self.assertEqual(result['months'][1]['records'],[])
        self.assertEqual(result['months'][2]['legacy'][0]['sections'][0]['title'],'養護のねらい')
        self.assertNotIn('他の園児',json.dumps(result,ensure_ascii=False))
        self.user.classroom_refs=('B組',)
        result=self.client.get('/plans/monthly-library/history',params=args).json()
        self.assertEqual(result['months'][0]['records'],[])
        args['child_ref']='child:2'
        self.assertEqual(self.client.get('/plans/monthly-library/history',params=args).status_code,404)

    def test_no_source_still_allows_manual_save_and_preserves_existing_sources(self):
        context=self.context().json()
        saved=self.save(self.payload(context,{'child:1:life':{'body':'原文','origins':[{'source_key':'fixture','phrase_id':2}]}})).json()
        with patch.dict('os.environ',{'HOIKU_MONTHLY_LIBRARY_SOURCES':'{}'}):
            self.assertEqual(self.candidates('child:1:life').status_code,503)
            fields={'child:1:life':{'body':'編集済み','origins':[{'source_key':'fixture','phrase_id':2}]}}
            self.assertEqual(self.save(self.payload(saved,fields)).status_code,200)

    def test_reviewed_document_is_readonly_and_unauthenticated_detail_hidden(self):
        saved=self.save(self.payload(self.context().json(),{'common:goal':{'body':'目標'}})).json()
        with Session(self.engine) as session:
            row=session.get(PlanDocumentRow,saved['document_id']);row.status='approved';session.add(row);session.commit()
        self.assertFalse(self.context().json()['editable'])
        self.assertEqual(self.save(self.payload(saved,{})).status_code,409)
        self.user.actor_ref=None
        self.assertEqual(self.client.get(f"/plans/documents/{saved['document_id']}").status_code,404)

    def test_roster_additions_keep_existing_children_and_empty_month_is_missing(self):
        saved=self.save(self.payload(self.context().json(),{'child:1:life':{'body':'元の入力'}})).json()
        with Session(self.engine) as session:
            child=session.get(Child,1); child.classroom_id=2; session.add(child)
            session.add(Child(id=3,last_name='追加',first_name='園児',last_name_kana='ツイカ',
                first_name_kana='エンジ',birth_date=date(2025,1,1),enrollment_date=date(2026,10,5),classroom_id=1))
            session.commit()
        context=self.context().json()
        self.assertEqual({c['ref'] for c in context['sheet']['children']},{'child:1','child:2','child:3'})
        self.assertEqual(context['sheet']['fields']['child:1:life']['body'],'元の入力')
        # A class draft without any text for child 2 is not that child's record.
        result=self.client.get('/plans/monthly-library/history',params={
            'classroom_id':1,'target_month':'2026-11','age':1,'child_ref':'child:2'}).json()
        self.assertEqual(result['months'][-1]['records'],[])
        with Session(self.engine) as session:
            row=session.get(PlanDocumentRow,saved['document_id']);row.status='approved';session.add(row);session.commit()
        self.assertNotIn('child:3',{c['ref'] for c in self.context().json()['sheet']['children']})

    def test_candidate_pagination_and_unknown_age_exclusion(self):
        # Synthetic corpus mutation is setup, never an application write.
        with closing(sqlite3.connect(self.corpus)) as con:
            con.executemany('INSERT INTO phrase VALUES(?,1,1,?,?,1,10,2025,?,?,NULL)',
                [(100+i,f'文例{i}',f'文例{i}','生活・健康','個人別') for i in range(60)])
            con.execute("INSERT INTO phrase VALUES(999,1,1,'年齢なし','年齢なし',NULL,10,2025,'生活・健康','個人別',NULL)")
            con.commit()
        self.corpus_bytes=self.corpus.read_bytes()
        first=self.candidates('child:1:life').json()
        response=self.client.get('/plans/monthly-library/candidates',params={
            'classroom_id':1,'target_month':'2026-10','age':1,'field':'child:1:life','offset':50})
        second=response.json()
        self.assertTrue(first['has_more']);self.assertFalse(second['has_more'])
        ids=[row['phrase_id'] for row in first['items']+second['items']]
        self.assertEqual(len(ids),61);self.assertEqual(len(set(ids)),61);self.assertNotIn(999,ids)

    def test_additive_migration_is_repeatable_and_preserves_legacy(self):
        engine=create_engine('sqlite://')
        with engine.begin() as con:
            con.exec_driver_sql('CREATE TABLE plan_documents(id INTEGER PRIMARY KEY, title TEXT)')
            con.exec_driver_sql("INSERT INTO plan_documents VALUES(1, 'legacy')")
        with patch.object(database,'engine',engine):
            database._migrate_monthly_sheet_columns(); database._migrate_monthly_sheet_columns()
        with engine.connect() as con:
            row=con.exec_driver_sql('SELECT title,monthly_sheet,monthly_sheet_key FROM plan_documents').one()
            self.assertEqual(tuple(row),('legacy',None,None))
        engine.dispose()


def test_monthly_sheet_backup_roundtrip(tmp_path):
    from scripts.backup_runtime import BackupConfig, create_backup
    from scripts.backup_recovery import prepare_restore
    from test_backup_support import full_databases

    main, facility = tmp_path / 'source' / 'hoikuict.db', tmp_path / 'source' / 'facility.sqlite'
    storage = tmp_path / 'storage'
    storage.mkdir()
    full_databases(main, facility)
    engine = create_engine(f'sqlite:///{main}')
    sheet = {'schema_version':1, 'template_id':'infant-1', 'template_version':'2026-09-27.1',
        'age':1, 'classroom_id':1, 'children':[{'ref':'child:1','name':'架空 園児','birth_date':'2023-01-01'}],
        'fields':{'child:1:life':{'body':'架空の計画', 'origins':[{'source_key':'fixture', 'phrase_id':1,
                                                                'kind':'original','text':'架空の原文'}]}}}
    with Session(engine) as session:
        SqlModelDocumentRepository(session).create(PlanDocument(id=0, document_type=DocumentType.MONTHLY_PLAN,
            status=DocumentStatus.DRAFT, title='架空月案',nursery_ref='synthetic',classroom_ref='架空組',
            actor_ref='staff:test',owner_name='架空職員',sections=[],target_month='2026-10',monthly_sheet=sheet))
    engine.dispose()
    config = BackupConfig(output_root=tmp_path/'sets',database_url=f'sqlite:///{main}',facility_db=facility,
        storage_root=storage,git_sha='a'*40,app_image='sha256:'+'b'*64,compose_sha256='c'*64,
        cloudflared_image='cloudflared@sha256:'+'d'*64,environment='test',facility_ref='synthetic',
        quiesced=True,recovery_kit_ref='kit-test',actor_ref='operator-test',baseline_ref='baseline-test')
    backup = create_backup(config)
    destination = tmp_path/'restored'
    prepare_restore(backup,destination,incident_ref='monthly-roundtrip',isolated=True)
    restored = destination/'runtime/data/hoikuict.db'
    with closing(sqlite3.connect(main)) as original, closing(sqlite3.connect(restored)) as recovered:
        for query in ('SELECT monthly_sheet,monthly_sheet_key FROM plan_documents',
                      'SELECT snapshot,content_hash FROM plan_revisions'):
            assert original.execute(query).fetchall() == recovered.execute(query).fetchall()


if __name__=='__main__':
    unittest.main()
