"""Build an offline print mock from the deployed document template, using fictional data."""
from pathlib import Path
from types import SimpleNamespace as NS
import hashlib
import json
import re
import subprocess
from jinja2 import DictLoader, Environment, select_autoescape

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'.local-dev/attendance-production-20261004'
OUT=ROOT/'tools/daily-print-preview'
BASELINE='3392880660909e8471a8b437c6c002aa583fb220'
def git_file(name):
    return subprocess.check_output(['git','-c',f'safe.directory={SOURCE.as_posix()}','-C',str(SOURCE),'show',BASELINE+':'+name]).decode('utf-8')

def main():
    source=git_file('templates/plan_docs/documents/detail.html')
    base=git_file('templates/base.html')
    styles='\n'.join(re.findall(r'<style>(.*?)</style>',base,re.S)[:2])
    OUT.mkdir(exist_ok=True)
    (OUT/'deployed.css').write_text(styles,encoding='utf-8')
    # Preserve all business-screen fields; mock submissions never leave this page.
    source=re.sub(r'\s+hx-[\w-]+="[^"]*"','',source)
    source=re.sub(r'action="[^"]*"','action="#"',source)
    source=re.sub(r'href="[^"]*"','href="#"',source)
    source=source.replace('method="post"','method="get"')
    source=source.replace('onclick="window.print()"','data-preview-print')
    shell='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'">
<title>日案の印刷見本</title><link rel="stylesheet" href="deployed.css"><link rel="stylesheet" href="frame.css"></head>
<body><main class="plan-docs-content">{% block content %}{% endblock %}</main><script src="frame.js"></script></body></html>'''
    env=Environment(loader=DictLoader({'base.html':shell,'detail.html':source}),autoescape=select_autoescape(['html']))
    env.filters['jst_datetime']=lambda value,format='%Y-%m-%d %H:%M':str(value)
    # Twenty-two rows reproduce the sparse, multi-row shape of the supplied printout.
    rows=[
        ('','','','','・体調や機嫌を確かめる'),
        ('','','','','・ほかのクラスと移動の順番を合わせる'),
        ('','','','','・抱っこや歩行など、一人ひとりに合わせて移動する'),
        ('9:50','','・遊戯室へ移動','',''),
        ('10:00','','○みんなの集い','・歌や手遊びを一緒に楽しむ',''),
        ('','','・朝のあいさつ','','・子どもの位置と動線を確認する'),
        ('','','・友達の紹介','・安心して参加できるよう、そばで声をかける',''),
        ('','','・絵本を見る','','・見やすい位置に座り、興味が続くよう配慮する'),
        ('','','・歌の贈り物','・声や身振りに応え、楽しさを共有する','・座る場所を変えたい子には近くで付き添う'),
        ('','','・手作りカードを受け取る','',''),
        ('','','・季節の歌','・慣れない雰囲気の子には、個別に関わる',''),
        ('','','・保育士の出し物','',''),
        ('','','','・ほかのクラスの動きを見ながら移動を始める',''),
        ('','','台の上の物に手を伸ばす子がいる','・人数を確かめる',''),
        ('','','幕の後ろに入ろうとする','',''),
        ('','','眠くなっている子がいる','',''),
        ('','','・保育室へ移動','',''),
        ('10:30','','・おむつ替え','',''),
        ('','','・水分補給','',''),
        ('','','・室内遊び','',''),
        ('','','（天候によりテラス遊び）','',''),
        ('11:00','','・給食','',''),
    ]
    schedule=NS(layout='daily_timeline',columns=[NS(key=k,title=t) for k,t in [('children','子どもの様子'),('support','保育士の援助'),('considerations','配慮事項')]],rows=[])
    for index,(time,label,children,support,care) in enumerate(rows):
        schedule.rows.append(NS(row_key=f'row_{index+1}',order=index,start_time=time,label=label,cells={k:NS(body=v,needs_confirmation=False) for k,v in [('children',children),('support',support),('considerations',care)]}))
    document=NS(id=1,title='2026-10-01 日案（ことり組）',document_type=NS(value='daily_plan'),document_type_label='日案',
        nursery_label='見本保育園',classroom_label='ことり組（0歳児）',owner_name='見本の保育士',status=NS(value='in_review'),status_label='レビュー待ち',
        can_edit_body=True,period_start=None,period_end=None,school_year=None,target_month=None,target_week=None,target_date='2026-10-01',confirmation_items=[],schedule=schedule,
        sections=[NS(section_key=k,title=t,body=b,evidence_tags=['入力'],needs_confirmation=False) for k,t,b in [
            ('daily_goal','ねらい','・集いの雰囲気を楽しみ、感じたことを身振りや声で表す。'),
            ('daily_content','内容（活動）','・みんなの集い、室内遊び')]])
    user=NS(is_admin=False,can_edit=True,name='見本の保育士')
    states={
        'empty':('', 'missing','振り返り未入力',[]),
        'partial':('集いでは歌に合わせて体を揺らす姿が見られた。','draft','振り返り下書き',[]),
        'filled':('集いでは歌や手遊びに笑顔で応じる姿が見られた。\n眠気のある子は静かな場所で休めるようにした。次回も一人ひとりの生活リズムに合わせて参加する。','submitted','振り返り提出済み',[
            NS(id=1,reason_code='weather',impact_level='minor',changed_at='2026-10-01 10:30',recorded_by='見本の保育士',approval_state_at_change='in_review',reason_note='小雨のため、室内で遊んだ。',
               before_snapshot={'row_key':'row_21','start_time':'10:30','label':'テラス遊び','cells':{}},after_snapshot={'time_label':'10:30','heading':'室内遊び','details':'マットと柔らかい積み木を用意し、好きな場所で遊べるようにした。'},confirmation_status='not_required',corrects_change_id=None)
        ]),
        'error':('', 'missing','振り返り未入力',[]),
    }
    for key,(body,state,label,changes) in states.items():
        markup=env.get_template('detail.html').render(document=document,user=user,monthly_boot=None,annual_boot=None,can_edit_document=True,
            lock_version=1,revisions=[1],approval_details=None,rejection_details=None,execution_changes=changes,
            reason_labels={'weather':'天候','condition':'子どもの体調','other':'その他'},impact_labels={'minor':'軽微','major':'重大'},
            changed_at_default='2026-10-01T10:30',reflection=NS(body=body,submitted_at='2026-10-01 16:00' if state=='submitted' else None),
            reflection_state=state,reflection_state_label=label,reflection_reminder_time='16:30')
        (OUT/(key+'.html')).write_text(markup,encoding='utf-8')
    (OUT/'baseline.json').write_text(json.dumps({'app_commit':BASELINE,'template_sha256':hashlib.sha256(git_file('templates/plan_docs/documents/detail.html').encode()).hexdigest(),
        'base_sha256':hashlib.sha256(base.encode()).hexdigest(),'fictional_data_only':True,'business_fields_preserved':True,'timeline_rows':22,
        'production_connections':False,'saves_to_database':False,'states':list(states)},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Built four offline states from deployed template; 22 fictional timeline rows.')

if __name__=='__main__':main()
