"""Offline proposal based on deployed annual templates, with fictional content only."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
import re
import subprocess
from types import SimpleNamespace as NS
from jinja2 import Environment, DictLoader, select_autoescape

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'.local-dev/attendance-production-20261004'
INPUT=ROOT/'.local-dev/annual-r8-20260929/annual-runtime'
OUT=ROOT/'tools/annual-creation-preview'
BASELINE='0291f13ca33771e7d03bf533f396590645b00b8f'

def git(name):
    return subprocess.check_output(['git','-c',f'safe.directory={SOURCE.as_posix()}','-C',str(SOURCE),'show',BASELINE+':'+name]).decode('utf-8')

def fictional(text,label=''):
    sample='一人ひとりの気持ちを受け止め、安心して過ごせるようにする。身近な遊びを通して、友達や保育者との関わりを楽しむ。'
    length=max(24,min(180,len(text)))
    return '・'+(sample*4)[:length]+'。'

def build_data():
    result=[]
    for age,(key,name) in enumerate(zip(['kiichigo','donguri','kurumi','ume','take','matsu'],['ひよこ組','ことり組','こぐま組','うさぎ組','きりん組','そら組'])):
        original=json.loads((INPUT/f'{key}-r8-data.json').read_text(encoding='utf-8'))
        periods=deepcopy(original.get('periods',[{'label':x} for x in ['1期（4〜5月）','2期（6〜8月）','3期（9〜12月）','4期（1〜3月）']]))
        data={'schema':original['schema'],'source':{'title':f'取り込み元の見本年案（{age}歳児）','url':'#source-example','sheet':'見本','range':original['source']['range'],'year':2026,'age':age,'className':'原本の見本クラス','ownerText':'原本の担任A・原本の担任B'},'fields':[],'sections':[],'periods':periods}
        allowed=['id','kind','label','period','sourceCell','sourceLine','category','estimateValue','positionRatio','positionStatus','axis']
        def convert(item):
            out={k:deepcopy(item[k]) for k in allowed if k in item}
            if len(out.get('label',''))>40:out['label']='本文'
            out['text']=fictional(item['text']);out['rawLine']=out['text']
            return out
        data['fields']=[convert(x) for x in original['fields']]
        for s in original['sections']:
            data['sections'].append({**{k:deepcopy(s[k]) for k in ['kind','axis','ticks'] if k in s},'items':[convert(x) for x in s['items']]})
        for k in ['grid','annualFields']:
            if k in original:data[k]=deepcopy(original[k])
        if data.get('grid'):
            for row in data['grid']['rows']:
                for cell in row:
                    if cell.get('field'):cell['text']=''
        definitions=data['fields']+[x for s in data['sections'] for x in s['items']]
        fields={x['id']:{'body':x['text'],'start':x.get('estimateValue'),'position_ratio':x.get('positionRatio'),'confirmed':x.get('positionStatus')=='explicit_annual'} for x in definitions}
        refs=json.loads((INPUT/f'{key}-r8-references.json').read_text(encoding='utf-8'))
        primary=next(r for r in refs if r['primary'])
        reflect_periods=[re.sub(r'\s+','',row[0]['text']) for row in primary['grid']['rows'] if row and re.match(r'^[ⅠⅡⅢⅣIV1-4１２３４]+期',row[0]['text'].strip())]
        assert len(reflect_periods)==4,(key,reflect_periods)
        columns=['生活','遊び'] if age<3 else ['基本的事項','五領域']
        reference={'source':{'title':'過去の反省の見本（架空）','sheet':'参考資料','url':'#reference-example','range':'見本'},'status':'記入済みの参考資料','primary':False,'grid':{'widths':[16,42,42],'rows':[
            [{'text':'期','rowspan':1,'colspan':1},*[{'text':c,'rowspan':1,'colspan':1} for c in columns]],
            *[[{'text':p,'rowspan':1,'colspan':1},*[{'text':'参考資料の架空の文章です。反省の入力欄へは引き継ぎません。' if i<2 else '', 'rowspan':1,'colspan':1} for _ in columns]] for i,p in enumerate(reflect_periods)]
        ]}}
        references=[]
        for index,ref in enumerate(refs,1):
            item=deepcopy(reference)
            item['source']['title']=f'過去の反省・参考資料の見本 {index}（架空）'
            item['status']='記入済みの参考資料' if ref['primary'] else '参考資料'
            references.append(item)
        result.append({'id':age+1,'name':name,'age':age,'teachers':[f'見本 花{age+1}',f'見本 空{age+1}'],'reflection_periods':reflect_periods,'reflection_columns':columns,
            'sheet':{'schema_version':1,'template_id':'annual-infant-1-v1' if age==1 else 'annual-grid-v1','age':age,'classroom_id':age+1,'periods':periods,'source':data,'fields':fields,'baseline':deepcopy(fields),'baseline_label':'取り込み元の見本','origin':{'kind':'source','key':f'source-{age}'},'source_digest':'0'*64},'references':references})
    return result

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    data=build_data()
    (OUT/'fixtures.js').write_text('window.ANNUAL_PREVIEW_FIXTURES='+json.dumps(data,ensure_ascii=False)+';\n',encoding='utf-8')
    template=git('templates/plan_docs/annual_library/_sheet.html')
    template=template.replace('<section class="annual-reflections"','<section id="annual-reflection-editor" aria-label="年間指導計画反省"></section>\n      <section class="annual-reflections"')
    template=template.replace('<div class="rd-source no-print">','<p class="creation-note no-print" id="creation-note"></p><nav class="section-jumps no-print"><a href="#annual-plan-sheet">計画・基本情報</a><a href="#annual-reflection-editor">年間指導計画反省へ</a></nav>\n      <div class="rd-source no-print">',1)
    env=Environment(loader=DictLoader({'sheet':template}),autoescape=select_autoescape())
    env.globals['static_asset_url']=lambda path:Path(path).name
    markup=env.get_template('sheet').render(boot={},classrooms=[NS(id=d['id'],name=d['name']) for d in data],request=NS(app=NS(state=NS())),detail_mode=False)
    base=git('templates/base.html')
    (OUT/'base.css').write_text('\n'.join(re.findall(r'<style>(.*?)</style>',base,re.S)[:2]),encoding='utf-8')
    (OUT/'annual-library.css').write_text(git('static/css/annual-library.css'),encoding='utf-8')
    script=git('static/js/annual-library.js')
    script=script.replace("let boot = JSON.parse(document.getElementById('annual-library-boot').textContent);","let boot = window.AnnualMock.initial();\n  let reflection = [], savedReflection = '[]';")
    script=script.replace("const dirty = () => boot.sheet && value() !== saved;","const dirtyPlan = () => boot.sheet && value() !== saved;\n  const dirtyReflection = () => JSON.stringify(reflection) !== savedReflection;\n  const dirty = () => dirtyPlan() || dirtyReflection();")
    script=script.replace("el.readOnly = flag || !editable();","el.readOnly = flag || (el.hasAttribute('data-reflection') ? (!boot.reflection_editable || window.ReflectionReview.isLocked(reflectionKey(Number(el.dataset.reflection.split(':')[0])))) : !editable());")
    script=script.replace("    if ($('#annual-import')) $('#annual-import').disabled = flag || !editable() || !!boot.document_id || !$('#annual-origin').value;", "    if ($('#annual-import')) $('#annual-import').disabled = flag || !editable() || !!boot.document_id || !$('#annual-origin').value;\n    if ($('#reflection-save')) $('#reflection-save').disabled=flag || !boot.sheet || !boot.reflection_editable;\n    if ($('#reflection-reset')) $('#reflection-reset').disabled=flag || !boot.reflection_editable;\n    if ($('#reflection-review')) $('#reflection-review').disabled=flag || !boot.sheet || !boot.reflection_editable;")
    script=script.replace("    renderReferences();","    renderReferences(); renderReflection();")
    script=script.replace("    boot = data;","    boot = data;\n    reflection = clone(data.reflection_draft || data.reflection); savedReflection = JSON.stringify(data.reflection);")
    script=script.replace("    renderSheet(); setBusy(false);","    renderSheet(); setBusy(false);\n    window.AnnualMock.current = () => ({boot:clone(boot),reflection:clone(reflection),planDirty:dirtyPlan(),reflectionDirty:dirtyReflection()});")
    start=script.index('  async function api(');end=script.index('  async function load(',start)
    script=script[:start]+"  async function api(path, options = {}) { return window.AnnualMock.api(path, options, boot); }\n"+script[end:]
    script=re.sub(r'^.*history\.replaceState.*\n','',script,flags=re.M)
    script=script.replace("      adopt(data); message('保存しました。承認・文書情報から確認を依頼できます。');","      data.reflection_draft=clone(reflection); adopt(data); message('年案を保存しました。反省を記入し、承認確認へ進めます。');")
    script=script.replace("window.addEventListener('beforeunload'","window.addEventListener('annual-preview-reset',()=>{adopt(window.AnnualMock.initial());message('確認用の状態を切り替えました。');});\n  window.addEventListener('annual-preview-reopen',()=>{if(!dirty()||confirm('未保存の入力を取り消して開き直しますか？')){adopt(window.AnnualMock.reopen(boot));message('保存した内容を開き直しました。');}});\n  window.addEventListener('beforeunload'")
    script=script.replace("    root.querySelectorAll('.rd-field textarea,#annual-owner').forEach(fit);","    root.querySelectorAll('.rd-field textarea,#annual-owner,[data-reflection]').forEach(fit);")
    script=script.replace("    if (button.id === 'annual-save') save();","    if (button.id === 'annual-save') save();")
    script=script.replace("  adopt(boot);",(OUT/'reflection-extension.js').read_text(encoding='utf-8')+'\n  adopt(boot);')
    (OUT/'annual-library.js').write_text(script,encoding='utf-8')
    shell=(OUT/'shell.html').read_text(encoding='utf-8')
    (OUT/'index.html').write_text(shell.replace('<!-- ANNUAL_SHEET -->',markup),encoding='utf-8')
    from build_daily_reflection_preview import build
    build(OUT,git)
    report={'baseline_commit':BASELINE,'fictional_data_only':True,'database_connections':False,'external_requests':False,'field_counts':{str(d['age']):len(d['sheet']['fields']) for d in data},'source_hashes':{p:hashlib.sha256(git(p).encode()).hexdigest() for p in ['templates/plan_docs/annual_library/_sheet.html','static/js/annual-library.js','static/css/annual-library.css']}}
    (OUT/'baseline.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
