"""Weekly-only offline prototype built from the verified production templates."""
import os
os.environ.update(HOIKUICT_DATABASE_URL='sqlite://', HOIKUICT_ENV='development', PYTHON_DOTENV_DISABLED='1', HOIKUICT_ENABLE_MOCK_AUTH='1')
os.environ.pop('HOIKU_NURSERY_REF',None)
import sys
import re
import json
import shutil
import hashlib
import subprocess
from pathlib import Path
from copy import deepcopy

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SOURCE=ROOT/'.local-dev/document-search-rollout-20261108/source'
COMMIT='9549c0c88a2f50028f8c5a01944f88b8e7197a13'
sys.path.insert(0,str(SOURCE));os.chdir(SOURCE)
from jinja2 import Environment,ChoiceLoader,DictLoader,FileSystemLoader,select_autoescape
from lxml import html as LH
from sqlmodel import Session
from models import Classroom
from test_weekly_library import WeeklyLibraryTests
from plan_docs.contracts import DocumentStatus

hashes={};pages=[]
def read(name):
    data=(SOURCE/name).read_bytes();hashes[name]=hashlib.sha256(data).hexdigest();return data.decode('utf-8')
class TrackedLoader(FileSystemLoader):
    def get_source(self,environment,template):
        read('templates/'+template);return super().get_source(environment,template)

