"""Add fictional new-admission examples from the saved deployed templates."""
import ast
import hashlib
import json
import runpy
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace as NS

HERE = Path(__file__).resolve().parent
ctx = runpy.run_path(str(HERE / 'build_registration_screens.py'))
env, render, save = (ctx[k] for k in ('env', 'render', 'save'))
BASE, OUT = ctx['BASE'], ctx['OUT']
ctx['names'].clear()
ctx['files'].clear()
classroom = NS(id=9001, name='さくら組')
family = NS(id=9100, identity_label='見本家 / みどり', selection_label='見本家 / 見本 みどり', children=[])
older = NS(id=9101, full_name='見本 はる', family=family, family_id=9100, birth_date=date(2017,5,10),
           enrollment_date=date(2020,4,1), status=NS(label='退園'), classroom=None)
current = NS(id=9102, full_name='見本 あおい', family=family, family_id=9100, birth_date=date(2022,4,15),
             enrollment_date=date(2025,4,1), status=NS(label='在園'), classroom=classroom)
family.children = [older, current]
family_data = {**ctx['family_data'], 'g1_parent_account_id':'9200'}
child_data = {**ctx['child_data'], 'first_name':'ひなた','first_name_kana':'ヒナタ',
              'birth_date':'2024-05-20', 'enrollment_date':'2027-04-01'}
base = dict(child=None,all_children=[older,current],classrooms=[classroom],families=[family],
            action_url='#',submit_label='登録する',page_title='園児を追加',
            sibling_relationships=[],current_user=NS(can_edit=True,can_manage_child_records=True),
            relationship_options=['母','父','祖母','祖父','その他'])
render('admission-sibling-select','children/form.html',['#sibling_id','form[method=get] button'],
       **base, selected_family_value='new',family_form_data={},form_data={},form_error='',
       older_sibling_id=None,inherit_from=None,show_family_selection=True,siblings=[],family_context_child=None)
# Show a selected former pupil. This selection is fixture data, not a business request.
p=OUT/'screens/admission-sibling-select.html'
p.write_text(p.read_text(encoding='utf-8').replace('<option value="9101">','<option value="9101" selected>'),encoding='utf-8')
for state in ['empty','partial','filled','error']:
    data = dict(status='enrolled',sex='not_set')
    if state=='partial': data.update(last_name='見本',first_name='ひなた')
    if state in ['filled','error']: data=child_data.copy()
    if state=='error': data['birth_date']=''
    render('admission-sibling-'+state,'children/form.html',
           ['#first_name','#enrollment_date','input[name=home_address]','form[method=post] button[type=submit]'] if state=='filled' else (),
           **base,selected_family_value='9100',family_form_data=family_data,form_data=data,
           form_error='生年月日と入園日は必須です。' if state=='error' else '',
           older_sibling_id=9101,inherit_from=None if state=='error' else older,
           show_family_selection=state=='error',siblings=[] if state=='error' else [older,current],
           family_context_child=None if state=='error' else older)

new_child = NS(id=9103,full_name='見本 ひなた',family_id=9100,classroom=classroom)
family.children.append(new_child)
env.globals['parent_enrollment_enabled']=lambda:True
render('admission-access','parent_accounts/form.html',['label:has(input[name=child_ids][value="9103"])','button[type=submit]'],
       account=NS(id=9200,display_name='見本 みどり',contact_email='midori@example.invalid',
                  registration_verification_name='ミホン ミドリ',registration_verification_name_type='kana',
                  phone='000-0000-0000',home_address=family_data['home_address']),
       submit_label='更新する',action_url='#',guardian_choices=[dict(value='9100:1',label='見本家 / 見本 みどり',family_id=9100,fields={})],
       selected_guardian_link='9100:1',selected_family_id=9100,selected_child_ids=[9102,9103],
       families=[family],children=[older,current,new_child],current_user=NS(is_admin=True),lifecycle=NS(label='利用中'))

