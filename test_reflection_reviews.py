"""Real SQLite/HTTP workflow tests with fictional staff and isolated source data."""
from dataclasses import replace
from contextlib import closing
import sqlite3
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from models import Classroom, User, StaffClassroomAssignment
from plan_docs.contracts import DocumentStatus, DocumentType, Role
from plan_docs.db_models import PlanDocumentRow, PlanDailyReflectionRow
from plan_docs.db_models import PlanReflectionReviewRow as Review
from plan_docs.db_models import PlanReflectionNotificationRow as Notification
from plan_docs.models import PlanDocument
from plan_docs.services import reflection_reviews as service
from plan_docs.store import SqlModelDocumentRepository
import test_annual_library as annual_tests


class ReflectionReviewTests(unittest.TestCase):
    setUp = annual_tests.AnnualLibraryTests.setUp
    tearDown = annual_tests.AnnualLibraryTests.tearDown
    preview = annual_tests.AnnualLibraryTests.preview
    payload = annual_tests.AnnualLibraryTests.payload
    save = annual_tests.AnnualLibraryTests.save

    def actors(self):
        with Session(self.engine) as s:
            teacher = s.exec(select(User)).first()
            admin = User(email="review-admin@example.invalid", display_name="見本管理者", staff_role="admin")
            s.add(admin); s.commit(); s.refresh(admin)
            self.editor = replace(self.user, actor_ref=f"staff:{teacher.id}", user_id=teacher.id)
            self.admin = replace(self.editor, role=Role.ADMIN, actor_ref=f"staff:{admin.id}", user_id=admin.id, name=admin.display_name)
        self.user = self.editor

    def post(self, path, status=200, **kwargs):
        response = self.client.post(path, follow_redirects=False, **kwargs)
        self.assertEqual(response.status_code, status, response.text)
        return response

    def saved_period(self, doc_id, period=0, version=0, values=None, status=200):
        return self.post(f"/plans/documents/{doc_id}/reflections", status, json={"entries":[
            {"period":period, "version":version, "values":values or ["生活の反省", "遊びの反省"]}]})

    def test_annual_full_workflow_preserves_plan_and_review_history(self):
        self.actors()
        boot = self.save(self.payload(self.preview())); doc_id = boot['document_id']
        with Session(self.engine) as s:
            repo = SqlModelDocumentRepository(s)
            repo.update_status(doc_id, DocumentStatus.IN_REVIEW, actor_ref=self.editor.actor_ref, actor_name=self.editor.name, expected_lock_version=repo.lock_version(doc_id))
            repo.update_status(doc_id, DocumentStatus.APPROVED, actor_ref=self.admin.actor_ref, actor_name=self.admin.name, expected_lock_version=repo.lock_version(doc_id))
            head_before = repo.head(doc_id).model_dump()
        result = self.saved_period(doc_id).json()['0']
        with Session(self.engine) as s:
            self.assertEqual(s.exec(select(Review)).all(), [])
            self.assertEqual(s.exec(select(Notification)).all(), [])
        confirm = self.client.get(f'/plans/documents/{doc_id}/reflections/0/confirm')
        self.assertIn('生活の反省', confirm.text); self.assertIn('管理者へ承認を依頼', confirm.text)
        url = self.post(f'/plans/documents/{doc_id}/reflections/0/request', 303, data={'version': result['version']}).headers['location']
        self.assertEqual(self.post(f'/plans/documents/{doc_id}/reflections/0/request', 303, data={'version':result['version']}).headers['location'], url)
        self.saved_period(doc_id, version=2, values=['上書き不可', ''], status=409)
        self.saved_period(doc_id, period=1, values=['別の期', ''])
        with Session(self.engine) as s:
            self.assertEqual(len(s.exec(select(Review)).all()), 1)
            queue, notes = service.portal_items(s, self.admin.user_id, self.admin.nursery_ref, True)
            self.assertEqual(len(queue), 1); self.assertEqual(len(notes), 1)
            open_url = notes[0].open_url
        self.post(url, 403, data={'action':'approve'})
        self.post(open_url, 404)
        self.user = self.admin; self.post(open_url, 303)
        with Session(self.engine) as s:
            queue, notes = service.portal_items(s, self.admin.user_id, self.admin.nursery_ref, True)
            self.assertEqual(len(queue), 1); self.assertIsNotNone(notes[0].read_at)
        self.post(url, 422, data={'action':'return'})
        self.post(url, 303, data={'action':'return','comment':'援助の振り返りを追記してください'})
        self.post(url, 409, data={'action':'approve'})
        with Session(self.engine) as s:
            queue, _ = service.portal_items(s, self.admin.user_id, self.admin.nursery_ref, True)
            self.assertEqual(queue, [])
            _, notes = service.portal_items(s, self.editor.user_id, self.editor.nursery_ref)
            self.assertEqual(notes[0].decision_status, 'rejected')
        self.user = self.editor
        result = self.saved_period(doc_id, version=3, values=['追記した生活', '遊び']).json()['0']
        url2 = self.post(f'/plans/documents/{doc_id}/reflections/0/request',303,data={'version':result['version']}).headers['location']
        self.user = self.admin; self.post(url2,303,data={'action':'approve'})
        self.user = self.editor; self.post(url2,303,data={'action':'revise'})
        with Session(self.engine) as s:
            reviews = s.exec(select(Review).order_by(Review.id)).all()
            self.assertEqual([r.status for r in reviews], ['returned', 'approved'])
            self.assertEqual(reviews[0].snapshot['values'], ['生活の反省','遊びの反省'])
            self.assertEqual(reviews[1].snapshot['values'], ['追記した生活','遊び'])
            self.assertEqual(s.get(PlanDocumentRow, doc_id).status, 'approved')
            self.assertEqual(SqlModelDocumentRepository(s).head(doc_id).model_dump(), head_before)

    def test_creation_metadata_and_new_year_blank(self):
        boot = self.preview()
        self.assertEqual(boot['owner_name'], '今年の担任')
        self.assertEqual(boot['reflection'], [['','']]*4)
        saved = self.save(self.payload(boot)); doc_id = saved['document_id']
        self.saved_period(doc_id)
        with Session(self.engine) as s:
            classroom=s.get(Classroom,1); classroom.name='変更後のA組'; s.add(classroom)
            teacher=s.exec(select(User)).first(); teacher.display_name='後から変更した担任'; s.add(teacher); s.commit()
        self.user = replace(self.user, classroom_refs=('変更後のA組',))
        reopened=self.preview(document_id=doc_id)
        self.assertEqual(reopened['classroom_name'], 'A組'); self.assertEqual(reopened['owner_name'], '今年の担任')
        self.assertIn('今年の担任', self.client.get(f'/plans/documents/{doc_id}').text)
        edited=self.save(self.payload(reopened)); self.assertEqual(edited['classroom_name'],'A組')
        with Session(self.engine) as s:
            revision=SqlModelDocumentRepository(s).head(doc_id).current_revision_id
        copied=self.preview(school_year=2027,previous_id=doc_id,revision_id=revision)
        self.assertEqual(copied['owner_name'],'後から変更した担任'); self.assertEqual(copied['reflection'],[['','']]*4)
        with Session(self.engine) as s:
            for assignment in s.exec(select(StaffClassroomAssignment)).all(): s.delete(assignment)
            s.commit()
        self.assertEqual(self.preview(school_year=2028)['owner_name'],'')

    def test_stale_confirmation_and_atomic_period_save(self):
        self.actors(); doc=self.save(self.payload(self.preview()))['document_id']
        self.saved_period(doc)
        self.saved_period(doc,version=0,status=409)
        self.saved_period(doc,version=1,values=['新しい内容',''])
        self.post(f'/plans/documents/{doc}/reflections/0/request',409,data={'version':1})
        self.post(f'/plans/documents/{doc}/reflections',409,json={'entries':[
            {'period':1,'version':0,'values':['保存されない','']},
            {'period':0,'version':1,'values':['古い内容','']}]})
        with Session(self.engine) as s:
            self.assertIsNone(service.draft_for(s,doc,1)); self.assertEqual(s.exec(select(Review)).all(),[])

    def test_scope_csrf_view_only_archived_and_empty(self):
        self.actors(); doc=self.save(self.payload(self.preview()))['document_id']
        with TestClient(self.app,base_url='https://testserver') as client:
            self.assertEqual(client.post(f'/plans/documents/{doc}/reflections',json={'entries':[{'period':0,'version':0,'values':['x','']}]}).status_code,403)
        self.user=replace(self.editor,role=Role.VIEW_ONLY); self.saved_period(doc,status=403)
        self.user=replace(self.editor,nursery_ref='別園'); self.saved_period(doc,status=404)
        self.user=replace(self.editor,classroom_refs=('B組',)); self.saved_period(doc,status=403)
        self.user=self.editor; self.saved_period(doc,values=['',''])
        self.post(f'/plans/documents/{doc}/reflections/0/request',422,data={'version':1})
        self.saved_period(doc,period=-1,values=['日案への偽装'],status=404)
        with Session(self.engine) as s:
            row=s.get(PlanDocumentRow,doc); row.status='archived';s.add(row);s.commit()
        self.saved_period(doc,version=1,status=409)

    def test_existing_daily_reflection_and_withdrawal(self):
        self.actors()
        with Session(self.engine) as s:
            doc=SqlModelDocumentRepository(s).create(PlanDocument(id=0,document_type=DocumentType.DAILY_PLAN,
                title='見本の日案',status=DocumentStatus.APPROVED,nursery_ref=self.user.nursery_ref,classroom_ref='A組',
                actor_ref=self.user.actor_ref,owner_name=self.user.name,sections=[],target_date='2026-10-11'))
            doc_id=doc.id;s.add(PlanDailyReflectionRow(document_id=doc_id,body='既存の提出内容',status='submitted',updated_by=self.user.actor_ref));s.commit()
            self.assertEqual(service.state(s,doc,-1)['values'],['既存の提出内容'])
        draft=self.saved_period(doc_id,period=-1,values=['確認へ進む日案']).json()['-1']
        url=self.post(f'/plans/documents/{doc_id}/reflections/-1/request',303,data={'version':draft['version']}).headers['location']
        self.post(url,303,data={'action':'withdraw'})
        with Session(self.engine) as s:
            self.assertEqual(s.get(PlanDocumentRow,doc_id).status,'approved')
            self.assertEqual(service.portal_items(s,self.admin.user_id,self.admin.nursery_ref,True)[0],[])
            self.assertEqual(s.exec(select(PlanDailyReflectionRow)).one().status,'draft')

    def test_old_backup_upgrades_without_copying_reflections(self):
        from restore_family_archive import compatible, upgrade_copy
        current=self.engine.raw_connection()
        schema=current.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        path=Path(self.temp.name)/'restore.sqlite'
        with closing(sqlite3.connect(path)) as target:
            current.driver_connection.backup(target)
            for table in ('plan_reflection_notifications','plan_reflection_reviews','plan_reflection_drafts'):
                target.execute(f'DROP TABLE {table}')
            old=target.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        current.close()
        self.assertTrue(compatible(old,schema));self.assertFalse(compatible(schema,old))
        upgrade_copy(path,schema)
        with closing(sqlite3.connect(path)) as target:
            self.assertEqual(target.execute('SELECT COUNT(*) FROM plan_reflection_drafts').fetchone()[0],0)
            self.assertEqual(target.execute('PRAGMA foreign_key_check').fetchall(),[])
        changed=[(*r[:3],r[3].replace('draft_version INTEGER NOT NULL','draft_version VARCHAR NOT NULL')) if r[1]=='plan_reflection_reviews' else r for r in schema]
        self.assertFalse(compatible(old,changed))
