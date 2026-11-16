"""Render deployed-template samples with invented data, without importing the app."""
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace as NS
import hashlib
import json
import re
import shutil

from jinja2 import Environment, FileSystemLoader, DictLoader, ChoiceLoader

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent / 'dist'
BASE = ROOT / '.local-dev/backup-v2-rollout-20261101/source'
FILES = ['templates/attendance_checks/_row_card.html', 'templates/attendance_monthly.html',
         'templates/staff_auth/authentication.html', 'templates/staff_auth/reset_password.html',
         'templates/staff_auth/users.html', 'templates/settings/_back.html',
         'static/css/attendance-monthly.css', 'static/js/attendance-monthly.js']
OUT.joinpath('screens').mkdir(parents=True, exist_ok=True)
OUT.joinpath('assets').mkdir(exist_ok=True)
evidence = {'date': '2026-11-03 JST', 'source': str(BASE),
            'deployed_baseline': '225ea99d8ca39f773dd9b8e0920bca13854817b5',
            'latest_deployment_record': 'docs/deployment-billing-reopen-2026-11-01.md',
            'latest_deployment_changes_these_templates': False,
            'live_server_checked': False, 'synthetic_data_only': True, 'files': {}}
for path in FILES:
    data = BASE.joinpath(path).read_bytes()
    evidence['files'][path] = {'sha256': hashlib.sha256(data).hexdigest(),
                             'matches_workspace_normalized': data.replace(b'\r\n', b'\n') == ROOT.joinpath(path).read_bytes().replace(b'\r\n', b'\n')}
shutil.copyfile(ROOT / 'tools/staff-auth-print-preview/tailwind.js', OUT / 'assets/tailwind.js')
shutil.copyfile(BASE / 'static/css/attendance-monthly.css', OUT / 'assets/attendance-monthly.css')
shutil.copyfile(BASE / 'static/js/attendance-monthly.js', OUT / 'assets/attendance-monthly.js')

shell = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; form-action 'none'; base-uri 'none'"><title>架空データの画面見本</title><script src="../assets/tailwind.js"></script><style>
body{background:#f8fafc;color:#1e293b;font-family:'Yu Gothic UI','Meiryo',sans-serif;margin:0}main{padding:22px 30px;max-width:1200px;margin:auto}.sample-head{padding:14px 30px;background:#fff;border-bottom:1px solid #e2e8f0;display:flex;justify-content:space-between;font-size:14px}.check-row{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px}.check-summary{display:flex;align-items:center;gap:18px;flex-wrap:wrap}.check-name strong{font-size:20px}.check-name small{display:block;font-size:13px;color:#64748b}.alarm-dot{color:#be123c}.check-category{border-radius:20px;background:#fef3c7;padding:5px 12px}.check-status{display:flex;gap:5px;margin-left:auto}.check-status button,.check-open{border:1px solid #cbd5e1;border-radius:5px;padding:6px 10px}.check-status button[aria-pressed=true]{background:#4338ca;color:white}.check-times,.check-parent{font-size:14px}.annotation{position:absolute;z-index:9999;border:3px solid #d34c26;border-radius:7px;pointer-events:none}.annotation span{position:absolute;top:-18px;left:-14px;background:#bd3d1b;color:white;border:3px solid white;border-radius:50%;width:32px;height:32px;text-align:center;font:bold 18px/26px sans-serif}.sample-note{background:#fff7ed;border-left:4px solid #c2410c;padding:10px;margin:12px 0;font-size:14px}
</style><script>document.addEventListener('submit',e=>{e.preventDefault();e.stopImmediatePropagation()},true);document.addEventListener('click',e=>{if(e.target.closest('a'))e.preventDefault()},true);</script></head><body><div class="sample-head"><strong>オープン保育ICT</strong><span>説明用の画面見本 · 氏名・記録はすべて架空</span></div><main>{% block content %}{% endblock %}</main></body></html>'''
env = Environment(loader=ChoiceLoader([DictLoader({'base.html': shell}), FileSystemLoader(BASE / 'templates')]), autoescape=True)
env.filters['jst_datetime'] = lambda d, fmt='%Y-%m-%d %H:%M': d.strftime(fmt)

def save(name, html, script='', marks=()):
    html = html.replace('/static/css/attendance-monthly.css?v=20261004', '../assets/attendance-monthly.css').replace('/static/js/attendance-monthly.js?v=20261004', '../assets/attendance-monthly.js')
    # No form keeps a live action, even if opened outside the intended static server.
    html = re.sub(r'action="[^"]*"', 'action="#"', html)
    js = 'window.addEventListener("load",()=>{' + script
    js += ''';const openDialog=document.querySelector('dialog[open]');if(openDialog){openDialog.close();openDialog.setAttribute('open','');openDialog.style.cssText='position:relative;max-height:none;margin:20px auto;width:100%;overflow:visible';openDialog.querySelector('footer').style.position='static';const am=document.getElementById('attendance-monthly');for(const item of am.children){if(item!==openDialog)item.hidden=true;}const n=document.createElement('p');n.className='sample-note';n.textContent='説明用に入力画面を縦に展開しています。実際の画面ではスクロールして確認します。';am.prepend(n);}requestAnimationFrame(()=>{'''
    for i, selector in enumerate(marks, 1):
        js += 'mark(' + json.dumps(selector) + ',' + str(i) + ');'
    js += '''document.fonts.ready.then(()=>{document.documentElement.dataset.captureReady='true';});});});
