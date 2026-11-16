"""Render deployed parent-portal templates with fictional data, without app/DB imports."""
import ast
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from enum import Enum
from jinja2 import Environment, ChoiceLoader, DictLoader, FileSystemLoader

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASE=ROOT/'.local-dev/backup-v2-rollout-20261101/source'
OUT=HERE/'dist'
scope=dict(OUT=OUT,re=re,json=json)
for node in ast.parse((HERE/'build_screens.py').read_text(encoding='utf-8')).body:
    if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='shell' for t in node.targets) or isinstance(node,ast.FunctionDef) and node.name=='save':
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<fixture-helper>','exec'),scope)
shell,save=scope['shell'],scope['save']
extra=re.search(r'<style>(.*?)</style>',shell,re.S).group(1)
extra=extra[extra.index('.sample-head'):]
guard=re.search(r'<script>document.addEventListener.*?</script>',shell,re.S).group(0).replace('e.stopImmediatePropagation()','')
csp=re.search(r'<meta http-equiv="Content-Security-Policy"[^>]+>',shell).group(0)
base=(BASE/'templates/base.html').read_text(encoding='utf-8').replace('https://cdn.tailwindcss.com','../assets/tailwind.js')
base=re.sub(r'<script src="https://unpkg.com/htmx[^>]*></script>','',base)
base=re.sub(r'<link rel="manifest"[^>]+>','',base)
base=base.replace('</head>','<style>'+extra+'</style>'+csp+guard+'</head>')
base=base.replace('<body class="bg-slate-50 text-slate-800">','<body class="bg-slate-50 text-slate-800"><div class="sample-head"><strong>画面の見本</strong><span>名前・日付・内容は例です</span></div>')
env=Environment(loader=ChoiceLoader([DictLoader({'base.html':base}),FileSystemLoader(BASE/'templates')]),autoescape=True)
env.filters['jst_datetime']=env.filters['local_datetime']=lambda d,fmt='%Y-%m-%d %H:%M':d.strftime(fmt)
env.globals['static_asset_url']=lambda p:p
enums={'Enum':Enum}
for node in ast.parse((BASE/'models.py').read_text(encoding='utf-8')).body:
    if isinstance(node,ast.ClassDef) and node.name in {'ParentContactType','SurveyAnswerUnit'}:
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<deployed-labels>','exec'),enums)
day=date(2026,11,4);now=datetime(2026,11,4,8,0)
child=NS(id=9201,full_name='見本 あおい',classroom=NS(name='さくら組'))
parent=NS(display_name='見本 はなこ',child_links=[child])
notice=NS(id=9301,title='秋のお散歩のお知らせ',priority=NS(value='normal'),publish_start_at=now,created_at=now,attachments=[NS(id=9302,display_order=0,is_image=False,original_filename='持ち物のご案内（見本）.pdf',file_size=24576)])
survey=NS(id=9401,title='保育参加の希望日',description='参加できる日を教えてください。',answer_unit=enums['SurveyAnswerUnit'].child,closes_at=datetime(2026,11,10,17,0))
updates=[NS(kind='notice',url='/parent-portal/notices/9301',is_unread=True,is_important=False,title=notice.title,summary='持ち物と集合時間をご確認ください。',published_at_label='2026-11-04 08:00',closes_at_label=''),NS(kind='survey',url='/parent-portal/surveys/9401',is_unread=True,is_important=False,title=survey.title,summary=survey.description,published_at_label='2026-11-04 08:00',closes_at_label='2026-11-10 17:00')]
ctx=dict(request=NS(url=NS(path='/parent-portal/'),state=NS(csrf_token='sample-only')),current_parent_user=parent,parent_portal_mode=True,target_date_value=day.isoformat(),children=[child],child=child,entry_by_child_id={},reply_by_child_id={},pending_request_by_child_id={},reply_display_by_child_id={},recent_replies=[],flash_notice='',unread_notice_count=2,latest_updates=updates,notice='',form_error='')
files={'templates/base.html','templates/shared/_pickup_fields.html','templates/shared/_pickup_script.html','templates/parent_portal/_contact_quick_inputs.html','templates/parent_portal/_home_care_details.html','templates/parent_portal/_update_card.html','routers/parent_portal.py','models.py','survey_service.py'}
names=[]
def render(name,template,marks=(),script='',**kw):
    files.add('templates/parent_portal/'+template+'.html');names.append(name)
    save(name,env.get_template('parent_portal/'+template+'.html').render(**{**ctx,**kw}),script=script,marks=marks)

