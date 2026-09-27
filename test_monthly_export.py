"""Monthly output regression tests against a fictional, isolated database."""
import json
import hashlib
import re
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from sqlmodel import Session
from models import Child
from plan_docs.contracts import Role
from plan_docs.services.monthly_export import EXPORT_GATE
from plan_docs.services.monthly_export_layout import make_layout
import test_monthly_library as library_tests

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


class MonthlyExportTests(unittest.TestCase):
    def setUp(self):
        self.fixture = library_tests.MonthlyLibraryTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.client = self.fixture.client
        self.context = self.fixture.context().json()
        self.payload = {k: self.context[k] for k in ('document_id','lock_version','classroom_id','target_month','age')}
        self.payload.update(kind='pdf', mode='current', owner_name='架空職員', fields={
            'child:1:play': {'body': '【架空】保存前の本文。\n友達の動きを真似する。'},
            'child:2:review': {'body': '【架空】最後の園児の評価。'},
            'common:goal': {'body': '=1+1\n<script>alert(1)</script> https://example.invalid'}})

    def post(self, payload=None):
        return self.client.post('/plans/monthly-library/export', json=payload or self.payload)

    def saved(self):
        saved = self.fixture.save(self.fixture.payload(self.context, self.payload['fields'])).json()
        return {k: saved[k] for k in ('document_id','lock_version','classroom_id','target_month','age')} | {'kind':'pdf','mode':'saved'}

    def dump(self):
        with self.fixture.engine.connect() as con:
            return '\n'.join(con.connection.driver_connection.iterdump())

    def test_editor_and_saved_document_load_the_actual_versioned_assets(self):
        from fastapi.staticfiles import StaticFiles
        import template_utils
        self.fixture.app.mount('/static', StaticFiles(directory=template_utils._STATIC_ROOT), name='static')
        saved = self.saved()
        for role in (Role.CAN_EDIT, Role.VIEW_ONLY):
            self.fixture.user.role = role
            for path in (f"/plans/monthly-library?document_id={saved['document_id']}",
                         f"/plans/documents/{saved['document_id']}"):
                page = self.client.get(path)
                self.assertEqual(page.status_code, 200)
                for asset in ('js/monthly-library.js', 'css/monthly-library.css'):
                    pattern = r'(?:src|href)="(/static/' + re.escape(asset) + r'\?v=([0-9a-f]{16}))"'
                    match = re.search(pattern, page.text)
                    self.assertIsNotNone(match, path)
                    response = self.client.get(match[1])
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(hashlib.sha256(response.content).hexdigest()[:16], match[2])
                    self.assertNotIn(f'"/static/{asset}"', page.text)

    def test_rendered_asset_url_changes_when_content_changes(self):
        root = Path(self.fixture.temp.name) / 'versioned-assets'
        for name in ('js', 'css'):
            (root / name).mkdir(parents=True)
            (root / name / f'monthly-library.{name}').write_bytes(b'original asset')
        with patch('template_utils._STATIC_ROOT', root):
            before = self.client.get('/plans/monthly-library').text
            (root / 'js/monthly-library.js').write_bytes(b'updated asset!')
            after = self.client.get('/plans/monthly-library').text
        pattern = r'src="(/static/js/monthly-library.js\?v=[0-9a-f]{16})"'
        self.assertNotEqual(re.search(pattern, before)[1], re.search(pattern, after)[1])

    def test_pdf_snapshot_escapes_text_embeds_font_and_does_not_save(self):
        before = self.dump()
        response = self.post(); self.assertEqual(response.status_code, 200, response.text)
        data = response.json(); self.assertEqual(data['pages'], 1)
        self.assertIn('保存前の入力を含みます', data['html'])
        self.assertIn('最後の園児の評価', data['html'])
        self.assertNotIn('<script>alert(1)</script>', data['html'])
        self.assertIn('&lt;script&gt;', data['html'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(before, self.dump())

    def test_xlsx_editable_print_setup_and_literal_formula_and_url(self):
        response = self.post(self.payload | {'kind':'xlsx'})
        self.assertEqual(response.status_code, 200, response.text[:200])
        with ZipFile(BytesIO(response.content)) as z:
            sheet = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            setup = sheet.find('s:pageSetup', NS)
            self.assertEqual(setup.get('paperSize'), '9'); self.assertEqual(setup.get('orientation'), 'landscape')
            self.assertIsNone(sheet.find('s:sheetProtection', NS))
            self.assertFalse(sheet.findall('.//s:f', NS)); self.assertIsNone(sheet.find('s:hyperlinks', NS))
            self.assertGreater(len(sheet.findall('.//s:mergeCell', NS)), 20)
            strings = ''.join(ET.fromstring(z.read('xl/sharedStrings.xml')).itertext())
            self.assertIn('=1+1', strings); self.assertIn('最後の園児の評価', strings)
            self.assertIn('_xlnm.Print_Area', z.read('xl/workbook.xml').decode())

    def test_saved_output_keeps_saved_roster_and_allows_viewer(self):
        payload = self.saved()
        with Session(self.fixture.engine) as session:
            child = session.get(Child, 1); child.first_name = '変更後'; session.add(child); session.commit()
        self.fixture.user.role = Role.VIEW_ONLY
        before = self.dump()
        response = self.post(payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('架空 1', response.json()['html']); self.assertNotIn('変更後', response.json()['html'])
        self.assertIn('保存済みの内容です', response.json()['html'])
        self.assertEqual(before, self.dump())

    def test_denies_anonymous_and_csrf_and_other_classroom(self):
        payload = self.payload | {'classroom_id':2}
        self.assertEqual(self.post(payload).status_code, 403)
        token = self.client.headers.pop('X-CSRF-Token')
        self.assertEqual(self.post().status_code, 403)
        self.client.headers['X-CSRF-Token'] = token
        self.fixture.user.actor_ref = None
        response = self.client.post('/plans/monthly-library/export', json=self.payload, follow_redirects=False)
        self.assertEqual(response.status_code, 303)

    def test_other_nursery_cannot_export_saved_document(self):
        payload = self.saved(); self.fixture.user.nursery_ref = 'another-nursery'
        self.assertEqual(self.post(payload).status_code, 404)

    def test_viewer_cannot_supply_draft_or_modify_saved_export(self):
        payload = self.saved(); self.fixture.user.role = Role.VIEW_ONLY
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.post(payload | {'fields':self.payload['fields']}).status_code, 422)

    def test_stale_or_locked_draft_cannot_export_as_current(self):
        payload = self.saved()
        current = self.payload | {'document_id':payload['document_id'], 'lock_version':0}
        self.assertEqual(self.post(current).status_code, 409)
        current['lock_version'] = payload['lock_version']
        status = self.client.post(f"/plans/documents/{payload['document_id']}/status",
            data={'status':'in_review','lock_version':payload['lock_version']}, follow_redirects=False)
        self.assertEqual(status.status_code, 303)
        self.assertEqual(self.post(current).status_code, 409)
        self.assertEqual(self.post(payload).status_code, 200)

    def test_rejects_foreign_child_bad_month_and_injected_metadata(self):
        for extra in ({'fields':{'child:999:play':{'body':'unrelated'}}}, {'target_month':'bad'},
                      {'children':[{'name':'偽の名簿'}]}, {'classroom_name':'偽のクラス'},
                      {'fields':{'common:goal':{'body':'\x00'}}}):
            with self.subTest(extra=extra): self.assertEqual(self.post(self.payload | extra).status_code, 422)

    def test_busy_and_failure_preserve_db_and_release_gate(self):
        before = self.dump()
        with EXPORT_GATE:
            self.assertEqual(self.post().status_code, 429)
        with patch('plan_docs.services.monthly_export_layout.make_layout', side_effect=OSError('fixture failure')):
            self.assertEqual(self.post().status_code, 503)
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(before, self.dump())

    def test_native_form_print_download_and_error_page(self):
        self.client.headers.pop('X-CSRF-Token')
        before=self.dump()
        data={'snapshot':json.dumps(self.payload),'csrf_token':self.client.cookies.get('hoikuict_csrf')}
        response=self.client.post('/plans/monthly-library/export-file',data=data)
        self.assertEqual(response.status_code,200)
        self.assertIn('この帳票を印刷',response.text)
        self.assertIn('text/html',response.headers['content-type'])
        data['download_pdf']='true'
        response=self.client.post('/plans/monthly-library/export-file',data=data)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.content.startswith(b'%PDF'));self.assertIn(b'/FontFile2',response.content)
        del data['download_pdf']
        data['snapshot']=json.dumps(self.payload | {'kind':'xlsx'})
        response=self.client.post('/plans/monthly-library/export-file',data=data)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.content.startswith(b'PK'))
        self.assertIn('attachment',response.headers['content-disposition'])
        data['snapshot']=json.dumps(self.payload | {'classroom_id':2})
        response=self.client.post('/plans/monthly-library/export-file',data=data)
        self.assertEqual(response.status_code,403)
        self.assertIn('出力できませんでした',response.text)
        self.assertEqual(before,self.dump())

    def test_all_ages_long_text_and_many_children_keep_every_character(self):
        for age in range(6):
            for long in (False,True):
                context = self.fixture.context(age=age).json()
                fields = {k:{'body':f'【架空】{v["label"]}。'+('長い文章の確認。\n'*70 if long else '')}
                          for k,v in context['definitions'].items()}
                context['sheet']['fields'] = fields
                self.verify_layout(context)
        context = deepcopy(self.context)
        context['sheet']['children'] = [context['sheet']['children'][0] | {'ref':f'child:{i}','name':f'架空{i}'} for i in range(20)]
        self.assertGreater(len(self.verify_layout(context)['pages']), 1)
        context['sheet']['children'] = []
        self.verify_layout(context)

    def verify_layout(self, context):
        layout = make_layout(context); collected = {}
        for page in layout['pages']:
            occupied=set()
            for cell in page['cells']:
                self.assertLessEqual(cell['row']+cell['height'],85)
                for row in range(cell['row'],cell['row']+cell['height']):
                    for col in range(cell['col'],cell['col']+cell['span']):
                        self.assertNotIn((row,col),occupied);occupied.add((row,col))
                if cell['key']: collected.setdefault(cell['key'],{})[cell['part']]=cell['text']
        for key,value in context['sheet']['fields'].items():
            self.assertEqual(''.join(v for _,v in sorted(collected.get(key,{}).items())),value['body'])
        return layout

    def test_output_has_bounded_pages(self):
        context = deepcopy(self.context)
        context['sheet']['fields'] = {'child:1:play': {'body':'行\n'*20000}}
        with self.assertRaisesRegex(ValueError,'100ページ'): make_layout(context)


if __name__ == '__main__':
    unittest.main()