function mark(selector,n){
  const e=document.querySelector(selector);if(!e)throw new Error('Missing annotation target: '+selector);
  const a=document.createElement('div');a.className='annotation';a.dataset.target=selector;
  a.innerHTML='<span>'+n+'</span>';const dialog=e.closest('dialog');(dialog||document.body).append(a);
  const position=()=>{const r=e.getBoundingClientRect();const d=dialog?dialog.getBoundingClientRect():{left:0,top:0};
    a.style.left=(r.left-d.left+(dialog?dialog.scrollLeft:scrollX)-4)+'px';
    a.style.top=(r.top-d.top+(dialog?dialog.scrollTop:scrollY)-4)+'px';
    a.style.width=(r.width+8)+'px';a.style.height=(r.height+8)+'px';};
  position();new ResizeObserver(position).observe(document.querySelector('main'));
  window.addEventListener('resize',position);document.fonts.ready.then(position);
}'''
    html = html.replace('</body>', '<script>' + js + '</script></body>')
    (OUT / 'screens' / (name + '.html')).write_text(html, encoding='utf-8')

who = NS(can_manage_attendance_checks=True, can_edit=True, is_admin=True, name='見本 はなこ')
contact = NS(id=1, action='received', method='phone', status=NS(label='病欠'), recorded_by_name='見本 はなこ', created_at=datetime(2026,11,4,8,10), note='保護者から電話。体調不良のため本日はお休み。')
for state in ['empty', 'partial', 'filled', 'saved']:
    row = NS(child=NS(id=9001,full_name='見本 あおい'), classroom_name='さくら組', alarm_is_active=state!='saved', attendance_state='absent',check_in_at=None,check_out_at=None,has_check_in=False,entry=None,contact_confirmation=contact if state=='saved' else None,verification=True,verification_key='sick_absent',verification_label='病欠',verification_updated_by_name='見本 はなこ',verification_updated_at=datetime(2026,11,4,8,5),alarm_reasons=[] if state=='saved' else ['保護者連絡なし'],history_items=[],contact_history=[contact] if state=='saved' else [])
    body = env.get_template('attendance_checks/_row_card.html').render(row=row,current_user=who,verification_options=[NS(value=v,label=l) for v,l in [('present','出席'),('private_absent','私用休み'),('sick_absent','病欠'),('unknown','不明')]],target_date_value='2026-11-04',selected_layout='cards',selected_filter='all',selected_classroom_id_value='1',return_query='')
    html = env.from_string(shell.replace('{% block content %}{% endblock %}', '<h1 class="text-2xl font-bold mb-2">出欠確認</h1><p class="mb-5 text-sm text-slate-600">対象日：2026-11-04 ／ さくら組（園児1名の詳細を抜粋）</p>' + body)).render()
    script = 'document.querySelector(".check-open").click();'
    if state in ['partial','filled']: script += 'document.querySelector("select[name=status]").value="sick_absent";'
    if state=='filled': script += 'document.querySelector("input[name=note]").value="保護者から電話。体調不良のため本日はお休み。";'
    marks = ['.check-open'] if state=='empty' else ['select[name=method]','select[name=status]','input[name=note]','form[action] button[type=submit]'] if state=='filled' else ['.check-parent','.check-row ul:last-child'] if state=='saved' else []
    save('phone-'+state, html, script, marks)

rows=[]
for day in [26,27,28]:
    rows.append(dict(date=f'2026-10-{day}',weekday={26:'月',27:'火',28:'水'}[day],visual='出席',contact='出席連絡',arrival='08:30',departure='',next_day=False,allowed=True,locked=False,missing=True,unknown=False,future=False,date_mismatch=False,history=[],fee_minutes=None,fee=None,fee_status='未算出',planned='16:30',person='保護者',actual='',snack='なし',revision='sample',bulk_eligible=True,bulk_optional=False,record_id=9001))
monthly = env.get_template('attendance_monthly.html').render(data=dict(rows=rows,can_edit=True,is_admin=True,child_id=9001,child_name='見本 あおい',month='2026-10',return_query='',draft=None),notice='',error='',month='2026-10',classrooms=[NS(id=1,name='さくら組')],classroom_id=1,children=[NS(id=9001,full_name='見本 あおい',classroom_id=1)],child=NS(id=9001,full_name='見本 あおい',classroom_id=1),classroom_names={1:'さくら組'},rows=rows,current_user=who,missing_count=3,unknown_count=0,corrected_count=0,request=NS(state=NS(csrf_token='sample-only')))
save('monthly-list', monthly, marks=['.am-filters','#open-bulk'])
script='document.getElementById("open-bulk").click();'
save('monthly-empty',monthly,script)
filled=script+'document.getElementById("common-departure").value="16:30";document.getElementById("apply-common").click();document.getElementById("bulk-reason").value="職員の記録で実際の降園時刻を確認したため";'
save('monthly-filled',monthly,filled, ['#common-departure','#apply-common','#bulk-reason'])
save('monthly-confirm',monthly,filled+'document.getElementById("review-bulk").click();', ['#bulk-confirmation','#save-bulk'])
save('monthly-error',monthly,script+'document.getElementById("common-departure").value="07:00";document.getElementById("apply-common").click();document.getElementById("bulk-reason").value="職員の記録で確認";document.getElementById("review-bulk").click();', ['#bulk-error'])

authentication = env.get_template('staff_auth/authentication.html').render(user=NS(id=9002,display_name='見本 はなこ',email='hanako@example.invalid',is_active=True),current_user=who,auth_status='configured',form_error='',form_reason='本人からパスワード紛失の申告',credential=NS(login_id='hanako@example.invalid',password_changed_at=datetime(2026,10,1,9)),csrf_token='sample-only')
save('password-admin',authentication,marks=['input[name=reason]','button[type=submit]'])
staff_users = [NS(id=i, display_name=name, email=email+'@example.invalid',
                 calendar_role_label='編集可', can_manage_child_records_effective=False,
                 can_manage_billing_accounts_effective=False, staff_sort_order=order, is_active=True)
               for i,name,email,order in [(9001,'見本 さくら','sakura',10010),
                                          (9002,'見本 はなこ','hanako',100),
                                          (9003,'見本 あおば','aoba',10030)]]
staff_list = env.get_template('staff_auth/users.html').render(
    users=staff_users, current_user=NS(user_id=9999), show_inactive=False,
    credentials_by_user_id={9002:NS(login_id='hanako@example.invalid'),9003:NS(login_id='aoba.sample')},
    credential_status=lambda credential:'configured' if credential else 'not_configured')
save('staff-list',staff_list,marks=['tbody tr:nth-child(2) td:first-child', 'a[href="/staff/users/9002/authentication"]'])
reset = env.get_template('staff_auth/reset_password.html').render(form_error='',csrf_token='sample-only')
save('password-person',reset, marks=['input[name=reset_code]','input[name=password]','input[name=password_confirmation]','button[type=submit]'])
(Path(__file__).parent / 'baseline.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2),encoding='utf-8')
print(f'Rendered 12 synthetic screens in {OUT / "screens"}')