render('app-home','home',['input[name=date]','#child-information h3','a[href="/parent-portal/attention"]'])
render('app-menu','home',['nav details'],script='document.querySelector("nav details").open=true;')
render('app-home-empty','home',children=[],unread_notice_count=0,latest_updates=[])
fields='temperature bedtime wakeup_time sleep_notes breakfast_status breakfast_contents stool_consistency stool_count bowel_movement_status mood cough runny_nose medication condition_note contact_note absence_note absence_temperature absence_symptoms absence_diagnosis attendance_mode contact_type absence_reason'.split()
empty=dict.fromkeys(fields,'');empty.update(contact_type='present',attendance_mode='present')
filled={**empty,'temperature':'36.6','bedtime':'20:30','wakeup_time':'06:30','sleep_notes':'よく眠りました。','breakfast_status':'完食','breakfast_contents':'ごはん、みそ汁','stool_consistency':'normal','stool_count':'1','bowel_movement_status':'朝に1回','mood':'良好','cough':'なし','runny_nose':'なし','medication':'なし','condition_note':'いつもどおり元気です。','contact_note':'今日は母がお迎えに行きます。'}
pickup={'planned_pickup_time':'16:30','pickup_person':'母','snack_required':'0','pickup_revision':'sample-only'}
contact=dict(entry=None,published_reply=None,reply_display_items=[],pickup_editable=True,pickup_values=pickup,present_temperature_limit='37.5',present_temperature_error='体温が37.5℃以上のため、出席として送信できません。入力内容を確認し、欠席する場合は「欠席」を選択してください。',temperature_format_error='体温は数値で入力してください。')
for state,values in [('empty',empty),('filled',filled),('error',{**filled,'temperature':'37.8'})]:
    render('app-contact-'+state,'contact_form',script='document.querySelector("main form").requestSubmit();' if state=='error' else '',form_data=values,**{**contact,'pickup_values':{} if state=='empty' else pickup})
render('app-contact-top','contact_form',['label:has(input[name=attendance_mode][value=present])'],form_data=filled,**contact)
render('app-contact-care','contact_form',['#temperature','input[name=bedtime]'],script='document.querySelector("#temperature").parentElement.scrollIntoView();window.scrollBy(0,-40);',form_data=filled,**contact)
render('app-contact-bottom','contact_form',['textarea[name=contact_note]','main button[type=submit]'],script='document.querySelector("textarea[name=condition_note]").parentElement.scrollIntoView();window.scrollBy(0,-40);',form_data=filled,**contact)
for state,reason in [('private','absent_private'),('sick','absent_sick'),('error','absent_sick')]:
    values={**empty,'attendance_mode':'absent','contact_type':reason,'absence_reason':reason,'absence_note':'家庭の都合でお休みします。' if state=='private' else '自宅で休みます。','absence_temperature':'37.8' if state=='sick' else '','absence_symptoms':'発熱、鼻水' if state=='sick' else ''}
    render('app-absence-'+state,'contact_form',form_data=values,**{**contact,'form_error':'病欠の場合は現在の体温を入力してください。' if state=='error' else ''})
