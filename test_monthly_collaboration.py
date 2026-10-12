"""Production routes, real assignments and two independent staff identities."""
from datetime import date
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from sqlmodel import Session, select

from models import StaffClassroomAssignment, User
from plan_docs.auth_adapter import StaffUser
from plan_docs.contracts import Role, DocumentStatus, DocumentType
from plan_docs.db_models import PlanDocumentRow
from plan_docs.models import PlanDocument
from plan_docs.routers.plans import router as plans_router
from plan_docs.routers.bunrei import router as bunrei_router
from plan_docs.services.monthly_merge import wire_cell
from plan_docs.store import SqlModelDocumentRepository
import test_monthly_library as fixtures


class MonthlyCollaborationTests(TestCase):
    def setUp(self):
        self.fixture = fixtures.MonthlyLibraryTests()
        self.fixture.setUp()
        self.f = self.fixture
        self.f.app.include_router(plans_router, prefix='/plans')
        self.f.app.include_router(bunrei_router, prefix='/plans')
        self.a = self.f.user
        self.b = self.staff('補助担当', assignments=[(1, date(2026, 10, 1), date(2026, 10, 31))])
        self.presence_path = patch('plan_docs.services.monthly_presence.cache_path',
                                   return_value=Path(self.f.temp.name) / 'presence.sqlite')
        self.presence_path.start()

    def tearDown(self):
        self.presence_path.stop()
        self.f.tearDown()

    def staff(self, name, role='can_edit', assignments=()):
        identity = uuid4()
        with Session(self.f.engine) as session:
            session.add(User(id=identity, email=str(identity)+'@example.test', display_name=name, staff_role=role))
            session.commit()
            for classroom, start, end in assignments:
                session.add(StaffClassroomAssignment(staff_user_id=identity, classroom_id=classroom,
                                                     starts_on=start, ends_on=end))
            session.commit()
        return StaffUser(role=Role(role), user_id=identity, name=name, nursery_ref=self.a.nursery_ref,
                         actor_ref='staff:'+str(identity), classroom_refs=('A組', 'B組'))

    def context(self, user=None, **kwargs):
        self.f.user = user or self.a
        response = self.f.context(**kwargs)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def payload(self, context, fields=None):
        return self.f.payload(context, {k:wire_cell(v) for k,v in
            (context['sheet']['fields'] if fields is None else fields).items()}) | {'base_token':context['base_token']}

    def save(self, context, fields=None, user=None, **extra):
        self.f.user = user or self.a
        return self.f.save(self.payload(context, fields) | extra)

    def saved(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_assignments_role_admin_and_inclusive_month_boundaries(self):
        cases = [('admin', [], False), ('can_edit', [], False),
                 ('view_only', [(1,date(2026,10,1),None)], False),
                 ('admin', [(1,date(2026,10,31),date(2026,10,31))], True),
                 ('can_edit', [(1,date(2026,9,1),date(2026,10,1))], True),
                 ('can_edit', [(1,date(2026,11,1),None)], False),
                 ('can_edit', [(2,date(2026,10,1),None)], False)]
        for role, assignments, expected in cases:
            with self.subTest(role=role, assignments=assignments):
                staff = self.staff('架空職員', role, assignments)
                context = self.context(staff)
                self.assertEqual(context['editable'], expected)
                self.assertEqual(self.save(context, {'common:goal':{'body':'入力'}}, staff).status_code, 200 if expected else 403)

    def test_revocation_rechecks_direct_save_generation_export_and_keeps_db(self):
        context = self.context(self.b)
        with Session(self.f.engine) as session:
            for row in session.exec(select(StaffClassroomAssignment).where(StaffClassroomAssignment.staff_user_id==self.b.user_id)):
                session.delete(row)
            session.commit()
        self.assertEqual(self.save(context, {}, self.b).status_code,403)
        common = {k:context[k] for k in ('document_id','classroom_id','target_month','age')}
        self.assertEqual(self.f.client.post('/plans/monthly-library/generate',json=common|{'field':'common:goal'}).status_code,403)
        self.assertEqual(self.f.client.post('/plans/monthly-library/export',json=common|{'kind':'xlsx','mode':'current','fields':{},'owner_name':'入力'}).status_code,403)
        with Session(self.f.engine) as session:
            self.assertEqual(session.exec(select(PlanDocumentRow)).all(),[])

    def test_saved_export_remains_available_to_unassigned(self):
        saved=self.saved(self.save(self.context(),{'common:goal':{'body':'保存'}}))
        user=self.staff('未割当管理者','admin')
        self.assertFalse(self.context(user)['editable'])
        common={k:saved[k] for k in ('document_id','classroom_id','target_month','age')}
        response=self.f.client.post('/plans/monthly-library/export',json=common|{'kind':'xlsx','mode':'saved'})
        self.assertEqual(response.status_code,200)

    def test_different_cells_merge_from_durable_revision(self):
        a=self.saved(self.save(self.context(),{})); b=self.context(self.b)
        self.saved(self.save(b,{'common:home':{'body':'補助担当の入力'}},self.b))
        saved=self.saved(self.save(a,{'common:goal':{'body':'主担当の入力'}}))
        self.assertEqual(saved['sheet']['fields']['common:home']['body'],'補助担当の入力')
        self.assertEqual(saved['sheet']['fields']['common:goal']['body'],'主担当の入力')
        self.assertEqual(saved['merged_remote_fields'],['家庭との連携'])

    def test_conflict_is_atomic_and_resolution_rechecks_new_revision(self):
        a=self.saved(self.save(self.context(),{}));b=self.context(self.b)
        self.saved(self.save(b,{'common:goal':{'body':'相手'}},self.b))
        response=self.save(a,{'common:goal':{'body':'自分'},'common:home':{'body':'未保存の別欄'}})
        self.assertEqual(response.status_code,409)
        detail=response.json()['detail'];self.assertEqual(detail['kind'],'cell_conflict')
        self.assertEqual([c['key'] for c in detail['conflicts']],['common:goal'])
        self.assertNotIn('common:home',self.context()['sheet']['fields'])
        self.saved(self.save(self.context(self.b),{'common:goal':{'body':'相手の再更新'}},self.b))
        self.assertEqual(self.save(detail['latest'],{'common:goal':{'body':'選んだ文'}}).status_code,409)

    def test_empty_deletion_owner_and_identical_changes(self):
        a=self.saved(self.save(self.context(),{'common:goal':{'body':'元の文'}}));b=self.context(self.b)
        self.saved(self.save(b,{'common:goal':{'body':'変更'}},self.b))
        self.assertEqual(self.save(a,{}).status_code,409)
        self.saved(self.save(a,{'common:goal':{'body':'変更'}}))
        a=self.context();b=self.context(self.b)
        self.saved(self.save(b,user=self.b,owner_name='共同担任'))
        saved=self.saved(self.save(a,{'common:goal':{'body':'変更'},'common:home':{'body':'連携'}}))
        self.assertEqual(saved['owner_name'],'共同担任')
        response=self.save(a,owner_name='別の担任名')
        self.assertEqual(response.json()['detail']['conflicts'][0]['key'],'@owner')

    def test_two_initial_creators_share_one_document(self):
        a=self.context();b=self.context(self.b)
        first=self.saved(self.save(b,{'common:home':{'body':'補助'}},self.b))
        second=self.saved(self.save(a,{'common:goal':{'body':'主担当'}}))
        self.assertEqual(first['document_id'],second['document_id'])
        self.assertEqual(len(second['sheet']['fields']),2)
        with Session(self.f.engine) as session:
            self.assertEqual(len(session.exec(select(PlanDocumentRow)).all()),1)

    def test_signed_baseline_cannot_move_between_actor_scope_or_document(self):
        a=self.context()
        self.assertEqual(self.save(a,{},self.b).status_code,409)
        self.assertEqual(self.save(a,{},target_month='2026-11').status_code,409)
        self.assertEqual(self.save(a,{},base_token=a['base_token']+'x').status_code,409)
        self.assertEqual(self.save(a,{},classroom_id=2).status_code,409)

    def test_provenance_survives_peer_clear_and_unavailable_corpus(self):
        fields={'child:1:life':{'body':'原文','origins':[{'source_key':'fixture','phrase_id':2}]}}
        a=self.saved(self.save(self.context(),fields));b=self.context(self.b)
        self.saved(self.save(b,{},self.b))
        with patch.dict('os.environ',{'HOIKU_MONTHLY_LIBRARY_SOURCES':'{}'}):
            result=self.save(a,fields|{'common:home':{'body':'家庭'}})
        self.assertEqual(result.status_code,200,result.text)
        self.assertNotIn('child:1:life',result.json()['sheet']['fields'])

    def heartbeat(self, user, tab, **changes):
        self.f.user=user
        return self.f.client.post('/plans/monthly-library/presence',json={
            'classroom_id':1,'target_month':'2026-10','age':1,'tab_id':str(tab),
            'field':'common:goal','state':'typing'}|changes)

    def test_presence_scope_expiry_same_user_tabs_and_no_body(self):
        tab_a,tab_b,tab_c=uuid4(),uuid4(),uuid4()
        with patch('plan_docs.services.monthly_presence.time.time',return_value=1000):
            self.assertEqual(self.heartbeat(self.a,tab_a).status_code,200)
            data=self.heartbeat(self.b,tab_b).json()
            self.assertEqual(data['peers'][0]['name'],self.a.name)
            self.assertNotIn('body',str(data))
            same=self.heartbeat(self.a,tab_c).json()
            self.assertTrue(any(p['self'] for p in same['peers']))
            self.assertEqual(self.heartbeat(self.b,tab_b,age=2).json()['peers'],[])
            self.assertEqual(self.heartbeat(self.b,tab_b,field='child:999:life').status_code,422)
        with patch('plan_docs.services.monthly_presence.time.time',return_value=1061):
            self.assertEqual(self.heartbeat(self.b,tab_b).json()['peers'],[])

    def test_presence_revoked_staff_disappears_and_readonly_does_not_register(self):
        a,b=uuid4(),uuid4()
        self.heartbeat(self.b,b)
        with Session(self.f.engine) as session:
            staff=session.get(User,self.b.user_id);staff.is_active=False;session.add(staff);session.commit()
        self.assertEqual(self.heartbeat(self.a,a).json()['peers'],[])
        viewer=self.staff('閲覧のみ','view_only',[(1,date(2026,1,1),None)])
        self.heartbeat(viewer,uuid4())
        self.assertEqual(self.heartbeat(self.a,a).json()['peers'],[])
        self.heartbeat(self.a,a,state='leave')
        self.assertEqual(self.heartbeat(viewer,uuid4()).json()['peers'],[])

    def test_review_transition_rejects_stale_body_but_rejected_can_edit(self):
        a=self.saved(self.save(self.context(),{}))
        with Session(self.f.engine) as session:
            repo=SqlModelDocumentRepository(session)
            repo.update_status(a['document_id'],DocumentStatus.IN_REVIEW,expected_lock_version=1,actor_ref=self.a.actor_ref)
        self.assertFalse(self.context()['editable'])
        self.assertEqual(self.save(a,{'common:goal':{'body':'入力'}}).status_code,409)
        with Session(self.f.engine) as session:
            repo=SqlModelDocumentRepository(session)
            repo.update_status(a['document_id'],DocumentStatus.REJECTED,expected_lock_version=2,actor_ref=self.a.actor_ref,comment="再確認")
        self.assertTrue(self.context()['editable'])

    def test_legacy_creation_and_update_require_assignments_admin_has_no_bypass(self):
        user=self.staff('未担当管理者','admin');self.f.user=user
        response=self.f.client.post('/plans/monthly-plans',data={'target_month':'2026-10','classroom_ref':'A組','owner_name':'担任'})
        self.assertEqual(response.status_code,403)
        with patch('plan_docs.routers.bunrei._ensure_available'):
            response=self.f.client.post('/plans/bunrei/monthly',data={'target_month':'2026-10','classroom_ref':'A組'})
        self.assertEqual(response.status_code,403)
        with Session(self.f.engine) as session:
            repo=SqlModelDocumentRepository(session)
            doc=repo.create(PlanDocument(id=0,document_type=DocumentType.MONTHLY_PLAN,title='旧月案',
                status=DocumentStatus.DRAFT,nursery_ref=self.a.nursery_ref,classroom_ref='A組',
                actor_ref=self.a.actor_ref,owner_name='担任',target_month='2026-10',sections=[]))
        self.assertEqual(self.f.client.get(f'/plans/documents/{doc.id}/edit').status_code,403)
        self.assertEqual(self.f.client.post(f'/plans/documents/{doc.id}',data={'lock_version':'1','owner_name':'変更'}).status_code,403)
        self.f.user=self.a
        self.assertEqual(self.f.client.get(f'/plans/documents/{doc.id}/edit').status_code,200)


    def test_overlapping_database_writes_retry_without_losing_other_cell(self):
        import sqlite3
        from contextlib import closing
        from plan_docs.routers import monthly_library as monthly
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier, Lock
        from sqlmodel import create_engine
        path=Path(self.f.temp.name)/'concurrent.sqlite'
        with self.f.engine.connect() as source, closing(sqlite3.connect(path)) as target:
            source.connection.driver_connection.backup(target)
        self.f.engine.dispose()
        self.f.engine=create_engine('sqlite:///'+path.as_posix(),connect_args={'check_same_thread':False})
        with self.f.engine.connect() as connection:
            connection.exec_driver_sql('PRAGMA journal_mode=WAL')
        context=self.saved(self.save(self.context(),{}))
        barrier,lock=Barrier(2),Lock()
        entered=0
        original=monthly._begin_snapshot
        def synchronized(repo,*args,**kwargs):
            nonlocal entered
            with lock:
                if kwargs.get("write"):entered+=1
                wait=bool(kwargs.get("write")) and entered<=2
            if wait:barrier.wait(timeout=10)
            return original(repo,*args,**kwargs)
        payloads=[self.payload(context,{key:{'body':key}}) for key in ('common:goal','common:home')]
        with patch.object(monthly,'_begin_snapshot',synchronized),ThreadPoolExecutor(2) as pool:
            responses=list(pool.map(self.f.save,payloads))
        self.assertEqual([r.status_code for r in responses],[200,200],[r.text for r in responses])
        self.assertEqual(set(self.context()['sheet']['fields']),{'common:goal','common:home'})
