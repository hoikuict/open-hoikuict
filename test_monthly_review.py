"""Monthly review checks run before revision, status and notification writes."""
from datetime import date
from unittest import TestCase
from unittest.mock import patch

from sqlmodel import Session, select

from models import Child
from plan_docs.contracts import DocumentStatus, DocumentType
from plan_docs.db_models import PlanDocumentAction, PlanRevisionRow, PlanReviewNotificationRow
from plan_docs.models import PlanDocument
from plan_docs.serializers import document_to_dict
from plan_docs.services.monthly_review import MonthlyReviewIncompleteError
from plan_docs.store import SqlModelDocumentRepository
import test_monthly_library as fixtures


class MonthlyReviewTests(TestCase):
    def setUp(self):
        self.f = fixtures.MonthlyLibraryTests()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def save(self, context, fields):
        response = self.f.save(self.f.payload(context, fields) | {'base_token': context['base_token']})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def complete(self, age=1):
        context = self.f.context(age=age).json()
        return self.save(context, {item['key']: {'body': '計画本文'} for item in context['review_fields']})

    def request(self, context, status='in_review'):
        return self.f.client.post(f"/plans/documents/{context['document_id']}/status",
            headers={'Accept':'application/json'}, data={'status':status,'lock_version':context['lock_version']})

    def snapshot(self, document_id):
        with Session(self.f.engine) as session:
            repo = SqlModelDocumentRepository(session)
            return (document_to_dict(repo.get(document_id)), repo.head(document_id).model_dump(),
                    [[row.model_dump() for row in session.exec(select(model)).all()]
                     for model in (PlanRevisionRow, PlanDocumentAction, PlanReviewNotificationRow)])

    def test_required_fields_all_ages_and_optional_exclusions(self):
        for age in range(6):
            with self.subTest(age=age):
                context = self.f.context(age=age).json()
                keys = {item['key'] for item in context['review_fields']}
                expected = {'common:goal','common:home'}
                if age < 3:
                    expected |= {f'child:{child}:{field}' for child in (1,2) for field in ('life','play','help')}
                else:
                    expected |= {f'group:{domain}:{column}' for domain in ('care','health','relations','nature','language','expression')
                                 for column in ('goal','environment','expected','support')} | {'group:food'}
                self.assertEqual(keys, expected)
                # Optional text cannot satisfy any planning requirement; Unicode whitespace is empty.
                fields = {key:{'body':'評価や行事'} for key in context['definitions'] if key not in keys}
                fields.update({key:{'body':' \n　\t'} for key in keys})
                saved = self.save(context, fields)
                response = self.request(saved)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual({item['key'] for item in response.json()['detail']['missing']}, expected)

    def test_rejected_request_does_not_write_or_notify_and_direct_store_cannot_bypass(self):
        saved = self.save(self.f.context().json(), {})
        before = self.snapshot(saved['document_id'])
        with patch('plan_docs.store.create_review_notifications') as notify:
            with Session(self.f.engine) as session:
                with self.assertRaises(MonthlyReviewIncompleteError):
                    SqlModelDocumentRepository(session).update_status(saved['document_id'], DocumentStatus.IN_REVIEW,
                        expected_lock_version=saved['lock_version'], actor_ref=self.f.user.actor_ref)
            self.assertEqual(self.request(saved).status_code, 422)
            notify.assert_not_called()
        self.assertEqual(before, self.snapshot(saved['document_id']))

    def test_valid_review_notifies_once_and_retry_with_old_version_fails(self):
        saved = self.complete()
        with patch('plan_docs.store.create_review_notifications', return_value=[]) as notify:
            result = self.request(saved)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json(), {'document_id':saved['document_id'],'status':'in_review'})
            after = self.snapshot(saved['document_id'])
            self.assertEqual(self.request(saved).status_code, 409)
            self.assertEqual(after, self.snapshot(saved['document_id']))
            notify.assert_called_once()

    def test_new_child_after_save_blocks_review_without_altering_saved_text(self):
        saved = self.complete()
        with Session(self.f.engine) as session:
            session.add(Child(id=3,last_name='新規',first_name='架空',last_name_kana='シンキ',first_name_kana='カクウ',
                              birth_date=date(2024,5,1),enrollment_date=date(2026,10,1),classroom_id=1))
            session.commit()
        before = self.snapshot(saved['document_id'])
        result = self.request(saved)
        self.assertEqual(result.status_code, 422, result.text)
        detail = result.json()['detail']
        self.assertEqual({item['key'] for item in detail['missing']}, {'child:3:life','child:3:play','child:3:help'})
        self.assertEqual(len(detail['latest']['sheet']['children']), 3)
        self.assertEqual(detail['latest']['sheet']['fields'], saved['sheet']['fields'])
        self.assertEqual(before, self.snapshot(saved['document_id']))
        latest = detail['latest']
        saved = self.save(latest, latest['sheet']['fields'] | {item['key']:{'body':'新規園児の計画'} for item in detail['missing']})
        self.assertEqual(self.request(saved).status_code, 200)

    def test_peer_clears_a_field_old_revision_cannot_be_submitted(self):
        saved = self.complete()
        fields = dict(saved['sheet']['fields'])
        fields.pop('common:home')
        latest = self.save(saved, fields)
        before = self.snapshot(saved['document_id'])
        self.assertEqual(self.request(saved).status_code, 409)
        response = self.request(latest)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail']['missing'], [{'key':'common:home','label':'家庭との連携'}])
        self.assertEqual(before, self.snapshot(saved['document_id']))

    def test_owner_is_required_on_historical_saved_sheet(self):
        saved = self.complete()
        with Session(self.f.engine) as session:
            repo = SqlModelDocumentRepository(session)
            document = repo.get(saved['document_id'])
            document.owner_name = '　 '
            repo.update_document(document.id, title=document.title, owner_name=document.owner_name,
                confirmation_items=document.confirmation_items, section_updates={}, monthly_sheet=document.monthly_sheet,
                expected_lock_version=saved['lock_version'],actor_ref=self.f.user.actor_ref)
        saved = self.f.context().json()
        self.assertEqual(self.request(saved).json()['detail']['missing'], [{'key':'@owner','label':'担任名'}])

    def test_legacy_monthly_without_sheet_retains_existing_transition(self):
        with Session(self.f.engine) as session:
            repo = SqlModelDocumentRepository(session)
            document = repo.create(PlanDocument(id=0,document_type=DocumentType.MONTHLY_PLAN,title='旧月案',
                status=DocumentStatus.DRAFT,nursery_ref=self.f.user.nursery_ref,classroom_ref='A組',
                actor_ref=self.f.user.actor_ref,owner_name='担任',target_month='2026-10',sections=[]))
            result = repo.update_status(document.id,DocumentStatus.IN_REVIEW,
                expected_lock_version=repo.head(document.id).lock_version,actor_ref=self.f.user.actor_ref)
            self.assertEqual(result.status, DocumentStatus.IN_REVIEW)

    def test_unassigned_user_does_not_receive_missing_fields(self):
        saved = self.complete()
        from dataclasses import replace
        self.f.user = replace(self.f.user, user_id=None, actor_ref='staff:unassigned')
        response = self.request(saved)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertNotIn('missing', response.text)
