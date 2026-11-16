"""Render monthly-only fictional prototypes from the current deployed templates."""
import os
os.environ.update(HOIKUICT_DATABASE_URL='sqlite://', HOIKUICT_ENV='development', PYTHON_DOTENV_DISABLED='1', HOIKUICT_ENABLE_MOCK_AUTH='1')
os.environ.pop('HOIKU_NURSERY_REF', None)
import sys
import re
import json
import shutil
import hashlib
import subprocess
from pathlib import Path
from datetime import date
from copy import deepcopy

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SOURCE=ROOT/'.local-dev/document-search-rollout-20261108/source'
COMMIT='0e1249f301b3257ae9afe0b76f47602bcd2cbe4f'
sys.path.insert(0,str(SOURCE));os.chdir(SOURCE)
from jinja2 import Environment,ChoiceLoader,DictLoader,FileSystemLoader,select_autoescape
from lxml import html as LH
from sqlmodel import Session,select
from models import Child
from test_monthly_library import MonthlyLibraryTests
from plan_docs.contracts import DocumentStatus

hashes={};pages=[]
def read(name):
    data=(SOURCE/name).read_bytes();hashes[name]=hashlib.sha256(data).hexdigest();return data.decode('utf-8')
class TrackedLoader(FileSystemLoader):
    def get_source(self,environment,template):
        read('templates/'+template);return super().get_source(environment,template)
