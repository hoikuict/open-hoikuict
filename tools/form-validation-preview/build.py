"""Render all review forms from the pinned deployment using fictional in-memory fixtures."""
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
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS
from copy import deepcopy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / '.local-dev/document-search-rollout-20261108/source'
COMMIT = '8f7bf89d9860300980a4cef781b0561ff845375c'
sys.path.insert(0, str(SOURCE))
os.chdir(SOURCE)

from jinja2 import Environment, ChoiceLoader, DictLoader, FileSystemLoader, select_autoescape
from lxml import html as LH
from sqlmodel import Session, select
from models import Child, HealthCheckRecord, ChildAllergy, InstitutionalRecordOrigin, HighlightStatus
from test_plan_docs import PlanDocsIntegrationTests
from test_weekly_library import WeeklyLibraryTests
from test_child_records import ChildRecordFeatureTests
from test_child_health import ChildHealthRouterTests
from test_institutional_records import InstitutionalRecordRouterTests
from testing_helpers import authenticate_mock_staff
from plan_docs.contracts import DocumentStatus

pages = []
hashes = {}

def read(path):
    data = (SOURCE / path).read_bytes()
    hashes[path] = hashlib.sha256(data).hexdigest()
    return data.decode('utf-8')

class TrackedLoader(FileSystemLoader):
    def get_source(self, environment, template):
        read('templates/' + template)
        return super().get_source(environment, template)

