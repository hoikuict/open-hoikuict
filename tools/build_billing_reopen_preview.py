"""Render a disconnected proposal from the verified deployed billing templates."""
import ast
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace as NS

from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPO = ROOT / '.local-dev/backup-v2-rollout-20261101/source'
SOURCE = ROOT / '.local-dev/billing-reopen-20261101/approved-baseline'
OUT = ROOT / 'tools/billing-reopen-preview'
OUT.mkdir(exist_ok=True)
verification = json.loads((ROOT / '.local-dev/billing-reopen-20261101/source-verification.json').read_text())
paths = ['templates/billing/index.html', 'templates/billing/child_charges.html', 'templates/billing/child_charge_input.html']
for path in paths + ['routers/billing.py']:
    # Keep the agreed mock reproducible after the implementation checkout changes.
    original = subprocess.check_output(['git', 'show', verification['commit'] + ':' + path], cwd=SOURCE_REPO)
    normalized = original.replace(b'\r\n', b'\n')
    original = next(data for data in (original, normalized, normalized.replace(b'\n', b'\r\n'))
                    if hashlib.sha256(data).hexdigest() == verification['files'][path])
    assert hashlib.sha256(original).hexdigest() == verification['files'][path]
    destination = SOURCE / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(original)
for path in paths:
    assert hashlib.sha256((SOURCE / path).read_bytes()).hexdigest() == verification['files'][path]
tree = ast.parse((SOURCE / 'routers/billing.py').read_text(encoding='utf-8'))
node = next(n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
            and n.targets[0].id == 'TABLE_CHARGE_COLUMNS')
columns = [{ast.literal_eval(k): ast.literal_eval(v) for k, v in zip(d.keys, d.values)
            if isinstance(v, ast.Constant)} for d in node.value.elts]
groups = [dict(key=key, label=label, columns=[c for c in columns if c['category'] == key])
          for key, label in [('monthly', '毎月請求'), ('temporary', '単発請求'), ('adjustment', '調整')]]
env = Environment(loader=DictLoader({'base.html': '{% block content %}{% endblock %}',
                  **{Path(p).name: (SOURCE / p).read_text(encoding='utf-8') for p in paths}}),
                  autoescape=select_autoescape(['html']), undefined=StrictUndefined)
user = NS(is_admin=True, can_edit=True)
cycle = NS(id=9001, year_month='2026-10', withdrawal_date='2026-11-27', status=NS(value='exported'))
child = NS(id=9001, family_id=9001, full_name='見本 はる')
profile = NS(payment_method=NS(name='direct_debit'), direct_debit_status=NS(value='active'),
             customer_number='00100000000000009001', bank_code='0001', bank_name_kana='MIHON',
             branch_code='001', branch_name_kana='MIHON', account_type='1', account_number='1234567',
             account_holder_kana='MIHON HARU', new_code='1', mandate_received_on='', note='架空データ')
claim = NS(total_amount=300, status=NS(value='exported'))
line = NS(description='写真代', source_type=NS(value='manual'), source_date='2026-10-15',
          amount=300, quantity=1, unit_label='回')
line_rows = [dict(child=child, line=line, claim=claim, claim_status_label='出力済み')]
base = dict(current_user=user, can_manage_billing_accounts=True, message='', error='', return_month='',
            cycle=cycle, child=child, profile=profile, claim=claim, cycle_status_label='出力済み',
            claim_status_label='出力済み', line_rows=line_rows,
            profile_summary=dict(payment_method='口座振替', direct_debit_status='利用中', is_registered=True),
            charge_columns=columns, charge_column_groups=groups,
            table_rows=[dict(child=child, profile=profile, profile_status_label='利用中', claim=claim,
                            amounts={c['code']: 300 if c['code']=='temp_photo' else 0 for c in columns},
                            locked_codes=[], row_total=300)])
cycles = []
for month in range(11, 4, -1):
    selected = month == 10
    c = cycle if selected else NS(id=9000+month, year_month=f'2026-{month:02}',
          withdrawal_date=f'2026-{month+1:02}-27', status=NS(value='confirmed'))
    cycles.append(dict(cycle=c, status_label='出力済み' if selected else '確定済み',
                       claim_count=1 if selected else 0, total_amount=300 if selected else 0))
exports = [dict(export=NS(id=n, status=NS(value=status), total_count=1, total_amount=300,
                         content_hash='sample0000000000'), status_label=label)
           for n, status, label in [(2, 'created', '作成済み'), (1, 'superseded', '差し替え済み')]]
views = {'index': env.get_template('index.html').render(**base, cycle_rows=cycles, export_rows=exports,
            setting=NS(collector_code='1234567890', file_encoding='cp932', line_separator='CRLF', collector_account_type='1'))}
for editable in (False, True):
    for name, template in [('table', 'child_charges.html'), ('detail', 'child_charge_input.html')]:
        views[f'{name}-{int(editable)}'] = env.get_template(template).render(**base, editable=editable)
for key, html in views.items():
    # Preserve original actions as labels for the local simulator, never as request targets.
    html = re.sub(r'action="([^"]+)"', r'data-action="\1" action="#"', html)
    html = re.sub(r'onsubmit="[^"]*"', '', html)
    html = html.replace('method="post"', 'method="dialog" novalidate')
    html = re.sub(r'href="([^"]+)"', r'data-href="\1" href="#"', html)
    views[key] = html
(OUT / 'views.js').write_text('window.BILLING_PREVIEW = ' + json.dumps(dict(views=views, columns=columns), ensure_ascii=False) + ';', encoding='utf-8')
shutil.copyfile(ROOT / 'tools/staff-auth-print-preview/tailwind.js', OUT / 'tailwind.js')
(OUT / 'baseline.json').write_text(json.dumps(dict(commit=verification['commit'],
        template_hashes={p: verification['files'][p] for p in paths}, all_charge_columns=[c['label'] for c in columns]), indent=2, ensure_ascii=False), encoding='utf-8')
print('Built 5 disconnected views; all 6 charge columns and 12 account fields preserved.')