entry=NS(**filled,is_present_contact=True,updated_at=now,home_care_details=[('就寝','20:30'),('起床','06:30')]);entry.contact_type=enums['ParentContactType'].present
render('app-home-saved','home',['main > div:nth-child(2)','#child-information h3'],flash_notice='日次連絡を保存しました。',entry_by_child_id={child.id:entry})
absent=NS(is_present_contact=False,contact_type=enums['ParentContactType'].absent_sick,absence_reason_label='病欠',absence_temperature='37.8',absence_symptoms='発熱、鼻水',absence_note='自宅で休みます。',updated_at=now)
render('app-home-absence','home',flash_notice='日次連絡を保存しました。',entry_by_child_id={child.id:absent})
for state in ['empty','partial','filled','error']:
    values={} if state in ['empty','error'] else {'pickup_hour':'16'} if state=='partial' else pickup
    render('app-pickup-'+state,'pickup',day=day,revision='sample-only',record=None,pickup_values=values,error='',script='document.querySelector("main form").requestSubmit();' if state=='error' else '')
render('app-attention','attention',updates=updates)
render('app-notices','notices',updates=[NS(kind='notice',notice=notice,is_unread=False)])
render('app-notice','notice_detail',notice=notice,notice_body_html='<p>11月6日（金）に、公園へお散歩に行きます。</p><p>持ち物：水筒、帽子、歩きやすい靴</p><p>詳しくは、下の「持ち物のご案内」をご確認ください。</p>')
notification_constants={}
for node in ast.parse((BASE/'parent_notification_service.py').read_text(encoding='utf-8')).body:
    if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'ATTENDANCE_CONFIRMATION_TITLE','ATTENDANCE_CONFIRMATION_BODY'} for t in node.targets):
        notification_constants[node.targets[0].id]=ast.literal_eval(node.value)
files.add('parent_notification_service.py')
render('app-notification','notification_detail',notification=NS(created_at=now,title=notification_constants['ATTENDANCE_CONFIRMATION_TITLE'],body=notification_constants['ATTENDANCE_CONFIRMATION_BODY'],action_url='/parent-portal/children/9201/contact?date=2026-11-04'))
card=NS(survey=survey,closes_soon=False,answer=None,blocked=False,children=[NS(child=child,answer=None)])
render('app-surveys','surveys',survey_cards=[card])
questions=[NS(id=9501,label='希望する日',is_required=True,question_type=NS(value='single_choice'),options=[NS(id=9601,order=1,label='11月16日（月）'),NS(id=9602,order=2,label='11月17日（火）')]),NS(id=9502,label='園へ伝えたいこと',is_required=False,question_type=NS(value='text_long'))]
for state in ['empty','filled','error']:
    responses={9501:NS(value_option_ids=[9601]),9502:NS(value_text='母が参加します。')} if state=='filled' else {}
    render('app-survey-'+state,'survey_form',survey=survey,questions=questions,responses=responses,child_id=child.id,blocked=False,errors=['希望する日を入力してください。'] if state=='error' else [])
card.children[0].answer=NS(id=9701)
render('app-survey-done','surveys',notice='回答しました。',survey_cards=[card])
reply=NS(staff_name='見本 先生',published_at=datetime(2026,11,4,15,0),message='お散歩でどんぐりを見つけて、楽しそうに集めていました。')
render('app-history','history',history_items=[NS(entry=entry,child=child,child_id=child.id,target_date=day,reply=reply,reply_items=[])])
render('app-reply','contact_form',['#daily-contact-reply'],form_data=filled,**{**contact,'published_reply':reply,'entry':entry})
assert len(names)==29,len(names)
(HERE/'parent-app-baseline.json').write_text(json.dumps(dict(source_commit='285b67e7c0bec04afb40ac526626781182280779',synthetic_data_only=True,business_records_written=0,network_disabled=True,screens=names,viewport_only=['app-menu','app-contact-top','app-contact-care','app-contact-bottom'],source_files={f:hashlib.sha256((BASE/f).read_bytes()).hexdigest() for f in sorted(files)}),ensure_ascii=False,indent=2),encoding='utf-8')
print(f'Rendered {len(names)} parent app fixtures.')
