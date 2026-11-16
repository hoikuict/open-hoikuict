"""Real weekly routes and status changes against a disposable fixture database."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from sqlmodel import Session, select
from plan_docs.contracts import Role
from plan_docs.db_models import PlanDocumentRow, PlanDocumentAction, PlanRevisionRow, PlanReviewNotificationRow
from plan_docs.store import SqlModelDocumentRepository
import test_weekly_library as fixtures


class WeeklyReviewTests(unittest.TestCase):
    setUp = fixtures.WeeklyLibraryTests.setUp
    tearDown = fixtures.WeeklyLibraryTests.tearDown
    context = fixtures.WeeklyLibraryTests.context
    payload = fixtures.WeeklyLibraryTests.payload
    save = fixtures.WeeklyLibraryTests.save

    def status(self, record, value='in_review', json=True):
        return self.client.post(f"/plans/documents/{record['document_id']}/status",
            data={'status':value, 'lock_version':record['lock_version']},
            headers={'Accept':'application/json'} if json else {}, follow_redirects=False)

    def test_all_ages_both_routes_review_withdraw_and_optional_body(self):
        for age in range(6):
            c=self.context(age=age).json()
            self.assertEqual(c['records'][3]['owner_name'], self.user.name)
            c=self.save(self.payload(c)).json();r=c['records'][3]
            response=self.status(r);self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json(),{'document_id':r['document_id'],'status':'in_review','lock_version':r['lock_version']+1})
            r=self.context(age=age).json()['records'][3]
            self.assertFalse(r['editable'])
            self.assertEqual(self.status(r,'draft',json=False).status_code,303)
            r=self.context(age=age).json()['records'][3]
            self.assertTrue(r['editable'])
            self.assertEqual(self.status(r,json=False).status_code,303)

    def test_only_selected_week_is_saved_and_reviewed(self):
        c=self.context().json();p=self.payload(c)
        p['items'][0]['sheet']['aim']='選択週の計画'
        r=self.save(p).json()['records'][3]
        self.assertEqual(self.status(r).status_code,200)
        c=self.context().json()
        self.assertEqual([r['status'] for r in c['records']],['empty','empty','empty','in_review','empty'])

    def test_existing_owner_does_not_change_with_viewer(self):
        p=self.payload(self.context().json());p['items'][0]['owner_name']='元の作成者'
        r=self.save(p).json()['records'][3];self.user.name='別の職員'
        self.assertEqual(self.context().json()['records'][3]['owner_name'],'元の作成者')
        self.assertEqual(self.status(r).status_code,200)
        self.assertEqual(self.context().json()['records'][3]['owner_name'],'元の作成者')

    def test_missing_owner_blocks_both_detail_modes_without_side_effects(self):
        r=self.save(self.payload(self.context().json())).json()['records'][3]
        with Session(self.engine) as s:
            row=s.get(PlanDocumentRow,r['document_id']);row.owner_name='　 ';s.add(row);s.commit()
        for json in (True,False):
            response=self.status(r,json=json)
            self.assertEqual(response.status_code,422,response.text)
            self.assertIn('作成者を入力してください',response.text)
            if not json:self.assertIn('weekly-review-feedback',response.text)
            with Session(self.engine) as s:
                repo=SqlModelDocumentRepository(s)
                self.assertEqual(repo.lock_version(r['document_id']),r['lock_version'])
                self.assertEqual(repo.get(r['document_id']).status.value,'draft')
                self.assertEqual(len(repo.revisions(r['document_id'])),1)
                self.assertEqual(s.exec(select(PlanDocumentAction)).all(),[])
                self.assertEqual(s.exec(select(PlanReviewNotificationRow)).all(),[])

    def test_latest_owner_is_checked_after_lock_claim(self):
        r=self.save(self.payload(self.context().json())).json()['records'][3]
        original=SqlModelDocumentRepository._claim_lock
        def clear_owner(repository, document_id, version):
            original(repository,document_id,version)
            row=repository.session.get(PlanDocumentRow,document_id);row.owner_name=' '
            repository.session.add(row);repository.session.flush()
        with patch.object(SqlModelDocumentRepository,'_claim_lock',clear_owner):
            self.assertEqual(self.status(r).status_code,422)
        self.assertEqual(self.context().json()['records'][3]['lock_version'],r['lock_version'])

    def test_stale_or_duplicate_review_cannot_submit_twice(self):
        c=self.save(self.payload(self.context().json())).json();old=deepcopy(c['records'][3])
        p=self.payload(c);p['items'][0]['sheet']['aim']='新しい本文'
        latest=self.save(p).json()['records'][3]
        self.assertEqual(self.status(old).status_code,409)
        self.assertEqual(self.status(latest).status_code,200)
        self.assertEqual(self.status(latest).status_code,409)
        with Session(self.engine) as s:
            submitted=s.exec(select(PlanRevisionRow).where(PlanRevisionRow.reason=='submitted')).all()
            self.assertEqual(len(submitted),1)
            self.assertEqual(SqlModelDocumentRepository(s).get(latest['document_id']).weekly_sheet['aim'],'新しい本文')

    def test_review_permissions_scope_and_csrf(self):
        r=self.save(self.payload(self.context().json())).json()['records'][3]
        self.user.role=Role.VIEW_ONLY;self.assertEqual(self.status(r).status_code,403)
        self.user.role=Role.CAN_EDIT;self.user.classroom_refs=('B組',)
        self.assertIn(self.status(r).status_code,(403,404))
        self.user.classroom_refs=('A組',);self.user.nursery_ref='other'
        self.assertEqual(self.status(r).status_code,404)
        self.user.nursery_ref='test-nursery';self.client.headers.pop('X-CSRF-Token')
        self.assertEqual(self.status(r).status_code,403)

    def test_editor_and_detail_expose_actions_for_all_ages(self):
        from lxml import html
        for age in range(6):
            r=self.save(self.payload(self.context(age=age).json())).json()['records'][3]
            response=self.client.get('/plans/weekly-library',params={'document_id':r['document_id']})
            self.assertEqual(response.status_code,200)
            doc=html.fromstring(response.text)
            self.assertTrue(doc.xpath('//*[@id="weekly-save"]/following-sibling::button[@id="weekly-review"]'))
            self.assertTrue(doc.xpath('//*[@id="weekly-save-feedback"]'))
            self.assertTrue(doc.xpath('//*[@id="weekly-form"][@novalidate]'))
            detail=self.client.get(f"/plans/documents/{r['document_id']}")
            self.assertIn('weekly-review-feedback',detail.text)
            self.assertIn('value="in_review"',detail.text)