shell='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'">
<title>月案のレビュー依頼｜確認用モック</title><link rel="stylesheet" href="assets/base.css"><script src="assets/tailwind.js"></script><link rel="stylesheet" href="preview.css"><script id="preview-data" type="application/json">{{ config|tojson }}</script><script src="preview.js"></script>{% block head %}{% endblock %}</head>
<body><aside class="preview-toolbar" aria-label="確認用の操作"><strong>月案のレビュー依頼 · 確認用モック</strong><p>架空データです。本番への保存・レビュー依頼・通知は行いません。</p>
<div class="preview-controls"><label>試す状態<select id="preview-state"><option value="partial">一部入力（未記入2項目）</option><option value="empty">計画欄が未入力</option><option value="filled">計画欄が入力済み</option><option value="other-page">別ページの園児に未記入</option><option value="owner-cleared">担任名を消した場合</option><option value="error">通信エラーと再試行</option></select></label><button type="button" id="preview-reset">見本を入れ直す</button><button type="button" id="preview-jump">レビュー依頼の位置へ</button><a id="preview-editor" href="edit-0.html">入力画面へ</a></div>
<p>レビュー前に計画欄をチェックします。「評価・反省」「行事・活動」は対象外です。下書きは途中でも保存できます。</p><p id="preview-status" role="status"></p></aside>
<main id="preview-business" class="plan-docs-content">{% block content %}{% endblock %}</main>{% block body_end %}{% endblock %}</body></html>'''
env=Environment(loader=ChoiceLoader([DictLoader({'base.html':shell}),TrackedLoader(str(SOURCE/'templates'))]),autoescape=select_autoescape(['html']))
env.filters['jst_datetime']=lambda v,fmt='%Y-%m-%d %H:%M':v.strftime(fmt) if hasattr(v,'strftime') else str(v or '')
env.globals.update(static_asset_url=lambda p:'assets/'+Path(p).name,csrf_token=lambda request:'mock-only',url_for=lambda *a,**k:'#')

def write_page(name,template,context,config):
    doc=LH.document_fromstring(env.get_template(template).render(**context,config=config))
    business=doc.xpath('//*[@id="preview-business"]')[0]
    contract=[(e.tag,e.get('name'),e.get('type'),e.get('required') is not None) for e in business.xpath('.//*[self::input or self::select or self::textarea]')]
    for e in doc.xpath('//script[@src]'):
        if e.get('src') not in ('preview.js','assets/tailwind.js','assets/monthly-library.js'):e.getparent().remove(e)
    for e in doc.xpath('//form'):
        e.set('action','#');e.set('novalidate','')
    for e in business.xpath('.//a[@href]'):
        e.set('data-original-href',e.get('href'));e.set('href','#');e.attrib.pop('target',None)
    for e in doc.iter():
        for attr in list(e.attrib):
            if attr.startswith('on'):e.attrib.pop(attr)
    if config['kind']=='editor':
        save=doc.xpath('//*[@id="save"]')[0]
        pair=LH.Element('div',{'class':'monthly-submit-pair'})
        save.getparent().replace(save,pair);pair.append(save)
        review=LH.Element('button',{'type':'button','id':'request-monthly-review','class':'primary'});pair.append(review)
        review.text='レビュー依頼'
        feedback=LH.Element('section',{'id':'monthly-review-missing','class':'review-feedback','hidden':'','tabindex':'-1'})
        pair.getparent().insert(0,feedback)
    else:
        for e in doc.xpath('//*[@id="monthly-review-feedback"]'):e.getparent().remove(e)
        form=doc.xpath('//*[@id="review-status"]/form')[0]
        form.insert(0,LH.Element('section',{'id':'monthly-review-missing','class':'review-feedback','hidden':'','tabindex':'-1'}))
    (HERE/name).write_text('<!doctype html>\n'+LH.tostring(doc,encoding='unicode'),encoding='utf-8')
    pages.append({'file':name,'kind':config['kind'],'age':config['age'],'field_contract':contract})

def main():
    assert subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()==COMMIT
    assert not subprocess.check_output(['git','-C',str(SOURCE),'status','--porcelain'],text=True).strip()
    assets=HERE/'assets';assets.mkdir(exist_ok=True)
    (assets/'base.css').write_text('\n'.join(re.findall(r'<style>(.*?)</style>',read('templates/base.html'),re.S)[:2]),encoding='utf-8')
    shutil.copyfile(ROOT/'tools/billing-reopen-preview/tailwind.js',assets/'tailwind.js')
    for name in ('monthly-library','document-search','daily-plan-print'):
        (assets/(name+'.css')).write_text(read('static/css/'+name+'.css'),encoding='utf-8')
    script=read('static/js/monthly-library.js')
    hook="""window.MonthlyPreviewAdapter={read:()=>clone(ctx()),commit:()=>commitEdit(),reset:data=>{cache.clear();current=entry(data);cache.set(scopeKey(data),current);before=null;render();},saved:data=>{current.context=clone(data);current.saved=clone(data);paper();status();},jump:key=>{if(key.startsWith('child:'))selectChild(key.split(':').slice(0,2).join(':'));current.field=key;panel(false);highlight();const el=key==='@owner'?q('[data-owner]'):all('[data-cell]').find(e=>e.dataset.cell===key);el?.scrollIntoView({block:'center'});el?.focus({preventScroll:true});}};"""
    at=script.rfind('})();');script=script[:at]+hook+'\n'+script[at:]
    assert script.count('renderHistory(); highlight();')==1
    script=script.replace('renderHistory(); highlight();','renderHistory(); highlight(); document.dispatchEvent(new Event("monthly-preview-render"));')
    (assets/'monthly-library.js').write_text(script,encoding='utf-8')
    f=MonthlyLibraryTests();f.setUp();f.user.name='見本 はなこ'
    try:
        with Session(f.engine) as session:
            for child in session.exec(select(Child)).all():
                child.last_name='見本';child.first_name=f'園児{child.id}';session.add(child)
            for i in range(3,9):
                session.add(Child(id=i,last_name='見本',first_name=f'園児{i}',last_name_kana='ミホン',first_name_kana=f'{i:02}',birth_date=date(2025,5,1),enrollment_date=date(2024,6,1),classroom_id=1))
            session.commit()
        contexts={}
        for age in range(6):
            with Session(f.engine) as session:
                for child in session.exec(select(Child)).all():child.birth_date=date(2025-age,5,1);session.add(child)
                session.commit()
            contexts[str(age)]=f.context('2026-11',age).json()
        for age in range(6):
            context=deepcopy(contexts[str(age)])
            response=f.client.get('/plans/monthly-library',params={'classroom_id':1,'target_month':'2026-11','age':age})
            assert response.status_code==200
            response.context['boot']=context
            write_page(f'edit-{age}.html','plan_docs/monthly_library/sheet.html',response.context,{'kind':'editor','age':age,'contexts':contexts})
            created=f.save(f.payload(context,{}));assert created.status_code==200,created.text
            detail=f.client.get('/plans/documents/'+str(created.json()['document_id']));assert detail.status_code==200
            detail.context['monthly_boot']=context|{'editable':False,'status':'下書き'}
            write_page(f'detail-{age}.html','plan_docs/documents/detail.html',detail.context,{'kind':'detail','age':age,'contexts':contexts})
    finally:f.tearDown()
    (HERE/'baseline.json').write_text(json.dumps({'source_commit':COMMIT,'source_hashes':hashes,'pages':pages},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (HERE/'index.html').write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=edit-0.html"><title>月案の確認</title><a href="edit-0.html">月案の確認用モックを開く</a></html>',encoding='utf-8')
    print(f'Rendered {len(pages)} monthly-only pages from {COMMIT}')

if __name__=='__main__':main()
