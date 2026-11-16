"""Common-QR manual fixtures from deployed templates; never access the business DB."""
import hashlib
import json
import runpy
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'.local-dev/manual-qr-20261103/python'))
import qrcode
from qrcode.image.svg import SvgPathFillImage

HERE=Path(__file__).resolve().parent
ctx=runpy.run_path(str(HERE/'build_admission_screens.py'))
env,render,save,BASE,OUT=(ctx[k] for k in ('env','render','save','BASE','OUT'))
base_context=ctx['ctx'];base_context['names'].clear();base_context['files'].clear()
sample_url='https://nursery.example.invalid/parent-portal/register/apply'
(OUT/'assets/qr-sample.svg').write_bytes(qrcode.make(sample_url,image_factory=SvgPathFillImage,border=4).to_string())
account=NS(id=9200,display_name='見本 みどり',contact_email='midori@example.invalid',phone='',home_address='',workplace='',
           family=None,child_links=[],last_login_at=None,email_removed=False)
render('qr-list','parent_accounts/list.html',['a[href="/parent-accounts/registration-qr"]'],
       current_user=NS(is_admin=True,can_manage_child_records=True),accounts=[account],
       pending_registrations=[NS(child_name='見本 ひなた',display_name='見本 みどり',email='midori@example.invalid',
                                 submitted_at=datetime(2026,11,3,10,15),parent_account_id=9200,registration_id=9300)],
       notifications=[],lifecycle_states={9200:NS(code='review',label='確認待ち')},parent_mock_login_available=False)
for accepting,state in [(False,'closed'),(True,'open')]:
    name='qr-settings-'+state
    render(name,'parent_auth/registration_qr.html',
           ['.qr-url','form[method=post] button'] if not accepting else ['button[onclick]','a[download]'],
           accepting=accepting,registration_url=sample_url)
    p=OUT/'screens'/f'{name}.html';html=p.read_text(encoding='utf-8')
    html=html.replace('/parent-accounts/registration-qr.svg','../assets/qr-sample.svg')
    html=html.replace('<section class="qr-poster"','<p class="sample-note">説明用のQRです。実際の申請には、園から配られたQRを使ってください。</p><section class="qr-poster"')
    p.write_text(html,encoding='utf-8')
for state in ['empty','filled','error','stopped']:
    render('qr-apply-'+state,'parent_auth/public_registration.html',
           ['#signup-email','button[type=submit]'] if state=='filled' else (),
           accepting=state!='stopped',email='midori@example.invalid' if state=='filled' else '',
           form_error='受信できるメールアドレスを入力してください' if state=='error' else '')
render('qr-sent','parent_auth/public_registration_sent.html')
for state in ['empty','partial','filled','error']:
    data={} if state=='empty' else {'last_name':'見本','first_name':'ひなた'} if state=='partial' else ctx['values'].copy()
    if state=='error':data['birth_date']=''
    name='qr-form-'+state
    render(name,'parent_auth/enrollment.html',
           ['input[name=last_name]','input[name=g1_last_name]','details','button[type=submit]'] if state=='filled' else (),
           guardian_only=False,public_application=True,prefilled_guardian=False,
           enrollment=NS(child_name='初回申請',child_id=None),values=data,guardian_fields=ctx['guardian_fields'],
           child_fields=ctx['child_fields'],form_error='生年月日を入力してください' if state=='error' else '')
    p=OUT/'screens'/f'{name}.html';p.write_text(p.read_text(encoding='utf-8').replace('<details >','<details open>'),encoding='utf-8')

for state,target in [('new','new'),('existing','9103:1')]:
    html=env.from_string(ctx['review'].replace('新規入園の提出内容','共通QRの提出内容')).render(
        request=base_context['request'],latest_enrollment=ctx['enrollment'],
        registrations=[NS(id=9300,status='pending_review',submitted_at=datetime(2026,11,3,10,15))],
        enrollments={'9300':ctx['enrollment']},public_registrations=['9300'],is_guardian_only_submission=lambda e:False,
        registration_status_labels={'pending_review':'確認待ち'},account=NS(id=9200),
        public_registration_targets=[dict(value='9103:1',label='見本 ひなた（2024-05-20） / 見本 みどり')],
        review_values=dict(registration_id='9300',public_child_target=target),
        enrollment_field_labels={**ctx['child_fields'],**{f'g{i}_{key}':f'保護者{i}・{label}' for i in (1,2) for key,label in ctx['guardian_fields'].items()}})
    name='qr-review-'+state
    save(name,html,marks=['select[name=public_child_target]','textarea[name=reason]','label:has(input[name=enrollment_confirmed])','button[value=approve]'])
    base_context['names'].append(name)
base_context['files'].update(['templates/parent_auth/admin.html','templates/parent_auth/base.html','templates/settings/_back.html',
                             'parent_public_registration.py','parent_enrollment.py','parent_auth.py','routers/parent_auth.py'])
(HERE/'qr-baseline.json').write_text(json.dumps(dict(source_commit='285b67e7c0bec04afb40ac526626781182280779',
    synthetic_data_only=True,business_records_written=0,qr_contains_reserved_invalid_domain=True,
    screens=base_context['names'],source_files={p:hashlib.sha256((BASE/p).read_bytes()).hexdigest() for p in sorted(base_context['files'])}),ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'qr_screens':base_context['names']}))
