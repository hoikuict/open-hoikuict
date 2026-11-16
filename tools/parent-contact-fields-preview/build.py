"""Render the recorded deployment with fictional data; never import the app or DB."""
from datetime import date, timedelta
from pathlib import Path
import hashlib
import json
import re
import subprocess
from jinja2 import DictLoader, Environment, select_autoescape
from lxml import html

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / '.local-dev/document-search-rollout-20261108/source'
REV = '4f50cb732a21f4453fcec11f757fae79b1dd6c10'

def source(path):
    return subprocess.check_output(['git', '-C', str(SOURCE), 'show', f'{REV}:{path}']).decode('utf-8')

names = ['parent_portal/contact_form.html', 'parent_portal/_contact_quick_inputs.html',
         'parent_portal/_meal_fields.html', 'parent_portal/_daily_emergency.html',
         'parent_portal/_emergency_editor.html', 'shared/_emergency_order.html',
         'shared/_pickup_fields.html', 'shared/_pickup_script.html']
files = {n: source('templates/' + n) for n in names}
files['base.html'] = '{% block content %}{% endblock %}{% block body_end %}{% endblock %}'
env = Environment(loader=DictLoader(files), autoescape=select_autoescape(default=True))
env.filters['jst_datetime'] = lambda value, fmt: '11/16 07:30'
env.globals['static_asset_url'] = lambda path: path
env.globals['meal_dates'] = lambda day: [('dinner', f'{(day-timedelta(days=1)).month}月{(day-timedelta(days=1)).day}日の夕食'), ('breakfast', f'{day.month}月{day.day}日の朝食')]
contacts = [dict(label='見本保護者の職場', phone='000-0000-0101'), dict(label='見本保護者の電話', phone='000-0000-0102')]
markup = env.get_template(names[0]).render(child=dict(id=1, full_name='見本 ひなた'), form_data={},
    target_date_value='2026-11-16', target_day=date(2026,11,16), pickup_editable=True,
    pickup_values={}, closing_time='19:00', emergency=dict(usual=dict(contacts=contacts),
    answer=None, base_revision=1, day_revision=0), appetites=['旺盛','普通','あまりない','ない'],
    present_temperature_limit=37.5, present_temperature_error='37.5℃以上の場合は、出席として送信できません。入力内容を確認し、欠席する場合は「欠席」を選択してください。',
    temperature_format_error='体温は「36.7」のような数値で入力してください。')
scripts = re.findall(r'<script>(.*?)</script>', markup, re.S)
assert len(scripts) == 3
# Hidden optional fields must not keep the deployment's temperature error active.
scripts[1] = scripts[1].replace("selectedMode() === 'present', true", "selectedMode() === 'present' && !temperatureInput.disabled, true")
doc = html.fromstring(re.sub(r'<script\b[^>]*>.*?</script>', '', markup, flags=re.S))
inventory = [(e.tag, e.get('name'), e.get('type')) for e in doc.xpath('.//input|.//select|.//textarea')]
groups = {'temperature':'temperature', 'sleep':'sleep_notes', 'dinner':'dinner_contents',
    'breakfast':'breakfast_contents', 'stool':'bowel_movement_status', 'mood':'mood',
    'cough':'cough', 'runny_nose':'runny_nose', 'medication':'medication', 'condition':'condition_note'}
for key, field in groups.items():
    element = doc.xpath(f'.//*[@name="{field}"]')[0]
    wrapper = element.getparent()
    if key in ('dinner','breakfast'):
        wrapper = element.xpath('ancestor::section')[-1]
    wrapper.set('data-contact-group', key)
for a in doc.xpath('.//a'):
    a.set('href', '#home')
    a.set('data-home', '')
form = doc.xpath('.//form')[0]
form.set('action', '#')
form.set('novalidate', '')
form.set('id', 'contact-form')
form.attrib.pop('method', None)
button = form.xpath('.//button[@type="submit"]')[0]
button.text = '保存する'
cancel = html.fragment_fromstring('<button type="button" id="cancel-contact" class="rounded border px-4 py-2">今回の入力を取り消す</button>')
button.addnext(cancel)
doc.xpath('.//h1')[0].set('id', 'contact-title')
doc.xpath('.//h1')[0].getparent().xpath('./p')[0].set('id','contact-subtitle')
emergency_heading = doc.xpath('.//*[@data-day-emergency]/h2')[0]
emergency_heading.set('id','emergency-heading')
output = html.tostring(doc, encoding='unicode')
assert all(f'name="{name}"' in output for _, name, _ in inventory if name)
assets = {'FORM':output,
    'BIND':'function bindDeployedInputs(){\n'+'\n'.join(scripts)+'\n'+source('static/js/family-emergency.js')+'\n}',
    'APP':(HERE/'app.js').read_text(encoding='utf-8'),
    'STYLE':(HERE/'mock.css').read_text(encoding='utf-8'),
    'UTILITIES':(ROOT/'tools/family-emergency-preview/utilities.css').read_text(encoding='utf-8')}
shell = (HERE/'shell.html').read_text(encoding='utf-8')
for key,value in assets.items():
    assert shell.count('<!--'+key+'-->') == 1
    shell = shell.replace('<!--'+key+'-->',value)
assert not re.search(r'(?:fetch\(|XMLHttpRequest|WebSocket|(?:src|href)=["\']https?://)', shell)
(HERE/'index.html').write_text(shell,encoding='utf-8',newline='\n')
(HERE/'baseline.json').write_text(json.dumps(dict(mock_revision='r2',source_commit=REV,
    source_basis='2026-11-15 weekly deployment record; no live production access in this task',
    field_inventory=inventory, source_hashes={n:hashlib.sha256(files[n].encode()).hexdigest() for n in names},
    artifact_sha256=hashlib.sha256(shell.encode()).hexdigest()),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'Built {HERE / "index.html"}: {len(inventory)} original inputs retained')
