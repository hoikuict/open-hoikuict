"""Build an isolated monthly-plan mock from the recorded production templates.

No application imports, database reads, model calls, or Drive requests.
"""
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
from jinja2 import DictLoader, Environment, select_autoescape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / '.local-dev/truenas-desktop-20260925/source'
COMMIT = 'c907275b94cabcb613b4cf2a8edf778c05ade8dd'
FILES = ['templates/base.html', 'templates/plan_docs/bunrei/monthly.html',
         'templates/plan_docs/bunrei/_candidate_groups.html',
         'templates/plan_docs/documents/edit.html', 'plan_docs/services/bunrei.py',
         'plan_docs/routers/bunrei.py']


def git(*args):
    return subprocess.check_output(['git', '-C', str(SOURCE), *args])


assert git('rev-parse', 'HEAD').decode().strip() == COMMIT
sources = {}
hashes = {}
for name in FILES:
    raw = (SOURCE / name).read_bytes().replace(b'\r\n', b'\n')
    assert raw == git('show', f'HEAD:{name}').replace(b'\r\n', b'\n'), name
    sources[name] = raw.decode('utf-8')
    hashes[name] = hashlib.sha256(raw).hexdigest()

tree = ast.parse(sources['plan_docs/services/bunrei.py'])
sections = next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.AnnAssign) and node.target.id == 'MONTHLY_SECTION_ITEMS')
css = re.findall(r'<style>(.*?)</style>', sources['templates/base.html'], re.S)[1]
(HERE / 'baseline.css').write_text(css, encoding='utf-8')
env = Environment(loader=DictLoader({
    'base.html': '{% block content %}{% endblock %}',
    **{name.removeprefix('templates/'): text for name, text in sources.items() if name.startswith('templates/') and name != 'templates/base.html'},
}), autoescape=select_autoescape())
groups = [dict(section_key=key, section_title=title, examples=[dict(
    id=f'sample-{i}', source_label='架空の園文例', label=items[0],
    text='これは現行画面の項目と長さを確認する架空の文例です。', masked=False)])
    for i, (key, title, items) in enumerate(sections)]
baseline = env.get_template('plan_docs/bunrei/monthly.html').render(
    total_examples=10, age_options=[f'{n}歳児' for n in range(6)], selected_age_class='3歳児',
    selected_month=10, month_options=[4,5,6,7,8,9,10,11,12,1,2,3], groups=groups,
    user=dict(name='担任（架空）', classroom_refs=['そら組（架空）', 'にじ組（架空）']),
    default_classroom_ref='そら組（架空）')
editor = env.get_template('plan_docs/documents/edit.html').render(
    document=dict(id='preview', title='', nursery_label='見本の園', classroom_label='架空クラス',
                  status_label='下書き', owner_name='', document_type_label='月案',
                  document_type=dict(value='monthly_plan'), schedule=None,
                  sections=[dict(section_key=key, title=title, body='', editor_note='', needs_confirmation=True)
                            for key, title, _ in sections]),
    lock_version=0, confirmation_items_text='')
# Disable submission even if JavaScript fails to load; forms are also denied by CSP.
baseline = re.sub(r'action="[^"]*"', 'action="#"', baseline)
editor = re.sub(r'action="[^"]*"', 'action="#"', editor)
manifest = dict(commit=COMMIT, source=str(SOURCE), sha256=hashes,
                note='2026-09-27 latest completed deployment record; no live production connection')
(HERE / 'baseline.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
section_data = json.dumps([dict(key=key,title=title,items=items) for key,title,items in sections], ensure_ascii=False)
page = (HERE / 'page.html').read_text(encoding='utf-8').replace('<!-- EDITOR -->', editor).replace('/* SECTIONS */', section_data)
(HERE / 'index.html').write_text(page, encoding='utf-8')
(HERE / 'baseline.html').write_text('''<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'">
<title>現行月案画面・架空データ</title><link rel="stylesheet" href="baseline.css"><link rel="stylesheet" href="style.css"></head>
<body><aside class="review-bar">確認用・架空データ <a href="index.html">変更案に戻る</a> <span>現行の入力項目と並び順。業務リンク・保存は無効。</span></aside>
<header class="app-header"><strong>open-hoikuict</strong><span>指導計画 / 現行の月案文例選択</span></header>
<main class="plan-docs-content baseline">''' + baseline + '''</main><script src="baseline.js"></script></body></html>''', encoding='utf-8')
print('Built index.html, baseline.html, baseline.css, baseline.json; verified 6 baseline files.')
