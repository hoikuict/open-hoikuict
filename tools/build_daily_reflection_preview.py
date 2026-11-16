"""Render the deployed daily detail with fictional rows inside the review mock."""
from pathlib import Path
from types import SimpleNamespace as NS
import json
import re
from jinja2 import Environment,DictLoader,select_autoescape

def build(out,git):
    rows=json.loads((out/'daily-fixture.json').read_text(encoding='utf-8'))
    template=git('templates/plan_docs/documents/detail.html')
    template=re.sub(r'\s+hx-[\w-]+="[^"]*"','',template)
    template=re.sub(r'action="[^"]*"','action="#"',template)
    template=template.replace('method="post"','method="get"').replace('onclick="window.print()"','data-day-print')
    template=template.replace('/static/css/daily-plan-print.css','daily-plan-print.css').replace('/static/js/daily-plan-print.js','daily-plan-print.js')
    template=template.replace('振り返りを提出</button>','承認確認へ進む</button>')
    template=template.replace('入力内容は自動で下書き保存されます。提出後に書き換えると再提出が必要になります。','入力内容は自動で下書き保存されます。承認確認で依頼を確定すると管理者の通知に載ります。')
    shell='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'">
<link rel="stylesheet" href="base.css"><link rel="stylesheet" href="daily-frame.css"><link rel="stylesheet" href="review-preview.css">{% block head %}{% endblock %}</head><body><main class="plan-docs-content"><p class="mock-day-message no-print" id="day-message" role="status">日案の反省と承認の見本です。入力・保存・承認依頼はこの画面内だけの動作です。</p>{% block content %}{% endblock %}</main>{% block body_end %}{% endblock %}<script src="daily-frame.js"></script></body></html>'''
    env=Environment(loader=DictLoader({'base.html':shell,'detail.html':template}),autoescape=select_autoescape(['html']))
    env.filters['jst_datetime']=lambda value,format='%Y-%m-%d %H:%M':str(value)
    schedule=NS(layout='daily_timeline',columns=[NS(key=k,title=t) for k,t in [('children','子どもの様子'),('support','保育士の援助'),('considerations','配慮事項')]],rows=[])
    for i,row in enumerate(rows):
        schedule.rows.append(NS(row_key=f'row_{i+1}',order=i,start_time=row[0],label='',cells={k:NS(body=v,needs_confirmation=False) for k,v in zip(['children','support','considerations'],row[1:])}))
    doc=NS(id=1,title='2026-10-01 日案（ことり組）',document_type=NS(value='daily_plan'),document_type_label='日案',nursery_label='見本保育園',classroom_label='ことり組（0歳児）',owner_name='見本の保育士',status=NS(value='approved'),status_label='承認済み',can_edit_body=False,period_start=None,period_end=None,school_year=None,target_month=None,target_week=None,target_date='2026-10-01',confirmation_items=[],schedule=schedule,
        sections=[NS(section_key=k,title=t,body=b,evidence_tags=['入力'],needs_confirmation=False) for k,t,b in [('daily_goal','ねらい','集いの雰囲気を楽しみ、感じたことを身振りや声で表す。'),('daily_content','内容（活動）','みんなの集い、室内遊び')]])
    change=NS(id=1,reason_code='weather',impact_level='minor',changed_at='2026-10-01 10:30',recorded_by='見本の保育士',approval_state_at_change='approved',reason_note='小雨のため室内で遊んだ。',before_snapshot={'row_key':'row_21','start_time':'10:30','label':'テラス遊び','cells':{}},after_snapshot={'time_label':'10:30','heading':'室内遊び','details':'マットと柔らかい積み木を用意し、好きな場所で遊べるようにした。'},confirmation_status='not_required',corrects_change_id=None)
    markup=env.get_template('detail.html').render(document=doc,user=NS(is_admin=False,can_edit=True,name='見本の保育士'),monthly_boot=None,annual_boot=None,can_edit_document=True,lock_version=1,revisions=[1],approval_details=NS(actor_name='見本の管理者',decided_at='2026-10-01 08:00'),rejection_details=None,execution_changes=[change],reason_labels={'weather':'天候','condition':'子どもの体調','other':'その他'},impact_labels={'minor':'軽微','major':'重大'},changed_at_default='2026-10-01T10:30',reflection=NS(body='',submitted_at=None),reflection_state='missing',reflection_state_label='反省未入力',reflection_reminder_time='16:30')
    (out/'daily-frame.html').write_text(markup,encoding='utf-8')
    for path in ['static/css/daily-plan-print.css','static/js/daily-plan-print.js']:(out/Path(path).name).write_text(git(path),encoding='utf-8')