shell = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'">
<title>{{ mock_title }}｜記入漏れ案内の確認</title><link rel="stylesheet" href="assets/base.css"><script src="assets/tailwind.js"></script>
<link rel="stylesheet" href="mock.css"><script id="mock-fixture" type="application/json">{{ mock_config|tojson }}</script><script src="mock.js"></script>
{% block head %}{% endblock %}</head><body><aside class="mock-toolbar" aria-label="確認用の操作"><a href="index.html">← 対象一覧</a><strong>確認用モック · {{ mock_title }}</strong><p>架空データです。保存・提出・通知はこの画面内の見本です。</p>
<div class="mock-controls"><label>試す状態<select id="mock-state"><option value="partial">一部入力</option><option value="empty">未入力</option><option value="filled">入力済み</option><option value="error">保存エラー</option></select></label><button type="button" id="mock-reset">見本に戻す</button><label>試す操作<select id="mock-operation"></select></label><button type="button" id="mock-jump">操作ボタンの位置へ</button></div><p id="mock-note">{{ mock_note }}</p><p id="mock-status" role="status"></p></aside>
<main id="mock-business" class="{{ mock_class }}">{% block content %}{% endblock %}</main>{% block body_end %}{% endblock %}
<dialog id="mock-result"><h2 tabindex="-1">確認用の保存結果</h2><p></p><details><summary>仮保存した入力を確認</summary><dl></dl></details><button type="button" id="mock-edit">入力・修正へ戻る</button></dialog>
<dialog id="mock-leave"><h2>確認用画面の移動</h2><p>未保存の見本入力を残して続けますか？</p><button type="button" data-stay>入力を続ける</button><button type="button" data-discard>見本入力を破棄して戻る</button></dialog>
</body></html>'''
env = Environment(loader=ChoiceLoader([DictLoader({'base.html': shell}), TrackedLoader(str(SOURCE/'templates'))]), autoescape=select_autoescape(['html']))
env.filters['jst_datetime'] = lambda v, fmt='%Y-%m-%d %H:%M': v.strftime(fmt) if hasattr(v, 'strftime') else str(v or '')
env.globals['static_asset_url'] = lambda p: 'assets/' + Path(p).name
env.globals['csrf_token'] = lambda request: 'mock-only'
env.globals['url_for'] = lambda *a, **kw: '#'

def add(key, title, group, template, context, *, kind='generic', data=None, note='入力項目と必須条件は現行版を基準にしています。'):
    ctx = dict(context)
    ctx.setdefault('editor_user_name', '見本 はなこ')
    ctx.update(mock_title=title, mock_note=note, mock_class='plan-docs-content' if template.startswith('plan_docs/') else 'mock-normal',
               mock_config=dict(key=key, kind=kind, data=data or {}, title=title))
    raw = env.get_template(template).render(**ctx)
    doc = LH.document_fromstring(raw)
    original = [(el.tag, el.get('name'), el.get('type'), el.get('required') is not None) for el in doc.xpath('//*[@id="mock-business"]//*[self::input or self::select or self::textarea]')]
    for el in doc.xpath('//script'):
        src = el.get('src', '')
        if src in ('mock.js', 'assets/tailwind.js') or el.get('type') == 'application/json':
            continue
        if Path(src.split('?')[0]).name in ('annual-library.js', 'monthly-library.js', 'weekly-library.js'):
            el.set('src', 'assets/' + Path(src.split('?')[0]).name)
            continue
        el.getparent().remove(el)
    for el in doc.xpath('//link[@rel="stylesheet"]'):
        href = el.get('href')
        if href.startswith('http'):
            el.getparent().remove(el)
            continue
        if href.startswith('/static/'):
            el.set('href', 'assets/' + Path(href.split('?')[0]).name)
    for el in doc.xpath('//form'):
        el.set('data-original-action', el.get('action', ''))
        el.set('action', '#')
        el.set('novalidate', '')
        el.attrib.pop('onsubmit', None)
    for el in doc.xpath('//a[@href]'):
        href = el.get('href')
        if href.startswith(('/', 'http')):
            el.set('data-original-href', href)
            el.set('href', '#')
            el.attrib.pop('target', None)
    for el in doc.iter():
        for attr in list(el.attrib):
            if attr.startswith('on'):
                el.attrib.pop(attr)
    result = '<!doctype html>\n' + LH.tostring(doc, encoding='unicode')
    (HERE / (key + '.html')).write_text(result, encoding='utf-8')
    pages.append(dict(key=key, title=title, group=group, template=template, fields=len(original), field_contract=original, kind=kind))

def response(test, url, **kwargs):
    r = test.client.get(url, **kwargs)
    assert r.status_code == 200, (url, r.status_code, r.text[:180])
    return r

def main():
    assert subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip() == COMMIT
    assert not subprocess.check_output(['git','-C',str(SOURCE),'status','--porcelain'],text=True).strip()
    assets = HERE / 'assets'
    assets.mkdir(exist_ok=True)
    base = read('templates/base.html')
    (assets/'base.css').write_text('\n'.join(re.findall(r'<style>(.*?)</style>', base, re.S)[:2]),encoding='utf-8')
    shutil.copyfile(ROOT/'tools/billing-reopen-preview/tailwind.js', assets/'tailwind.js')
    for name in ('annual-library', 'monthly-library', 'weekly-library', 'reflection-review', 'daily-plan-print', 'daily-example-list'):
        (assets/(name+'.css')).write_text(read('static/css/'+name+'.css'),encoding='utf-8')
    for name in ('annual-library', 'monthly-library', 'weekly-library'):
        script = read('static/js/'+name+'.js')
        # All requests are served from memory by mock.js. Navigation is kept inside the mock.
        script = re.sub(r'^.*history\.replaceState.*\n', '', script, flags=re.M)
        script = script.replace('window.location.assign(', 'window.FormMock.navigate(').replace('location.assign(', 'window.FormMock.navigate(')
        hooks = {
            'weekly-library': "window.FormMock.adapters.weekly={current:()=>{collect();return {...copy(current.data),selected_week:selected};},reset:data=>{cache.clear();current=install(data);selected=data.selected_week||data.records[0].week_start;render();},select:start=>{collect();selected=start;render();},saved:data=>{current=install(data);status();}};",
            'annual-library': "window.FormMock.adapters.annual={current:()=>({...clone(boot),owner_name:owner,sheet:{...clone(boot.sheet),fields:clone(cells)},reflection:clone(reflection)}),reset:data=>adopt(data),saved:data=>{saved=value();savedReflection=JSON.stringify(reflection);}};",
            'monthly-library': "window.FormMock.adapters.monthly={current:()=>{commitEdit();return clone(ctx());},reset:data=>{cache.clear();current=entry(data);cache.set(scopeKey(data),current);before=null;render();},saved:data=>{current.context=clone(data);current.saved=clone(data);status();}};",
        }
        at=script.rfind('})();')
        script=script[:at]+hooks[name]+'\n'+script[at:]
        (assets/(name+'.js')).write_text(script,encoding='utf-8')

    t=WeeklyLibraryTests();t.setUp()
    try:
        t.user.name='見本 はなこ'
        monthly={};weekly={}
        for age in range(6):
            with Session(t.engine) as s:
                for child in s.exec(select(Child)).all():
                    child.last_name='見本';child.first_name=f'園児{child.id}';child.birth_date=date(2025-age,5,1);s.add(child)
                s.commit()
            weekly[str(age)]=t.context('2026-11',age).json()
            assert all(r['owner_name']==t.user.name for r in weekly[str(age)]['records'])
            monthly[str(age)]=response(t,'/plans/monthly-library/context',params={'classroom_id':1,'target_month':'2026-11','age':age}).json()
        for age in range(6):
            with Session(t.engine) as s:
                for child in s.exec(select(Child)).all():
                    child.birth_date=date(2025-age,5,1);s.add(child)
                s.commit()
            w=response(t,'/plans/weekly-library',params={'classroom_id':1,'month':'2026-11','age':age})
            add(f'weekly-{age}', f'週案 · {age}歳児', '指導計画', 'plan_docs/weekly_library/sheet.html', w.context,kind='weekly',data={'contexts':weekly},note='新規の作成者はログイン中の職員名（見本 はなこ）が入ります。保存済みは記録済みの名前を保持します。「作成者を消した場合」で不足の案内を試せます。')
            m=response(t,'/plans/monthly-library',params={'classroom_id':1,'target_month':'2026-11','age':age})
            m.context['boot']=deepcopy(monthly[str(age)])
            add(f'monthly-{age}',f'月案 · {age}歳児','指導計画','plan_docs/monthly_library/sheet.html',m.context,kind='monthly',data={'contexts':monthly},note='下書き保存後、上部の「承認・文書情報」からレビュー依頼を試せます。新規の担任名はログイン職員の名前です。不足の案内は「担任名を消した場合」で確認できます。')
            payload={k:monthly[str(age)][k] for k in ('document_id','lock_version','classroom_id','target_month','age','owner_name')}
            payload['fields']={k:{'body':'架空の月案です。','origins':[]} for k in monthly[str(age)]['definitions']}
            created=t.client.post('/plans/monthly-library/save',json=payload)
            assert created.status_code==200,created.text
            detail=response(t,f'/plans/documents/{created.json()["document_id"]}')
            ctx=detail.context
            panels={}
            for status_value in ('draft','in_review'):
                ctx['document'].status=DocumentStatus(status_value)
                fragment=LH.fromstring(env.get_template('plan_docs/documents/detail.html').render(**ctx,mock_config={},mock_title='月案',mock_note='',mock_class='plan-docs-content'))
                panel=fragment.xpath('//*[@id="review-status"]')[0]
                for form in panel.xpath('.//form'):
                    form.set('data-original-action',form.get('action'));form.set('action','#');form.set('novalidate','')
                panels[status_value]=LH.tostring(panel,encoding='unicode')
            ctx['document'].status=DocumentStatus('draft')
            add(f'monthly-review-{age}',f'月案の詳細・レビュー依頼 · {age}歳児','承認・確認依頼',detail.template.name,ctx,kind='monthly-detail',data={'age':age,'contexts':monthly,'review_panels':panels},note='保存した月案を確認して「レビュー依頼」を押します。依頼後の取り下げも試せます。この画面は閲覧用で、「修正」から入力へ戻ります。本番の保存・通知は行いません。')
    finally:t.tearDown()

    annual_path=ROOT/'tools/annual-creation-preview/fixtures.js'
    hashes['synthetic:annual-creation-preview/fixtures.js']=hashlib.sha256(annual_path.read_bytes()).hexdigest()
    annual=json.loads(annual_path.read_text(encoding='utf-8').split('=',1)[1].strip().rstrip(';'))
    contexts={}
    for c in annual:
        sheet=deepcopy(c['sheet']);age=c['age'];ref=[['',''] for _ in range(4)]
        contexts[str(c['id'])]=dict(document_id=100+age,lock_version=1,classroom_id=c['id'],classroom_name=c['name'],school_year=2026,age=age,nursery_name='見本保育園',owner_name='見本 はなこ',sheet=sheet,editable=True,reflection_editable=True,status='下書き',sources=[dict(key=sheet['origin']['key'],title='架空の年案',year=2026,class_name=c['name'])],references=c['references'],source_error=None,previous=[],reflection=ref,reflection_periods=c['reflection_periods'],reflection_columns=c['reflection_columns'],reflection_saved_at=None,reflection_states=[dict(period=i,values=['',''],version=1,locked=False,review_id=None,label='下書き',updated_at=None) for i in range(4)],created_at='2026-11-15 09:00')
    for c in annual:
        add(f'annual-{c["age"]}',f'年案・年間反省 · {c["age"]}歳児','指導計画','plan_docs/annual_library/sheet.html',dict(boot=contexts[str(c['id'])],classrooms=[NS(id=v['id'],name=v['name']) for v in annual],request=NS(app=NS(state=NS())),detail_mode=False),kind='annual',data={'contexts':contexts},note='年案保存は担任名、反省の承認確認は選択した期を確認します。反省の下書きは空欄でも仮保存できます。')

    t=PlanDocsIntegrationTests();t.setUp();t.client.cookies.update(t.staff_cookies())
    try:
        old_week=t.client.post('/plans/weekly-plans',data={'target_week':'','age_class':''})
        assert old_week.status_code==200 and old_week.context['errors']
        old_week.context['errors']=[]
        add('legacy-weekly','旧式の週案（旧POSTの再表示）','指導計画の周辺操作',old_week.template.name,old_week.context,note='通常の新規作成は現在の週案へ移動します。旧式POSTで入力エラーとなった場合の再表示を確認する画面です。')
        for key,title,url in [('legacy-annual','旧式の年案','/plans/annual-plans/new'),('legacy-monthly','旧式の月案','/plans/monthly-plans/new'),('bunrei','園文例の追加・ファイル取込','/plans/bunrei/facility/new')]:
            r=response(t,url);add(key,title,'指導計画の周辺操作',r.template.name,r.context)
        r=t.client.post('/plans/daily-plans',data={'target_date':'2026-11-16','classroom_ref':'ひよこ組','age_class':'2歳児','owner_name':'見本 はなこ','timeline_time':'10:00','timeline_children':'落ち葉を集めて遊ぶ見本です。','daily_aims':'秋の自然に親しむ。','daily_content':'架空の下書きです。'},follow_redirects=False)
        assert r.status_code==303
        location=r.headers['location'];detail=response(t,location)
        ctx=detail.context
        ctx['document'].status=DocumentStatus('approved')
        ctx['execution_changes']=[NS(id=10,status='recorded',corrects_change_id=None,changed_at=datetime(2026,11,16,10,tzinfo=timezone.utc),recorded_by_name='見本 はなこ',reason_label='天候',impact_label='軽微',reason_note='雨のため',before_snapshot={},after_snapshot={'heading':'室内遊び','time_label':'10:00','details':'架空の実施変更です。'},confirmation_comment='',confirmed_by_name=None,confirmed_at=None)]
        add('daily-reflection','日案の振り返り・実施変更','指導計画の周辺操作',detail.template.name,ctx,kind='daily-detail',note='振り返りの下書きは空欄可。承認確認へ進むときだけ本文を確認します。実施変更と訂正は別の操作です。')
        edit=response(t,location+'/edit');add('document-edit','保存済み帳票の修正','指導計画の周辺操作',edit.template.name,edit.context)
        user=ctx['user'];user=NS(**{k:getattr(user,k) for k in ('name','actor_ref','nursery_ref','classroom_refs')},can_edit=True,is_admin=True)
        common=dict(snapshot=dict(title='架空の反省',classroom='見本A組',owner='見本 はなこ',columns=['振り返り'],values=['友達と落ち葉を見せ合っていた。'],period=-1),document=ctx['document'],state=NS(version=1,status='pending',review_id=1),user=user,labels={'pending':'承認待ち'},input_url='daily-reflection.html',history=[],error='')
        add('reflection-request','反省の承認依頼確認','承認・確認依頼','plan_docs/reflections/review.html',{**common,'review':None},kind='reflection-request',note='未入力状態は、反省が空のまま確認画面へ来たケースです。理由から入力画面へ戻る案内を試せます。')
        review=NS(id=1,status='pending',requested_by=user.actor_ref,requested_by_name='見本 はなこ',created_at=datetime.now(),decided_by_name=None,decision_comment=None)
        add('reflection-decision','反省の承認・差し戻し','承認・確認依頼','plan_docs/reflections/review.html',{**common,'review':review},kind='reflection-decision')
    finally:t.tearDown()

    t=ChildRecordFeatureTests();t.setUp()
    try:
        with Session(t.engine) as s:
            c=s.get(Child,t.child_id);c.last_name='見本';c.first_name='はな';s.add(c);s.commit()
        r=response(t,f'/children/{t.child_id}/progress-records/new',params={'target_month':'2026-11'})
        r.context['logs']=[NS(id=1,observed_on=date(2026,11,10),categories=['遊び'],child_state='見本：落ち葉の色を見比べていた。',reflection='見本：発見を言葉にする姿が見られた。')]
        add('child-progress','児童票の入力・保存','園児の帳票・記録',r.template.name,r.context,kind='child-progress',note='通常の保存と「保存して切り替える」の両方を試せます。対象期間・参考ログ・各本文欄は現行どおりです。')
        r=response(t,f'/children/{t.child_id}/records/new')
        ctx=r.context;ctx['fields']=[dict(f) for f in ctx['fields']]+[dict(key='custom.mock',label='園独自の必須項目（見本）',required=True,enabled=True)]
        add('child-log','子どもの記録の追加','園児の帳票・記録',r.template.name,ctx,kind='child-log')
        ctx=dict(ctx)
        ctx.update(is_correction=True,log=NS(id=1,updated_at=datetime.now(),created_by=t.current_user.staff_id,visibility='private'),values={**ctx['values'],'child_state':'落ち葉の色を見比べていた。','correction_reason':''})
        add('child-log-correction','子どもの記録の訂正・無効化','園児の帳票・記録',r.template.name,ctx,kind='child-log')
    finally:t.client.close();t.engine.dispose()

    t=ChildHealthRouterTests();t.setUp()
    try:
        with Session(t.engine) as s:
            c=s.get(Child,t.child_id);c.last_name='見本';c.first_name='そら';s.add(c)
            record=HealthCheckRecord(child_id=t.child_id,check_type='periodic',checked_at=date(2026,11,15),height_cm=105,weight_kg=17,observer_name='見本 はなこ');s.add(record);s.commit();rid=record.id
        for key,title,url in [('health-check','健診・身体測定の追加',f'/children/{t.child_id}/health/check-records'),('health-correction','健診・身体測定の訂正',f'/children/{t.child_id}/health/check-records?edit={rid}'),('allergy','アレルギー情報の追加・更新',f'/children/{t.child_id}/health/allergies')]:
            r=response(t,url);add(key,title,'園児の帳票・記録',r.template.name,r.context,kind='health' if key.startswith('health') else 'allergy')
        with Session(t.engine) as s:
            aid=s.exec(select(ChildAllergy).where(ChildAllergy.child_id==t.child_id)).first().id
        r=response(t,f'/children/{t.child_id}/health/allergies?edit={aid}')
        add('allergy-edit','アレルギー情報の更新','園児の帳票・記録',r.template.name,r.context,kind='allergy')
    finally:t.tearDown()

    t=InstitutionalRecordRouterTests();t.setUp();authenticate_mock_staff(t.client)
    try:
        r=response(t,'/records/new');add('institutional-new','行事反省・経緯レコードの作成','行事・文書',r.template.name,r.context,kind='institutional')
        r=t.client.post('/records/',data={'title':'架空の行事反省','origin':'retrospective','fiscal_year':'2026','background':'見本の背景です。','purpose':'次回の活動につなぐ。','visibility':'staff'},follow_redirects=False)
        assert r.status_code==303,(r.status_code,r.text)
        edit=response(t,r.headers['location']+'/edit');add('institutional-edit','行事反省・経緯レコードの改訂','行事・文書',edit.template.name,edit.context,kind='institutional')
        cu=edit.context['current_user']
        add('document-request','文書の確認依頼','承認・確認依頼','document_reviews/list.html',dict(current_user=cu,items=[]),kind='document-request')
        admin=NS(can_edit=True,is_admin=True)
        item=NS(id=1,title='確認用の架空文書',body='見本の内容です。',requested_by_name='見本 はなこ',created_at=datetime.now(),status='pending',attachments=[])
        add('document-decision','文書の確認・差し戻し','承認・確認依頼','document_reviews/detail.html',dict(current_user=admin,item=item),kind='document-decision')
        highlight=NS(id=1,origin=InstitutionalRecordOrigin.retrospective,status=HighlightStatus.active,series_id=1,fiscal_year=2026,excerpt='道具の置き場所を分かりやすくする。',created_by='見本 はなこ',created_at=datetime(2026,11,15,9),comments=[NS(author='見本 はなこ',body='次回へ引き継ぐ架空のコメントです。')],promoted_record_id=None)
        series=NS(id=1,name='架空の秋の行事')
        add('meeting-markings','議事録のマーキング・コメント・昇格','行事・文書','meeting_notes/detail.html',dict(current_user=admin,note=NS(id=1,title='架空の職員会議',updated_by='見本 はなこ',updated_at=datetime(2026,11,15,9)),record_origin_options=list(InstitutionalRecordOrigin),event_series_list=[series],event_series_by_id={1:series},suggested_fiscal_year=2026,highlights=[highlight]),kind='meeting',note='抜き書き・コメント・経緯レコードへの昇格を確認します。本文は簡易編集の見本です。書式・写真・共同編集は今回の変更対象外です。')
    finally:t.tearDown()
    # Copy every stylesheet referenced by the rendered source; no remote dependencies.
    for page in pages:
        text=(HERE/(page['key']+'.html')).read_text(encoding='utf-8')
        for name in re.findall(r'href="assets/([^"?]+\.css)',text):
            if not (assets/name).exists() and (SOURCE/'static/css'/name).exists():
                (assets/name).write_text(read('static/css/'+name),encoding='utf-8')
    evidence=dict(date_jst='2026-11-15',source_commit=COMMIT,synthetic_data_only=True,production_connections=False,source_sha256=hashes,pages=pages)
    (HERE/'baseline.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (HERE/'catalog.js').write_text('window.FORM_CATALOG='+json.dumps([{k:p[k] for k in ('key','title','group','fields')} for p in pages],ensure_ascii=False)+';\n',encoding='utf-8')
    print('Rendered',len(pages),'pages from',COMMIT)

if __name__=='__main__':main()
