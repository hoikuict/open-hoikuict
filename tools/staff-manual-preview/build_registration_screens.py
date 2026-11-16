"""Synthetic registration screenshots from the deployed templates; no app/DB imports."""
import ast
import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from jinja2 import Environment, ChoiceLoader, DictLoader, FileSystemLoader

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / '.local-dev/backup-v2-rollout-20261101/source'
OUT = HERE / 'dist'
# Reuse only the shell and save function, without executing the other fixture builds.
tree = ast.parse((HERE / 'build_screens.py').read_text(encoding='utf-8'))
scope = dict(OUT=OUT, re=re, json=json)
for node in tree.body:
    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'shell' for t in node.targets):
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<shell>', 'exec'), scope)
    if isinstance(node, ast.FunctionDef) and node.name == 'save':
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<save>', 'exec'), scope)
shell, save = scope['shell'], scope['save']
parent_base = (BASE / 'templates/parent_auth/base.html').read_text(encoding='utf-8')
extra = re.search(r'<style>(.*?)</style>', shell, re.S).group(1)
# Keep the parent's actual layout; add only the sample banner, annotations, and no-send guard.
extra = extra[extra.index('.sample-head'):]
guard = re.search(r'<script>document.addEventListener.*?</script>', shell, re.S).group(0)
csp = re.search(r'<meta http-equiv="Content-Security-Policy"[^>]+>', shell).group(0)
parent_base = parent_base.replace('</head>', '<style>'+extra+'</style>'+csp+guard+'</head>')
parent_base = parent_base.replace('<body>', '<body><div class="sample-head"><strong>オープン保育ICT</strong><span>説明用・すべて架空の情報</span></div>')
env = Environment(loader=ChoiceLoader([DictLoader({'base.html':shell, 'parent_auth/base.html':parent_base}), FileSystemLoader(BASE/'templates')]), autoescape=True)
env.filters['jst_datetime'] = lambda d, fmt='%Y-%m-%d %H:%M': d.strftime(fmt)
env.globals['static_asset_url'] = lambda s: '../assets/'+Path(s).name
(OUT/'assets/parent-guardian-registration.js').write_bytes((BASE/'static/js/parent-guardian-registration.js').read_bytes())
request = NS(state=NS(csrf_token='synthetic-only'))
user = NS(id=9002, display_name='見本 はなこ', email='hanako@example.invalid', is_active=True)
classroom = NS(id=9001, name='さくら組')
files = set()
names = []
def render(name, template, marks=(), **context):
    files.add('templates/'+template)
    save(name, env.get_template(template).render(request=request, **context), marks=marks)
    names.append(name)

for state in ['empty','partial','filled','error']:
    data = dict(display_name='',email='',staff_role='can_edit',staff_sort_order=100,is_active=True)
    if state != 'empty': data['display_name']='見本 はなこ'
    if state in ['filled','error']: data['email']='hanako@example.invalid'
    render('staff-new-'+state,'staff_auth/user_form.html',
           ['input[name=display_name]','select[name=staff_role]','button[type=submit]'] if state=='filled' else (),
           submit_label='職員を追加',action_url='#',is_new=True,form_data=data,
           form_error='このメールアドレスはすでに登録されています。' if state=='error' else '',
           staff_role_options=[('admin','管理者'),('can_edit','編集可'),('view_only','閲覧のみ')])
render('staff-class','staff_auth/classroom_assignments.html',['select[name=classroom_id]','input[name=starts_on]','button[type=submit]'],
       user=user,classrooms=[classroom],form_error='',form_data=dict(classroom_id=9001,assignment_role='primary',starts_on='2026-11-03',ends_on='',display_order=100,is_primary=True),
       assignment_role_options=[('primary','主担当'),('support','補助'),('temporary','臨時')],assignment_rows=[],today=date(2026,11,3))
render('staff-code','staff_auth/authentication.html',['input[name=login_id]','input[name=reason]','button[type=submit]'],
       user=user,auth_status='not_configured',form_login_id=user.email,form_reason='新規採用職員の初期設定',credential=None,form_error='',csrf_token='synthetic-only')
render('staff-activate','staff_auth/activate.html',['input[name=activation_code]','button[type=submit]'],form_error='',csrf_token='synthetic-only')
render('staff-password','staff_auth/activate_confirm.html',['input[name=login_id]','input[name=password]','button[type=submit]'],
       target_name=user.display_name,login_id=user.email,activation_code='',csrf_token='synthetic-only',form_error='')