shell='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'">
<title>週案の保存案内｜確認用モック</title><link rel="stylesheet" href="assets/base.css"><script src="assets/tailwind.js"></script><link rel="stylesheet" href="preview.css"><script id="preview-data" type="application/json">{{ config|tojson }}</script><script src="preview.js"></script>{% block head %}{% endblock %}</head>
<body><aside class="preview-toolbar" aria-label="確認用の操作"><strong>週案の保存・レビュー依頼 · 確認用モック r2</strong><p>架空データです。本番への保存・レビュー依頼・通知は行いません。</p>
<div class="preview-controls"><label>試す状態<select id="preview-state"><option value="partial">一部入力（作成者は自動入力）</option><option value="empty">本文が未入力</option><option value="filled">入力済み</option><option value="owner">作成者を消した場合</option><option value="other-week">別の週の作成者不足</option><option value="dates">表示月・対象週を消した場合</option><option value="saved-owner">保存済みの作成者を保持</option><option value="error">保存エラーと再試行</option><option value="review-error">レビュー依頼エラーと再試行</option></select></label><button type="button" id="preview-reset">見本を入れ直す</button><button type="button" id="preview-jump">保存・レビューの位置へ</button><a id="preview-editor" href="edit-0.html">週案の入力画面へ</a></div>
<p>下書き保存の隣から、選択中の週を保存してレビュー依頼できます。文書詳細からの依頼も試せます。</p><p>今回の不足チェックは表示月・対象週・作成者です。計画本文の必須条件は相談中です。</p><p id="preview-status" role="status"></p></aside>
<main id="preview-business" class="plan-docs-content">{% block content %}{% endblock %}</main>{% block body_end %}{% endblock %}</body></html>'''
env=Environment(loader=ChoiceLoader([DictLoader({'base.html':shell}),TrackedLoader(str(SOURCE/'templates'))]),autoescape=select_autoescape(['html']))
env.filters['jst_datetime']=lambda v,fmt='%Y-%m-%d %H:%M':v.strftime(fmt) if hasattr(v,'strftime') else str(v or '')
env.globals.update(static_asset_url=lambda p:'assets/'+Path(p).name,csrf_token=lambda request:'mock-only',url_for=lambda *a,**k:'#')

def markup(template,context,config):
    doc=LH.document_fromstring(env.get_template(template).render(**context,config=config))
    for e in doc.xpath('//script[@src]'):
        if e.get('src') not in ('preview.js','assets/tailwind.js','assets/weekly-library.js'):e.getparent().remove(e)
    for e in doc.xpath('//form'):
        e.set('action','#');e.set('novalidate','')
    for e in doc.xpath('//*[@id="preview-business"]//a[@href]'):
        e.set('data-original-href',e.get('href'));e.set('href','#');e.attrib.pop('target',None)
    for e in doc.iter():
        for attr in list(e.attrib):
            if attr.startswith('on'):e.attrib.pop(attr)
        if e.text and re.fullmatch(r'__PREVIEW_[a-z0-9_]+__',e.text.strip()):
            e.set('data-preview-value',e.text.strip()[10:-2]);e.text=''
    return doc

def write(name,template,context,config):
    doc=markup(template,context,config)
    business=doc.xpath('//*[@id="preview-business"]')[0]
    contract=[(e.tag,e.get('name'),e.get('type'),e.get('required') is not None) for e in business.xpath('.//*[self::input or self::select or self::textarea]')]
    if config['kind']=='editor':
        actions=doc.xpath('//*[@id="weekly-save"]/..')[0]
        actions.insert(0,LH.Element('section',{'id':'weekly-save-feedback','class':'weekly-feedback','tabindex':'-1','hidden':''}))
        target=LH.Element('p',{'id':'weekly-review-target','class':'weekly-review-target'})
        actions.insert(0,target)
        group=LH.Element('div',{'class':'weekly-submit-actions'})
        group.append(doc.xpath('//*[@id="weekly-save"]')[0])
        review=LH.Element('button',{'id':'weekly-review','type':'button','class':'button primary','aria-describedby':'weekly-review-target'})
        review.text='レビュー依頼';group.append(review);actions.append(group)
    (HERE/name).write_text('<!doctype html>\n'+LH.tostring(doc,encoding='unicode'),encoding='utf-8')
    pages.append({'file':name,'kind':config['kind'],'age':config['age'],'field_contract':contract})

def main():
    assert subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip()==COMMIT
    assert not subprocess.check_output(['git','-C',str(SOURCE),'status','--porcelain'],text=True).strip()
    prod=json.loads((ROOT/'.local-dev/weekly-validation-preview-20261115/baseline.json').read_text(encoding='utf-8'))
    assert prod['commit']==COMMIT
    assets=HERE/'assets';assets.mkdir(exist_ok=True)
    (assets/'base.css').write_text('\n'.join(re.findall(r'<style>(.*?)</style>',read('templates/base.html'),re.S)[:2]),encoding='utf-8')
    shutil.copyfile(ROOT/'tools/billing-reopen-preview/tailwind.js',assets/'tailwind.js')
    for name in ('weekly-library','document-search'):
        (assets/(name+'.css')).write_text(read('static/css/'+name+'.css'),encoding='utf-8')
    for name in ('plan_docs/routers/weekly_library.py','plan_docs/services/weekly_library.py','test_weekly_library.py'):
        read(name)
    script=read('static/js/weekly-library.js')
    before="function notice(text,error=false){"
    assert script.count(before)==1
    script=script.replace(before,before+'if(window.WeeklyPreview.notice(text,error))return;')
    script=script.replace('paper();status();renderSources();','paper();status();renderSources();window.WeeklyPreview.changed();')
    script=script.replace("current=install(boot);selected=boot.selected_week;", "Object.assign(boot,window.WeeklyPreview.initial(boot));current=install(boot);selected=boot.selected_week;")
    hook='''window.WeeklyPreview.adapter={current:()=>{collect();return {...copy(current.data),selected_week:selected};},pending:()=>{collect();return current.data.records.filter((r,i)=>r.editable&&(changed(r,current.saved.records[i])||(r.week_start===selected&&!r.document_id)));},reset:(data,baseline=data)=>{cache.clear();current=install(data);current.saved=copy(baseline);selected=data.selected_week||data.records[0].week_start;render();search();},select:start=>{collect();selected=start;render();},save:()=>save(),restore:()=>{current.data=copy(current.saved);render();},dirty:()=>{collect();return dirty();},acceptReviewed:r=>{collect();const i=current.data.records.findIndex(x=>x.week_start===r.week_start);current.data.records[i]=copy(r);current.saved.records[i]=copy(r);render();},checkpoint:()=>{collect();return {current:scope(current.data),selected,entries:[...cache.values()].map(copy)};},resume:s=>{cache.clear();for(const entry of s.entries)cache.set(scope(entry.data),copy(entry));current=cache.get(s.current);selected=s.selected;render();search();}};'''
    at=script.rfind('})();');script=script[:at]+hook+'\n'+script[at:]
    (assets/'weekly-library.js').write_text(script,encoding='utf-8')
    f=WeeklyLibraryTests();f.setUp();f.user.name='見本 はなこ'
    try:
        with Session(f.engine) as session:
            classroom=session.get(Classroom,1);classroom.name='見本A組';session.add(classroom);session.commit()
        f.user.classroom_refs=('見本A組',)
        contexts={str(age):f.context('2026-11',age).json() for age in range(6)}
        for age in range(6):
            c=contexts[str(age)];c['selected_week']=c['records'][2]['week_start']
            c['monthly_documents']=[{'id':900,'title':'見本の月案（架空）','month':'2026-11','url':'/plans/monthly-library?document_id=900'}]
        for age in range(6):
            c=contexts[str(age)]
            editor=f.client.get('/plans/weekly-library',params={'classroom_id':1,'month':'2026-11','age':age,'week_start':c['selected_week']})
            assert editor.status_code==200
            editor.context['boot']=deepcopy(c)
            write(f'edit-{age}.html',editor.template.name,editor.context,{'kind':'editor','age':age,'contexts':contexts})
            calendar=f.client.get('/plans/weekly-plans/',params={'classroom_id':1,'month':'2026-11','age':age})
            assert calendar.status_code==200
            write(f'calendar-{age}.html',calendar.template.name,calendar.context,{'kind':'calendar','age':age,'contexts':contexts})
            payload=f.payload(c,index=2);sheet=payload['items'][0]['sheet']
            for key in ('aim','activity','support_preparation','reflection'):sheet[key]=f'__PREVIEW_{key}__'
            for i,day in enumerate(sheet['days']):
                for key in day:day[key]=f'__PREVIEW_day_{i}_{key}__'
            for key in sheet['context']:sheet['context'][key]=f'__PREVIEW_context_{key}__'
            saved=f.save(payload);assert saved.status_code==200,saved.text
            record=saved.json()['records'][2]
            detail=f.client.get('/plans/documents/'+str(record['document_id']));assert detail.status_code==200
            # Keep the conditional parent link available for the offline binding.
            detail.context['document'].parent_document_id=900
            panels={}
            for value in ('draft','in_review'):
                ctx=dict(detail.context);ctx['document']=deepcopy(ctx['document']);ctx['document'].status=DocumentStatus(value)
                rendered=markup(detail.template.name,ctx,{'kind':'detail','age':age,'contexts':contexts})
                panels[value]=LH.tostring(rendered.xpath('//*[@id="review-status"]')[0],encoding='unicode')
            write(f'detail-{age}.html',detail.template.name,detail.context,{'kind':'detail','age':age,'contexts':contexts,'review_panels':panels})
    finally:f.tearDown()
    (HERE/'index.html').write_text('<!doctype html><html lang="ja"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=edit-0.html"><a href="edit-0.html">週案の確認画面を開く</a></html>',encoding='utf-8')
    (HERE/'baseline.json').write_text(json.dumps({'source_commit':COMMIT,'production_image':prod['image'],'files':hashes,'pages':pages},ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Built {len(pages)} weekly-only pages from {COMMIT}')

if __name__=='__main__':main()
