"""All-age source selection, immutable reflections and backward-compatible annual saves."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from pathlib import Path

from sqlmodel import Session
from models import Classroom
from plan_docs.services.annual_library import read_source
from fastapi import HTTPException
import test_annual_library as legacy


class AllClassesTests(unittest.TestCase):
    setUp = legacy.AnnualLibraryTests.setUp
    tearDown = legacy.AnnualLibraryTests.tearDown
    payload = legacy.AnnualLibraryTests.payload
    save = legacy.AnnualLibraryTests.save

    def install_grid(self, age=4):
        source = deepcopy(self.source)
        source.update(schema='annual-r8-grid-v1', sections=[], annualFields=['cell:I1'],
            periods=[{'label':str(i)} for i in range(4)],
            rawCells={'I1':'年間目標\n', 'C4':'行事の原文\n'},
            fields=[{'id':'cell:I1', 'sourceCell':'I1', 'label':'年間のねらい', 'text':'年間目標\n'},
                    {'id':'cell:C4', 'sourceCell':'C4', 'label':'行事', 'text':'行事の原文\n'}],
            grid={'range':'A3:D4', 'widths':[10,10,30,30], 'rows':[[
                {'cell':'C4', 'text':'行事の原文\n', 'rowspan':1, 'colspan':2, 'field':'cell:C4'}]]})
        source['source'].update(age=age, className='A組')
        self.path.write_text(json.dumps(source), encoding='utf-8')
        self.source = source
        self.references = [{'source':{**source['source'], 'title':'反省'}, 'status':'反省（記入済み）',
            'primary':True, 'rawCells':{'B4':'反省の原文'},
            'grid':{'range':'A1:K7','widths':[10,40,40], 'rows':[[
                {'cell':'B4','text':'反省の原文','rowspan':1,'colspan':1,'field':None},
                {'cell':'B5','text':'','rowspan':1,'colspan':1,'field':None}]]}}]
        ref_path=Path(self.temp.name)/'refs.json'
        ref_path.write_text(json.dumps(self.references), encoding='utf-8')
        self.env.stop()
        from unittest.mock import patch
        self.env=patch.dict('os.environ', {'HOIKU_ANNUAL_LIBRARY_SOURCES':json.dumps({'test-nursery':[
            {'id':'fixture','path':str(self.path),'references_path':str(ref_path)}]}),
            'HOIKUICT_ENV':'production','HOIKUICT_SECRET_KEY':'annual-test-only','HOIKUICT_CSRF_ENFORCE':'1'})
        self.env.start()

    def context(self, year=2026, **extra):
        response=self.client.get('/plans/annual-library/context', params={'classroom_id':1,'school_year':year,**extra})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_matching_class_autoloads_all_age_source_and_preserves_reflections(self):
        for age in (2,3,4,5):
            with self.subTest(age=age):
                self.install_grid(age)
                boot=self.context(year=2026+age)
                self.assertIsNone(boot['sheet'])
                boot=self.context(year=2026+age,source_key='fixture')
                saved=self.save(self.payload(boot))
                self.assertEqual(saved['sheet'],boot['sheet'])
                self.assertEqual(saved['age'],age)
                self.assertEqual(saved['references'],[])
        boot=self.context()
        self.assertEqual(boot['age'],5)
        self.assertEqual(boot['references'],self.references)
        original=self.path.read_bytes()
        saved=self.save(self.payload(boot))
        p=self.payload(saved); p['fields']['cell:C4']['body']='自由な修正\n'
        edited=self.save(p)
        self.assertEqual(self.context()['sheet'],edited['sheet'])
        self.assertEqual(edited['references'],self.references)
        self.assertEqual(self.path.read_bytes(),original)

    def test_existing_one_year_old_document_keeps_saved_source_when_registry_expands(self):
        original=legacy.AnnualLibraryTests.preview(self)
        saved=self.save(self.payload(original))
        self.install_grid(4)
        self.assertEqual(self.context()['age'],4)
        reopened=self.context(document_id=saved['document_id'])
        self.assertEqual(reopened['sheet'],saved['sheet'])
        self.assertEqual(reopened['references'],self.references)
        self.assertEqual(reopened['age'],1)

    def test_previous_year_copies_plan_but_not_reflections(self):
        self.install_grid()
        saved=self.save(self.payload(self.context()))
        choices=self.context(2027)['previous']
        next_year=self.context(2027,previous_id=saved['document_id'],revision_id=choices[0]['revision_id'])
        self.assertEqual(next_year['sheet']['fields'],saved['sheet']['fields'])
        self.assertEqual(next_year['references'],[])
        self.assertEqual(next_year['owner_name'],self.user.name)

    def test_reflections_are_scoped_to_authorized_class_and_fields_are_server_owned(self):
        self.install_grid()
        denied=self.client.get('/plans/annual-library/context',params={'classroom_id':2,'school_year':2026})
        self.assertEqual(denied.status_code,403)
        p=self.payload(self.context()); p['fields']['fake']={'body':'bad'}
        self.assertEqual(self.client.post('/plans/annual-library/save',json=p).status_code,422)
        with Session(self.engine) as s:
            c=s.get(Classroom,1); c.name='別の組'; s.add(c); s.commit()
        self.user=replace(self.user,classroom_refs=('別の組',))
        self.assertEqual(self.context()['references'],[])

    def test_invalid_grid_and_inconsistent_source_text_are_rejected(self):
        self.install_grid()
        for mutation in ('span','field','text','age'):
            with self.subTest(mutation=mutation):
                broken=deepcopy(self.source)
                if mutation=='span': broken['grid']['rows'][0][0]['colspan']=9999
                if mutation=='field': broken['grid']['rows'][0][0]['field']='fake'
                if mutation=='text': broken['fields'][0]['text']='changed'
                if mutation=='age': broken['source']['age']=6
                self.path.write_text(json.dumps(broken),encoding='utf-8')
                with self.assertRaises(HTTPException) as error: read_source(self.path)
                self.assertEqual(error.exception.status_code,503)
