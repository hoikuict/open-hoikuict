"""SD-025: targeted fixture fixes; no live app, database or notification operations."""
from pathlib import Path
import runpy
import ast
import json
import hashlib

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
WORK=ROOT/'.local-dev/manual-audit-fixes-20261103'
WORK.mkdir(exist_ok=True,parents=True)
# The original builder only renders fictional templates. No browser or app actions.
ctx=runpy.run_path(str(HERE/'build_parent_app_screens.py'))
render,save,OUT,BASE=(ctx[k] for k in ['render','save','OUT','BASE'])
pickup=ctx['pickup'];day=ctx['day']
fields=['[data-pickup-fields] > fieldset:first-of-type','label:has(>select[name=pickup_person])','[data-pickup-fields] > fieldset:last-of-type']
for state in ['empty','partial','filled','error']:
    values={} if state in ['empty','error'] else {'pickup_hour':'16'} if state=='partial' else pickup
    render('app-pickup-'+state,'pickup',fields,day=day,revision='sample-only',record=None,pickup_values=values,error='',script='document.querySelector("main form").requestSubmit();' if state=='error' else '')
render('app-pickup-save','pickup',['main form > button'],day=day,revision='sample-only',record=None,pickup_values=pickup,error='',script='document.body.style.paddingBottom="600px";document.querySelector("label:has(>select[name=pickup_person])").scrollIntoView();window.scrollBy(0,-40);')
render('app-pickup-reopen','pickup',['main h1','div:has(>[data-selected-pickup-time])','select[name=pickup_person]','[data-pickup-fields] > fieldset:last-of-type'],day=day,revision='sample-only',record=None,pickup_values=pickup,error='')

# Re-render the original staff fixtures after unifying the fictional identity/date.
core=(HERE/'build_screens.py').read_text(encoding='utf-8')
core=core.replace('2026-11-02','2026-11-04').replace('datetime(2026,11,2,','datetime(2026,11,4,').replace("'hanako.sample'","'hanako@example.invalid'").replace("'hanako',10020","'hanako',100")
(HERE/'build_screens.py').write_text(core,encoding='utf-8')
staff=runpy.run_path(str(HERE/'build_screens.py'))
rows=[{**r,'departure':'16:30','missing':False,'bulk_eligible':False,'history':[dict(label='降園時刻を補記',before={'check_in_at':'08:30','check_out_at':None},after={'check_in_at':'08:30','check_out_at':'16:30'},reason='職員の記録で実際の降園時刻を確認したため',actor='見本 はなこ',at='2026-11-04 08:20')]} for r in staff['rows']]
NS=staff['NS']
monthly=staff['env'].get_template('attendance_monthly.html').render(data=dict(rows=rows,can_edit=True,is_admin=True,child_id=9001,child_name='見本 あおい',month='2026-10',return_query='',draft=None),notice='',error='',month='2026-10',classrooms=[NS(id=1,name='さくら組')],classroom_id=1,children=[NS(id=9001,full_name='見本 あおい',classroom_id=1)],child=NS(id=9001,full_name='見本 あおい',classroom_id=1),classroom_names={1:'さくら組'},rows=rows,current_user=staff['who'],missing_count=0,unknown_count=0,corrected_count=3,request=NS(state=NS(csrf_token='sample-only')))
staff['save']('monthly-saved',monthly,marks=['#monthly-rows tr:first-child td:nth-child(4)','#monthly-rows tr:first-child button[data-edit-day]'])
staff['save']('monthly-history',monthly,script='document.querySelector("#monthly-rows tr:first-child button").click();',marks=['#day-history'])

# Keep all four phone states on the same four input targets (never number Close).
for state in ['empty','partial']:
    p=OUT/'screens'/f'phone-{state}.html';html=p.read_text(encoding='utf-8')
    html=html.replace('mark(".check-open",1);','')
    marks=''.join('mark('+json.dumps(s)+','+str(i)+');' for i,s in enumerate(['select[name=method]','select[name=status]','input[name=note]','form[action] button[type=submit]'],1))
    html=html.replace("document.fonts.ready.then(()=>{document.documentElement.dataset.captureReady",marks+"document.fonts.ready.then(()=>{document.documentElement.dataset.captureReady",1)
    p.write_text(html,encoding='utf-8')

# Keep the number badges below the phone fields, clear of their labels.
for name in ['phone-empty','phone-partial','phone-filled']:
    p=OUT/'screens'/f'{name}.html';html=p.read_text(encoding='utf-8')
    html=html.replace('</head>', '<style>form:has(select[name=method]){margin-bottom:36px!important}.annotation span{left:0;top:auto;bottom:-32px}</style></head>')
    p.write_text(html,encoding='utf-8')

# Rebuild the permission diagrams and then use the existing admission fixture.
runpy.run_path(str(HERE/'build_notification_screens.py'))
safe_badges=['push-preferences','push-test','admission-access','app-pickup-empty','app-pickup-partial','app-pickup-filled','app-pickup-error','app-pickup-save','app-pickup-reopen']
badge_css='<style>.annotation span{left:-32px;top:-2px;width:28px;height:28px;font-size:16px;line-height:22px}</style>'
for name in safe_badges:
    p=OUT/'screens'/f'{name}.html';html=p.read_text(encoding='utf-8')
    assert '<head>' in html or '</head>' in html,name
    if badge_css not in html:html=html.replace('</head>',badge_css+'</head>')
    if name=='push-preferences':html=html.replace('</head>', '<style>.annotation:last-of-type span{left:auto;right:-32px}</style></head>')
    p.write_text(html,encoding='utf-8')

names=['app-notification','app-pickup-empty','app-pickup-partial','app-pickup-filled','app-pickup-error','app-pickup-save','app-pickup-reopen','monthly-saved','monthly-history','phone-empty','phone-partial','phone-filled','phone-saved','staff-list','password-admin','push-android-allow','push-preferences','push-test','admission-access']
manifest=dict(source_commit='285b67e7c0bec04afb40ac526626781182280779',synthetic_data_only=True,network_disabled=True,business_writes=0,screens=names,source_files={p:hashlib.sha256((BASE/p).read_bytes()).hexdigest() for p in ['parent_notification_service.py','templates/parent_portal/notification_detail.html','templates/parent_portal/profile.html','routers/parent_portal.py','templates/attendance_monthly.html','templates/parent_portal/pickup.html']})
(HERE/'audit-review-baseline.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Prepared '+str(len(names))+' targeted captures for SD-025.')
