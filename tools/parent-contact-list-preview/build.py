"""Build a static preview from verified deployment templates; no app/DB imports."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import re
import subprocess

from jinja2 import Environment, FileSystemLoader, select_autoescape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / '.local-dev/truenas-monthly-export-20260927/source'
COMMIT = 'f79846c31e361da6fed3f02f13798c4e4720a534'
FILES = ['templates/base.html', 'templates/daily_contacts/list.html',
         'templates/daily_contacts/detail.html', 'templates/parent_portal/contact_form.html',
         'templates/shared/_pickup_fields.html', 'routers/daily_contacts.py',
         'home_care_details.py', 'pickup_plan_service.py',
         'templates/daily_contacts/_content_table.html', 'static/css/daily-contact-list.css']

hashes = {}
for name in FILES:
    raw = subprocess.check_output(['git', '-C', str(SOURCE), 'show', f'{COMMIT}:{name}'])
    raw = raw.replace(b'\r\n', b'\n')
    assert raw == (SOURCE / name).read_bytes().replace(b'\r\n', b'\n'), name
    hashes[name] = hashlib.sha256(raw).hexdigest()

env = Environment(loader=FileSystemLoader(SOURCE / 'templates'), autoescape=select_autoescape())
env.filters['jst_datetime'] = lambda value, fmt='': str(value)
env.globals['static_asset_url'] = lambda name: '/static/' + name
baseline = env.get_template('daily_contacts/list.html').render(
    request=SimpleNamespace(url=SimpleNamespace(path='/daily-contacts/'), state=SimpleNamespace()),
    current_user=dict(staff_id=1, name='確認用職員', role_label='職員', can_manage_child_records=True),
    target_date_value='2026-09-28', children=[], classrooms=[], entry_by_child_id={}, reply_by_child_id={},
    selected_classroom_id=None, selected_sort='classroom', selected_view='content',
    view_urls={'content':'#','status':'#'}, contact_counts=dict(total=0,submitted=0,missing=0,absent=0),
    sort_options={'classroom': 'クラス・園児順', 'unsubmitted_first': '未提出を先頭',
                  'submitted_first': '提出済みを先頭', 'unsent_first': '園の未送信を先頭'},
)
sidebar = re.search(r'<aside\b.*?</aside>', baseline, re.S).group()
sidebar = re.sub(r'<form\b.*?</form>', '', sidebar, flags=re.S)
sidebar = sidebar.replace('ログイン中', 'モック用の表示')
sidebar = re.sub(r'href="[^"]*"', 'href="#"', sidebar)
page = (HERE / 'page.html').read_text(encoding='utf-8').replace('<!-- DEPLOYED_SIDEBAR -->', sidebar)
page = '\n'.join(line.rstrip() for line in page.splitlines()) + '\n'
(HERE / 'index.html').write_text(page, encoding='utf-8')
(HERE / 'baseline.json').write_text(json.dumps({'commit': COMMIT, 'normalized_sha256': hashes}, indent=2) + '\n', encoding='utf-8')
print(f'Built static contact-list preview; verified {len(FILES)} deployment source files. No database accessed.')
