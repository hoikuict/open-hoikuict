"""Monthly form defaults, rejected saves and the existing review journey."""
from unittest import TestCase

from sqlmodel import Session, select

from plan_docs.db_models import PlanDocumentRow
import test_monthly_library as fixtures


class MonthlyValidationTests(TestCase):
    def setUp(self):
        self.f = fixtures.MonthlyLibraryTests()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def save(self, context, **changes):
        return self.f.save(self.f.payload(context) | {'base_token': context['base_token']} | changes)

    def test_missing_owner_does_not_create_or_modify_documents(self):
        for age in range(6):
            with self.subTest(age=age):
                context = self.f.context(age=age).json()
                self.assertEqual(context['owner_name'], self.f.user.name)
                bad = self.save(context, owner_name='　 ', fields={'common:goal': {'body': '残す本文'}})
                self.assertEqual(bad.status_code, 422)
                self.assertIn('担任名', bad.json()['detail'])
                self.assertIsNone(self.f.context(age=age).json()['document_id'])
                good = self.save(context, owner_name='記録済みの担任', fields={'common:goal': {'body': '残す本文'}})
                self.assertEqual(good.status_code, 200, good.text)
                saved = good.json()
                self.assertEqual(self.save(saved, owner_name='').status_code, 422)
                after = self.f.context(age=age).json()
                self.assertEqual(after['owner_name'], '記録済みの担任')
                self.assertEqual(after['sheet']['fields']['common:goal']['body'], '残す本文')
                self.assertEqual(after['lock_version'], saved['lock_version'])
        with Session(self.f.engine) as session:
            self.assertEqual(len(session.exec(select(PlanDocumentRow)).all()), 6)

    def test_empty_body_save_review_withdraw_edit_for_all_ages(self):
        for age in range(6):
            with self.subTest(age=age):
                result = self.save(self.f.context(age=age).json(), fields={})
                self.assertEqual(result.status_code, 200, result.text)
                saved = result.json()
                url = f"/plans/documents/{saved['document_id']}"
                detail = self.f.client.get(url)
                self.assertEqual(detail.status_code, 200)
                self.assertIn('monthly-review-feedback.js', detail.text)
                self.assertIn('value="in_review">レビュー依頼', detail.text)
                requested = self.f.client.post(url+'/status', data={'status':'in_review','lock_version':saved['lock_version']})
                self.assertEqual(requested.status_code, 200, requested.text)
                self.assertIn('レビューを取り下げる', requested.text)
                self.assertNotIn('value="in_review">レビュー依頼', requested.text)
                context = self.f.context(age=age).json()
                self.assertFalse(context['editable'])
                stale = self.f.client.post(url+'/status', data={'status':'draft','lock_version':saved['lock_version']})
                self.assertEqual(stale.status_code, 409)
                withdrawn = self.f.client.post(url+'/status', data={'status':'draft','lock_version':context['lock_version']})
                self.assertEqual(withdrawn.status_code, 200, withdrawn.text)
                self.assertTrue(self.f.context(age=age).json()['editable'])
                self.assertIn(f'href="{url}/edit"', withdrawn.text)
                edited = self.save(self.f.context(age=age).json(), fields={'common:goal':{'body':'修正後'}})
                self.assertEqual(edited.status_code, 200, edited.text)
