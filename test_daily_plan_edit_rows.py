"""Saved daily plans support insertion without losing existing rows or revisions."""
import copy
import unittest

from sqlmodel import Session, select

import test_plan_docs as fixtures
from plan_docs.contracts import DocumentType
from plan_docs.db_models import PlanRevisionRow
from plan_docs.store import SqlModelDocumentRepository


class DailyPlanEditRowsTests(unittest.TestCase):
    setUp = fixtures.PlanDocsIntegrationTests.setUp
    tearDown = fixtures.PlanDocsIntegrationTests.tearDown
    staff_cookies = fixtures.PlanDocsIntegrationTests.staff_cookies
    _create_example_corpus = fixtures.PlanDocsIntegrationTests._create_example_corpus

    def create_plan(self, target_date='2026-11-19'):
        self.client.cookies.update(self.staff_cookies())
        response = self.client.post('/plans/daily-plans', data={
            'target_date': target_date, 'classroom_ref': 'ひよこ組', 'age_class': '3歳児',
            'owner_name': '見本の保育士', 'daily_aims': 'ねらいを保持', 'daily_content': '内容を保持',
            'timeline_row_key': ['morning', 'lunch'], 'timeline_time': ['10:00', '11:30'],
            'timeline_activity': ['園庭遊び', '食事'],
            'timeline_children': ['落ち葉を集める', '食事を楽しむ'],
            'timeline_support': ['発見を受け止める', '見守る'],
            'timeline_considerations': ['安全を確認', 'アレルギー確認'],
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        return int(response.headers['location'].rsplit('/', 1)[1])

    def document(self, document_id):
        response = self.client.get(f'/plans/api/documents/{document_id}')
        self.assertEqual(response.status_code, 200)
        return response.json()

    def save(self, document_id, keys, **fields):
        return self.client.post(f'/plans/documents/{document_id}', data={
            'lock_version': '1', 'daily_row_key': keys, **fields,
        }, follow_redirects=False)

    def revisions(self, document_id):
        with Session(self.engine) as session:
            return copy.deepcopy([r.snapshot for r in session.exec(select(PlanRevisionRow).where(
                PlanRevisionRow.document_id == document_id).order_by(PlanRevisionRow.revision_no)).all()])

    def test_insert_multiple_rows_save_reopen_and_keep_original_revision(self):
        document_id = self.create_plan()
        original = self.document(document_id)
        revisions = self.revisions(document_id)
        edit = self.client.get(f'/plans/documents/{document_id}/edit')
        self.assertEqual(edit.text.count('class="button button--secondary insert-daily-row"'), 2)
        self.assertEqual(edit.text.count('name="daily_row_key"'), 2)
        self.assertIn('js/daily-plan-edit.js?v=', edit.text)
        keys = ['morning', 'added_a', 'added_b', 'lunch', 'added_last']
        saved = self.save(document_id, keys,
            rowtime__added_a='10:30', cell__added_a__children='追加 <見本>',
            cell__added_a__support='追加の援助', cell__added_a__considerations='追加の配慮',
            rowtime__added_b='11:00', cell__added_last__children='午後の活動')
        self.assertEqual(saved.status_code, 303, saved.text)
        self.assertEqual(saved.headers['location'], f'/plans/documents/{document_id}')
        after = self.document(document_id)
        rows = after['schedule']['rows']
        self.assertEqual([r['row_key'] for r in rows], keys)
        self.assertEqual([r['order'] for r in rows], [10, 20, 30, 40, 50])
        self.assertEqual(after['sections'], original['sections'])
        for before, now in zip(original['schedule']['rows'], [rows[0], rows[3]]):
            self.assertEqual({k: v for k, v in before.items() if k != 'order'},
                             {k: v for k, v in now.items() if k != 'order'})
        self.assertEqual(rows[1]['cells']['support']['body'], '追加の援助')
        self.assertEqual(rows[1]['cells']['considerations']['body'], '追加の配慮')
        self.assertEqual(rows[1]['cells']['children']['source_refs'], ['form.schedule'])
        self.assertEqual(rows[1]['label'], '')
        reopened = self.client.get(f'/plans/documents/{document_id}/edit')
        self.assertEqual(reopened.text.count('name="daily_row_key"'), 5)
        self.assertIn('追加 &lt;見本&gt;', reopened.text)
        saved_again = self.save(document_id, keys, lock_version='2', cell__added_a__children='追加行の再修正')
        self.assertEqual(saved_again.status_code, 303)
        self.assertEqual(self.document(document_id)['schedule']['rows'][1]['cells']['children']['body'], '追加行の再修正')
        self.assertEqual(self.revisions(document_id)[0], revisions[0])
        self.assertEqual(len(self.revisions(document_id)), 3)

    def test_empty_new_rows_skipped_but_each_single_field_and_saved_empty_rows_kept(self):
        for day, field in enumerate(('rowtime', 'cell_children', 'cell_support', 'cell_considerations'), 19):
            with self.subTest(field=field):
                document_id = self.create_plan(target_date=f'2026-11-{day}')
                name = 'rowtime__added' if field == 'rowtime' else f'cell__added__{field.removeprefix("cell_")}'
                response = self.save(document_id, ['morning', 'empty', 'added', 'lunch'], **{
                    'rowtime__empty': '  ', 'cell__empty__children': '\n', name: '入力あり',
                    'rowtime__morning': '', 'cell__morning__children': '',
                    'cell__morning__support': '', 'cell__morning__considerations': '',
                })
                self.assertEqual(response.status_code, 303, response.text)
                rows = self.document(document_id)['schedule']['rows']
                self.assertEqual([r['row_key'] for r in rows], ['morning', 'added', 'lunch'])
                self.assertEqual(rows[0]['cells']['children']['body'], '')
                self.assertEqual(rows[0]['label'], '園庭遊び')

    def test_invalid_row_order_is_atomic_and_cannot_delete_or_reorder_saved_rows(self):
        document_id = self.create_plan()
        before = self.document(document_id)
        old_revisions = self.revisions(document_id)
        for keys in (['morning'], ['lunch', 'morning'], ['morning', 'morning', 'lunch'],
                     ['morning', '', 'lunch'], ['morning', 'bad/key', 'lunch'],
                     ['morning', 'x' * 129, 'lunch'], ['added_only']):
            with self.subTest(keys=keys):
                response = self.save(document_id, keys, title='更新されない', cell__morning__children='更新されない')
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.document(document_id), before)
                self.assertEqual(self.revisions(document_id), old_revisions)

    def test_stale_insert_does_not_overwrite_other_edit(self):
        document_id = self.create_plan()
        response = self.save(document_id, ['morning', 'added', 'lunch'], cell__added__children='先に保存')
        self.assertEqual(response.status_code, 303)
        before = self.document(document_id)
        response = self.save(document_id, ['morning', 'stale', 'lunch'], cell__stale__children='古い画面')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.document(document_id), before)
        self.assertEqual(len(self.revisions(document_id)), 2)

    def test_legacy_post_without_row_keys_keeps_existing_rows(self):
        document_id = self.create_plan()
        response = self.client.post(f'/plans/documents/{document_id}', data={
            'lock_version': '1', 'cell__morning__support': '以前の編集画面から修正',
            'cell__unlisted__children': '行一覧にない値',
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        rows = self.document(document_id)['schedule']['rows']
        self.assertEqual([r['row_key'] for r in rows], ['morning', 'lunch'])
        self.assertEqual(rows[0]['cells']['support']['body'], '以前の編集画面から修正')

    def test_weekly_grid_retains_existing_editor_and_rejects_daily_row_payload(self):
        daily_id = self.create_plan()
        with Session(self.engine) as session:
            repository = SqlModelDocumentRepository(session)
            weekly = repository.get(daily_id)
            weekly.id = 0
            weekly.document_type = DocumentType.WEEKLY_PLAN
            weekly.schedule.layout = 'weekly_grid'
            weekly_id = repository.create(weekly).id
        edit = self.client.get(f'/plans/documents/{weekly_id}/edit')
        self.assertEqual(edit.status_code, 200)
        self.assertNotIn('下に行を追加', edit.text)
        self.assertNotIn('daily-plan-edit.js', edit.text)
        before = self.document(weekly_id)
        self.assertEqual(self.save(weekly_id, ['morning', 'new', 'lunch'], cell__new__children='追加不可').status_code, 422)
        self.assertEqual(self.document(weekly_id), before)
        response = self.client.post(f'/plans/documents/{weekly_id}', data={
            'lock_version': '1', 'rowlabel__morning': '月曜日', 'cell__morning__children': '週案の変更',
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.document(weekly_id)['schedule']['rows'][0]['cells']['children']['body'], '週案の変更')

    def test_insert_respects_view_permission_and_review_status(self):
        document_id = self.create_plan()
        admin = dict(self.client.cookies)
        self.client.cookies.update(self.staff_cookies(role='view_only'))
        self.assertEqual(self.client.get(f'/plans/documents/{document_id}/edit').status_code, 403)
        self.assertEqual(self.save(document_id, ['morning', 'new', 'lunch'], cell__new__children='追加不可').status_code, 403)
        self.client.cookies.update(admin)
        lock = 1
        for status, editable in [('in_review', False), ('rejected', True), ('in_review', False), ('approved', False)]:
            response = self.client.post(f'/plans/documents/{document_id}/status', data={
                'status': status, 'lock_version': str(lock), 'comment': '見本の差し戻し理由',
            }, follow_redirects=False)
            self.assertEqual(response.status_code, 303, response.text)
            lock += 1
            before = self.document(document_id)
            keys = [r['row_key'] for r in before['schedule']['rows']] + [f'new_{lock}']
            saved = self.save(document_id, keys, **{'lock_version': str(lock), f'cell__new_{lock}__children': '差し戻し後に追加'})
            self.assertEqual(saved.status_code, 303 if editable else 409, saved.text)
            if editable:
                lock += 1
            else:
                self.assertEqual(self.document(document_id), before)
