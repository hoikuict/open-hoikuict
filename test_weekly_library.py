"""Weekly sheets and calendars use an isolated, disposable database."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlmodel import Session, select
from plan_docs.contracts import DocumentStatus, Role
from plan_docs.db_models import PlanDocumentRow, PlanRevisionRow
from plan_docs.routers.weekly_library import router
from plan_docs.store import SqlModelDocumentRepository
import test_monthly_library as fixtures


class WeeklyLibraryTests(unittest.TestCase):
    setUp = fixtures.MonthlyLibraryTests.setUp
    tearDown = fixtures.MonthlyLibraryTests.tearDown

    def context(self, month='2026-10', age=0, classroom=1):
        if not getattr(self, '_weekly_added', False):
            self.app.include_router(router, prefix='/plans')
            self._weekly_added = True
        return self.client.get('/plans/weekly-library/context', params={'classroom_id':classroom,'month':month,'age':age})

    def payload(self, context, index=3):
        return {k:context[k] for k in ('classroom_id','month','age')} | {'items':[
            {k:deepcopy(context['records'][index][k]) for k in ('week_start','document_id','lock_version','sheet','owner_name')}]}

    def save(self, payload):
        return self.client.post('/plans/weekly-library/save', json=payload)

    def test_empty_forms_calendars_and_no_implicit_records(self):
        c=self.context().json()
        self.assertEqual(len(c['records']),5)
        for age in range(6):
            r=self.client.get('/plans/weekly-library',params={'classroom_id':1,'month':'2026-10','age':age})
            self.assertEqual(r.status_code,200,r.text)
            self.assertIn('weekly-boot',r.text)
        for path in ('weekly','monthly'):
            r=self.client.get(f'/plans/{path}-plans/',params={'classroom_id':1,'month':'2026-10','age':2})
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.text.count('data-period='),5 if path=='weekly' else 12)
        with Session(self.engine) as s:self.assertEqual(s.exec(select(PlanDocumentRow)).all(),[])

    def test_all_ages_roundtrip_and_layouts(self):
        for age in range(6):
            p=self.payload(self.context(age=age).json());sheet=p['items'][0]['sheet']
            sheet.update(aim='ねらい',activity='活動',support_preparation='援助\n準備',reflection='今週の反省')
            sheet['days'][5]={'activity':'土曜の活動','support':'援助','preparation':'準備'}
            sheet['context']['family_context']='家族からの情報'
            r=self.save(p);self.assertEqual(r.status_code,200,r.text)
            record=r.json()['records'][3];self.assertEqual(record['sheet'],sheet)
            with Session(self.engine) as s:
                repo=SqlModelDocumentRepository(s);d=repo.get(record['document_id'])
                self.assertEqual(d.weekly_sheet['age'],age)
                self.assertEqual(d.schedule is None,age<3)
                self.assertEqual(repo.revisions(d.id)[0].snapshot['weekly_sheet']['support_preparation'],'援助\n準備')
            detail=self.client.get(f"/plans/documents/{record['document_id']}")
            self.assertEqual(detail.status_code,200,detail.text)
            self.assertIn('weekly-report',detail.text)

    def test_multisave_and_empty_clear_are_preserved(self):
        c=self.context().json();p=self.payload(c);p['items']+=self.payload(c,index=4)['items']
        p['items'][0]['sheet']['support_preparation']='改行\n材料'
        p['items'][1]['sheet']['support_preparation']='隣の週'
        r=self.save(p);self.assertEqual(r.status_code,200,r.text)
        p=self.payload(r.json());p['items'][0]['sheet']['support_preparation']=''
        r=self.save(p);self.assertEqual(r.status_code,200,r.text)
        c=self.context().json();self.assertEqual(c['records'][3]['sheet']['support_preparation'],'');self.assertEqual(c['records'][4]['sheet']['support_preparation'],'隣の週')

    def test_stale_and_duplicate_save_do_not_overwrite(self):
        p=self.payload(self.context().json());r=self.save(p);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.save(p).status_code,409)
        p=self.payload(r.json());old=deepcopy(p);p['items'][0]['sheet']['aim']='先の変更'
        self.assertEqual(self.save(p).status_code,200)
        old['items'][0]['sheet']['aim']='上書き禁止';self.assertEqual(self.save(old).status_code,409)
        self.assertEqual(self.context().json()['records'][3]['sheet']['aim'],'先の変更')

    def test_batch_conflict_rolls_back_every_week(self):
        c=self.save(self.payload(self.context().json())).json()
        p=self.payload(c);p['items'][0]['lock_version']=0
        new=self.payload(c,index=4)['items'][0];new['sheet']['aim']='この新規作成も取り消す'
        p['items'].insert(0,new);self.assertEqual(self.save(p).status_code,409)
        with Session(self.engine) as s:
            self.assertEqual(len(s.exec(select(PlanDocumentRow)).all()),1)
            self.assertEqual(len(s.exec(select(PlanRevisionRow)).all()),1)

    def test_cross_month_week_is_one_record(self):
        p=self.payload(self.context().json(),index=4);p['items'][0]['sheet']['aim']='月またぎ'
        c=self.save(p).json();n=self.context(month='2026-11').json()
        self.assertEqual(c['records'][4]['document_id'],n['records'][0]['document_id'])
        self.assertEqual(n['records'][0]['sheet']['aim'],'月またぎ')
        self.assertEqual(len(self.context(month='2026-03').json()['records']),6)

    def test_readonly_status_and_generic_editor_guards(self):
        c=self.save(self.payload(self.context().json())).json();record=c['records'][3]
        for state in ('in_review','approved','archived'):
            with Session(self.engine) as s:
                row=s.get(PlanDocumentRow,record['document_id']);row.status=state;s.add(row);s.commit()
            current=self.context().json();self.assertFalse(current['records'][3]['editable'])
            self.assertEqual(self.save(self.payload(current)).status_code,409)
        self.assertEqual(self.client.post(f"/plans/documents/{record['document_id']}",data={'title':'変更'}).status_code,409)

    def test_scope_permissions_and_login(self):
        c=self.context().json();p=self.payload(c)
        self.assertEqual(self.context(classroom=2).status_code,403)
        p['classroom_id']=2;self.assertEqual(self.save(p).status_code,403)
        self.user.role=Role.VIEW_ONLY;p['classroom_id']=1;self.assertEqual(self.save(p).status_code,403)
        self.user.actor_ref=None
        self.assertEqual(self.client.get('/plans/weekly-library',follow_redirects=False).status_code,303)

    def test_validation_and_csrf_do_not_save(self):
        p=self.payload(self.context().json())
        for mutate in [lambda x:x['items'][0].update(owner_name=' '),lambda x:x['items'][0].update(week_start='2026-10-20'),lambda x:x.update(age=6),lambda x:x['items'].append(deepcopy(x['items'][0])),lambda x:x['items'][0]['sheet']['context'].update(unexpected='x')]:
            bad=deepcopy(p);mutate(bad);self.assertEqual(self.save(bad).status_code,422)
        self.client.headers.pop('X-CSRF-Token');self.assertEqual(self.save(p).status_code,403)
        with Session(self.engine) as s:self.assertEqual(s.exec(select(PlanDocumentRow)).all(),[])

    def test_monthly_calendar_opens_new_sheet_with_context(self):
        self.context()
        r=self.client.get('/plans/monthly-plans/',params={'classroom_id':1,'age':4,'year':2026})
        self.assertIn('target_month=2027-03',r.text);self.assertIn('age=4',r.text)
        r=self.client.get('/plans/monthly-library',params={'classroom_id':1,'age':4,'target_month':'2028-02'})
        self.assertEqual(r.status_code,200,r.text);self.assertIn('2028-02',r.text);self.assertIn('event:29',r.text)
        self.assertEqual(self.client.get('/plans/monthly-library',params={'classroom_id':2,'age':4,'target_month':'2028-02'}).status_code,403)

    def test_reference_search_and_provenance(self):
        self.context();path=Path(self.temp.name)/'weekly.json'
        row={'id':'fixture-week','age':0,'month':10,'title':'秋の遊び','aim':'ねらい','activity':'落ち葉','support_preparation':'援助\n材料','days':[{'activity':'','support':'','preparation':''} for _ in range(6)],'source_label':'架空の原本'}
        path.write_text(json.dumps({'schema_version':1,'examples':[row]}),encoding='utf-8')
        original=path.read_bytes()
        with patch.dict('os.environ',{'HOIKU_WEEKLY_LIBRARY_SOURCES':json.dumps({'test-nursery':{'path':str(path)}})}):
            r=self.client.get('/plans/weekly-library/candidates',params={'classroom_id':1,'age':0,'month':10,'keyword':'落ち葉 材料'})
            self.assertEqual(r.json()['items'],[row])
            p=self.payload(self.context().json());p['items'][0]['sheet']['source_ids']=['fixture-week']
            self.assertEqual(self.save(p).status_code,200)
            self.assertEqual(path.read_bytes(),original)
            p=self.payload(self.context().json());p['items'][0]['sheet']['source_ids']=['forged']
            self.assertEqual(self.save(p).status_code,422)

    def test_scope_forgery_does_not_reassign_document(self):
        c=self.save(self.payload(self.context().json())).json();p=self.payload(c);p['age']=1
        self.assertEqual(self.save(p).status_code,404)
        self.user.nursery_ref='other';self.assertEqual(self.save(p).status_code,404)


    def test_reference_beyond_first_page_can_be_saved(self):
        self.context();path=Path(self.temp.name)/'large-weekly.json'
        row={'age':5,'month':10,'title':'架空の活動','aim':'ねらい','activity':'','support_preparation':'',
             'days':[{'activity':'活動','support':'援助','preparation':'準備'} for _ in range(6)]}
        path.write_text(json.dumps({'schema_version':1,'examples':[row|{'id':f'fixture-{i}'} for i in range(110)]}),encoding='utf-8')
        with patch.dict('os.environ',{'HOIKU_WEEKLY_LIBRARY_SOURCES':json.dumps({'test-nursery':{'path':str(path)}})}):
            p=self.payload(self.context(age=5).json());p['items'][0]['sheet']['source_ids']=['fixture-109']
            self.assertEqual(self.save(p).status_code,200)
