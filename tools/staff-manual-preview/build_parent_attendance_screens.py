"""Photograph the deployed guardian terminal with invented data and no network writes."""
import ast
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
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
base=(BASE/'templates/guardian/terminal_base.html').read_text(encoding='utf-8')
base=base.replace('https://cdn.tailwindcss.com','../assets/tailwind.js')
base=re.sub(r'<link rel="(?:manifest|icon)"[^>]+>','',base)
# No heartbeat, registration, real-time clock, automatic return, or submission transport.
base=re.sub(r'<script src="/guardian/assets/terminal.js[^>]+></script>','',base)
base=base.replace('</head>','<style>'+extra+'</style>'+csp+guard+'</head>')
base=base.replace('  <header','  <div class="sample-head"><strong>画面の見本</strong><span>名前・日付・時刻は説明用です</span></div><header',1)
base=base.replace('--:--:--','{{ sample_clock }}')
env=Environment(loader=ChoiceLoader([DictLoader({'guardian/terminal_base.html':base}),FileSystemLoader(BASE/'templates')]),autoescape=True)
classes=[NS(id=9101,name='さくら組'),NS(id=9102,name='たんぽぽ組'),NS(id=9103,name='ひまわり組'),NS(id=9104,name='すみれ組')]
children=[NS(id=9201,full_name='見本 あおい'),NS(id=9202,full_name='見本 ひなた'),NS(id=9203,full_name='見本 そら'),NS(id=9204,full_name='見本 はる')]
ctx=dict(request=NS(state=NS(csrf_token='sample-only')),terminal_mode=True,terminal_today='2026-11-04',target_date_value='2026-11-04',terminal_server_now='',terminal_start='/guardian/terminal',terminal_idle_seconds=90,terminal_ready=True,terminal_registration_number='',closing_time='19:00',kiosk_closed=False,sample_clock='08:30:00',classrooms=classes,children=children,selected_classroom=None,selected_child=None,selected_record=None,notice_message='',can_depart=False,pickup_person_options=['母','父','祖父','祖母','ファミリーサポート','その他'])
files={'templates/guardian/terminal_base.html','templates/shared/_pickup_fields.html','templates/shared/_pickup_script.html','routers/guardian.py','guardian_arrival.py','guardian_terminal.py','assets/guardian/terminal.js'}
names=[]
def render(name,template,marks=(),script='',**kw):
    files.add('templates/'+template);names.append(name)
    save(name,env.get_template(template).render(**{**ctx,**kw}),script=script,marks=marks)

render('terminal-classes','guardian/kiosk.html',['a[href*="class_id=9101"]'])
render('terminal-names','guardian/kiosk.html',['a[href*="child_id=9201"]'],selected_classroom=classes[0])
ctx.update(selected_classroom=classes[0],selected_child=children[0])
render('terminal-arrival','guardian/kiosk.html',['section h2','button[data-punch]'])
for state in ['empty','partial','filled','error','extra']:
    values={} if state in ['empty','error'] else {'pickup_hour':'16'} if state=='partial' else {'planned_pickup_time':'16:30','pickup_person':'母','snack_required':'0'}
    script=''
    marks=['[data-pickup-hour="16"]','[data-pickup-minute="30"]','[data-pickup-person="母"]','[data-pickup-fields] fieldset:last-of-type','button[type=submit]'] if state=='filled' else []
    if state=='error':script='document.querySelector("main form").requestSubmit();'
    if state=='extra':script='document.querySelectorAll("[data-pickup-fields] details").forEach(d=>d.open=true);'
    render('terminal-pickup-'+state,'guardian/pickup_form.html',marks,script, pickup_values=values,pickup_revision='sample',arrival_token='sample-only')
render('terminal-confirm','guardian/pickup_confirm.html',['section dl','form:last-child button'],arrival_at=datetime(2026,11,4,8,30),planned_pickup_time='16:30',pickup_person='母',snack_required=False,arrival_token='sample-only',pickup_revision='sample')
render('terminal-arrival-done','guardian/pickup_done.html',['main h1'],message='登園を受け付けました。',redirect_url='/guardian/terminal',redirect_ms=1000)
record=NS(check_in_at=datetime(2026,11,4,8,30),check_out_at=None,pickup_person='母',actual_pickup_person=None)
ctx.update(selected_record=record,can_depart=True,sample_clock='16:30:00')
for state in ['empty','filled','error']:
    script='document.querySelector("[data-actual-pickup=母]").click();' if state=='filled' else 'document.querySelector("[data-departure-form]").requestSubmit();' if state=='error' else ''
    render('terminal-departure-'+state,'guardian/kiosk.html',['section h2','[data-actual-pickup=母]','button[data-punch]'] if state=='filled' else [],script)
render('terminal-departure-done','guardian/pickup_done.html',['main h1'],message='降園を受け付けました。',redirect_url='/guardian/terminal',redirect_ms=1000)
record.check_out_at=datetime(2026,11,4,16,30);record.actual_pickup_person='母'
render('terminal-already','guardian/kiosk.html',['section h3'])
render('terminal-offline','guardian/kiosk.html',script='''document.getElementById('terminal-warning').hidden=false;document.getElementById('terminal-warning-message').textContent='通信が切れています。打刻は送信されません。職員にお知らせください。';document.getElementById('terminal-connection').textContent='接続を確認してください';''',selected_classroom=None,selected_child=None,selected_record=None)
assert len(names)==16
(HERE/'parent-attendance-baseline.json').write_text(json.dumps(dict(source_commit='285b67e7c0bec04afb40ac526626781182280779',deployment_record='docs/deployment-login-manual-link-2026-11-03.md',synthetic_data_only=True,business_records_written=0,network_disabled=True,automatic_return_paused_for_screenshots=True,screens=names,source_files={f:hashlib.sha256((BASE/f).read_bytes()).hexdigest() for f in sorted(files)}),ensure_ascii=False,indent=2),encoding='utf-8')
print('Rendered 16 parent attendance fixtures from deployed templates.')