child_data = dict(last_name='見本',first_name='あおい',last_name_kana='ミホン',first_name_kana='アオイ',birth_date='2022-04-15',enrollment_date='2026-11-03',withdrawal_date='',status='enrolled',sex='not_set',classroom_id='9001',allergy='',medical_notes='',registration_verification_name='',registration_verification_name_type='')
family_data = dict(family_name='見本家',home_address='架空市 見本町 1-2-3',home_phone='',g1_last_name='見本',g1_first_name='みどり',g1_last_name_kana='ミホン',g1_first_name_kana='ミドリ',g1_relationship='母',g1_email='midori@example.invalid',g1_phone='000-0000-0000',g1_workplace='',g1_workplace_address='',g1_workplace_phone='')
for state in ['empty','partial','filled']:
    data = child_data if state=='filled' else dict(status='enrolled',sex='not_set',last_name='見本' if state=='partial' else '')
    render('child-new-'+state,'children/form.html',['#family_selection','#last_name','#classroom_id','form[method=post] button[type=submit]'] if state=='filled' else (),
           child=None,all_children=[],classrooms=[classroom],families=[],selected_family_value='new',family_form_data=family_data if state=='filled' else {},form_data=data,
           action_url='#',submit_label='登録する',page_title='園児を追加',form_error='',older_sibling_id=None,inherit_from=None,show_family_selection=True,
           sibling_relationships=[],siblings=[],family_context_child=None,current_user=NS(can_edit=True,can_manage_child_records=True),relationship_options=['母','父','祖母','祖父','その他'])

child = NS(id=9001,full_name='見本 あおい',birth_date='2022-04-15',classroom=classroom)
render('parent-select','parent_auth/enrollment_select.html',['select[name=child_id]','a[href*="guardian_order=1"]'],
       children=[child],child=child,profiles=[NS(last_name='見本',first_name='みどり',relationship='母',parent_account_id=None,order=1)])
render('parent-invite','parent_auth/enrollment_invite.html',['input[name=child_name]','input[name=email]','form[method=post] button'],
       child_id=9001,child_name=child.full_name,guardian_order=1,mode='existing',email='midori@example.invalid',form_error='')
module = ast.parse((BASE/'parent_enrollment.py').read_text(encoding='utf-8'))
guardian_fields = next(ast.literal_eval(n.value) for n in module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='GUARDIAN_FIELDS' for t in n.targets))
values = {'g1_'+key:family_data.get('g1_'+key,'') for key in guardian_fields}
for state in ['empty','partial','filled']:
    render('parent-form-'+state,'parent_auth/enrollment.html',['input[name=g1_last_name]','input[name=g1_phone]','button[type=submit]'] if state=='filled' else (),
           guardian_only=True,public_application=False,prefilled_guardian=state=='filled',enrollment=NS(child_name=child.full_name,child_id=9001),
           values=values if state=='filled' else ({'g1_last_name':'見本'} if state=='partial' else {}),guardian_fields=guardian_fields,child_fields={},form_error='')
# The unchanged registration-review section is excerpted so its full approval form is readable.
admin = (BASE/'templates/parent_auth/admin.html').read_text(encoding='utf-8')
start = admin.rfind('  <section',0,admin.index('登録申請の履歴'))
end = admin.index('  </section>',admin.index('登録申請の履歴'))+len('  </section>')
review = shell.replace('{% block content %}{% endblock %}','<h1 class="text-2xl font-bold mb-2">見本 みどりさんの認証管理</h1><p class="sample-note">登録申請の確認・承認欄を抜粋した画面見本です。</p>'+admin[start:end])
enrollment=NS(child_name=child.full_name,child_id=9001,submitted_data=values,applied_at=None)
html = env.from_string(review).render(request=request,latest_enrollment=enrollment,registrations=[NS(id=9001,status='pending_review',submitted_at=datetime(2026,11,3,10,15))],
    enrollments={'9001':enrollment},public_registrations=[],is_guardian_only_submission=lambda e:True,registration_status_labels={'pending_review':'確認待ち'},
    guardian_enrollment_field_labels={'g1_'+key:'保護者・'+label for key,label in guardian_fields.items()},review_values={},account=NS(id=9001))
save('parent-review',html,marks=['textarea[name=reason]','input[name=enrollment_confirmed]','button[value=approve]'])
names.append('parent-review'); files.add('templates/parent_auth/admin.html')
render('parent-password','parent_auth/complete.html',['input[name=password]','input[name=password_confirmation]','button[type=submit]'],form_error='')
files.update(['templates/parent_auth/base.html','templates/parent_auth/fragment_exchange.html','templates/children/_profile_inputs.html','templates/children/_photo_preview_script.html','parent_enrollment.py','static/js/parent-guardian-registration.js'])
report=dict(synthetic_data_only=True,business_records_written=0,source_commit='285b67e7c0bec04afb40ac526626781182280779',screens=names,
            source_files={p:hashlib.sha256((BASE/p).read_bytes()).hexdigest() for p in sorted(files)},review_section_excerpt=True)
(HERE/'registration-baseline.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(rendered=len(names),screens=names)))