render('admission-new-entry','parent_auth/enrollment_select.html',['a[href*="mode=new"]'],children=[],child=None,profiles=[])
render('admission-new-invite','parent_auth/enrollment_invite.html',['input[name=child_name]','input[name=email]','form[method=post] button'],
       child_id=None,child_name='見本 ひなた',guardian_order=None,mode='new',email='midori@example.invalid',form_error='')
module=ast.parse((BASE/'parent_enrollment.py').read_text(encoding='utf-8'))
child_fields=next(ast.literal_eval(n.value) for n in module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CHILD_FIELDS' for t in n.targets))
guardian_fields=ctx['guardian_fields']
values={key:str(child_data.get(key, family_data.get(key,''))) for key in child_fields}
values.update({f'g1_{key}':family_data.get(f'g1_{key}','') for key in guardian_fields})
values.update({f'g2_{key}':'' for key in guardian_fields})
values.update(g2_last_name='見本',g2_first_name='そら',g2_last_name_kana='ミホン',g2_first_name_kana='ソラ',g2_relationship='父',g2_phone='000-0000-0001')
for state in ['empty','partial','filled','error']:
    data={} if state=='empty' else {'last_name':'見本','first_name':'ひなた'} if state=='partial' else values.copy()
    if state=='error': data['birth_date']=''
    name='admission-new-form-'+state
    render(name,'parent_auth/enrollment.html',
           ['input[name=last_name]','input[name=g1_last_name]','details','button[type=submit]'] if state=='filled' else (),
           guardian_only=False,public_application=False,prefilled_guardian=False,
           enrollment=NS(child_name='見本 ひなた',child_id=None),values=data,guardian_fields=guardian_fields,
           child_fields=child_fields,form_error='生年月日を入力してください' if state=='error' else '')
    # Expand the optional section for all samples, preserving all 28 actual fields.
    p=OUT/'screens'/f'{name}.html'
    p.write_text(p.read_text(encoding='utf-8').replace('<details >','<details open>'),encoding='utf-8')

admin=(BASE/'templates/parent_auth/admin.html').read_text(encoding='utf-8')
start=admin.rfind('  <section',0,admin.index('登録申請の履歴'))
end=admin.index('  </section>',admin.index('登録申請の履歴'))+len('  </section>')
review=ctx['shell'].replace('{% block content %}{% endblock %}',
    '<h1 class="text-2xl font-bold mb-2">見本 みどりさんの認証管理</h1><p class="sample-note">新規入園の提出内容と確認・承認欄を抜粋した画面見本です。</p>'+admin[start:end])
enrollment=NS(child_name='見本 ひなた',child_id=None,submitted_data=values,applied_at=None,source_snapshot=None)
html=env.from_string(review).render(request=ctx['request'],latest_enrollment=enrollment,
    registrations=[NS(id=9300,status='pending_review',submitted_at=datetime(2026,11,3,10,15))],
    enrollments={'9300':enrollment},public_registrations=[],is_guardian_only_submission=lambda e:False,
    registration_status_labels={'pending_review':'確認待ち'},review_values={},account=NS(id=9200),
    enrollment_field_labels={**child_fields,**{f'g{i}_{key}':f'保護者{i}・{label}' for i in (1,2) for key,label in guardian_fields.items()}})
save('admission-new-review',html,marks=['textarea[name=reason]','label:has(input[name=enrollment_confirmed])','button[value=approve]'])
ctx['names'].append('admission-new-review');ctx['files'].add('templates/parent_auth/admin.html')
ctx['files'].update(['routers/children.py','parent_enrollment.py','templates/children/_profile_inputs.html','templates/parent_auth/base.html'])
(HERE/'admission-baseline.json').write_text(json.dumps(dict(source_commit='285b67e7c0bec04afb40ac526626781182280779',
    synthetic_data_only=True,business_records_written=0,screens=ctx['names'],
    source_files={p:hashlib.sha256((BASE/p).read_bytes()).hexdigest() for p in sorted(ctx['files'])}),ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'admission_screens':ctx['names']}))
