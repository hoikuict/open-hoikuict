"""Build a disconnected prefill proposal from the last verified deployed templates."""
import ast
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace as NS

from jinja2 import DictLoader, Environment, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.local-dev/parent-guardian-rollout-20261101/source'
OUT = ROOT / 'tools/parent-guardian-prefill-preview'


def main():
    manifest = json.loads((ROOT/'.local-dev/parent-guardian-rollout-20261101/bundle/UPDATE.json').read_text())
    paths = ['parent_enrollment.py', 'routers/parent_auth.py', 'templates/parent_auth/enrollment.html']
    for path in paths:
        actual = hashlib.sha256((SOURCE/path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        assert actual == manifest['new_hashes'][path], path
    OUT.mkdir(exist_ok=True)
    tree = ast.parse((SOURCE/'parent_enrollment.py').read_text(encoding='utf-8'))
    constants = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id in ('CHILD_FIELDS', 'GUARDIAN_FIELDS')}
    original = (SOURCE/'templates/parent_auth/enrollment.html').read_text(encoding='utf-8')
    proposal = original.replace(
        '<p>{{ enrollment.child_name }}さんの保護者として利用する、ご本人の情報を入力してください。</p>',
        '<p>{{ enrollment.child_name }}さんの保護者として利用する、ご本人の登録情報を確認してください。</p>')
    proposal = proposal.replace('<fieldset><legend>入力する保護者ご本人</legend>',
        '<p class="prefill-note">園に登録されているご本人の情報を表示しています。内容を確認し、変更がある項目と未入力の必須項目だけ入力してください。</p>'
        '<fieldset><legend>保護者ご本人の登録情報</legend>')
    proposal = proposal.replace('勤務先がない場合は空欄で構いません。',
        '勤務先がない場合は空欄で構いません。登録済みの勤務先情報を削除する場合は、園へお知らせください。')
    env = Environment(loader=DictLoader({'parent_auth/base.html': '{% block content %}{% endblock %}',
        'current.html': original, 'proposal.html': proposal}), autoescape=select_autoescape(['html']))
    env.globals['static_asset_url'] = lambda name: '/static/'+name
    views = {}
    for kind in ('invite', 'add', 'current', 'new'):
        context = dict(request=NS(state=NS(csrf_token='mock-only')), public_application=False,
            guardian_only=kind!='new', enrollment=NS(child_id=None if kind=='new' else 900001, child_name='見本 はる'),
            values={}, form_error='', child_fields=constants['CHILD_FIELDS'], guardian_fields=constants['GUARDIAN_FIELDS'])
        markup = env.get_template('proposal.html' if kind=='invite' else 'current.html').render(**context)
        markup = re.sub(r'<input[^>]*type="hidden"[^>]*>', '', markup)
        markup = re.sub(r'<script\b[^>]*>.*?</script>', '', markup, flags=re.S)
        markup = markup.replace('method="post"', 'method="dialog" novalidate')
        markup = re.sub(r'action="[^"]+"', 'action="#"', markup)
        views[kind] = markup
    sample = {'last_name':'見本','first_name':'はる','last_name_kana':'ミホン','first_name_kana':'ハル',
        'birth_date':'2022-04-05','enrollment_date':'2026-04-01','home_address':'見本市さくら町1-2-3',
        'home_phone':'03-0000-0000','allergy':'見本：卵','medical_notes':'見本：園へ共有済み',
        'g1_last_name':'見本','g1_first_name':'あおい','g1_last_name_kana':'ミホン','g1_first_name_kana':'アオイ',
        'g1_relationship':'母','g1_phone':'090-0000-0000','g1_workplace':'見本事業所',
        'g1_workplace_address':'見本市さくら町4-5-6','g1_workplace_phone':'03-0000-0001'}
    fixture = dict(views=views, child_fields=constants['CHILD_FIELDS'], guardian_fields=constants['GUARDIAN_FIELDS'],
        sample=sample, registered={key:value for key,value in sample.items() if key.startswith('g1_')},
        version='PARENT-GUARDIAN-PREFILL-MOCK-001')
    (OUT/'fixtures.js').write_text('window.ParentGuardianFixture='+json.dumps(fixture,ensure_ascii=False)+';\n',encoding='utf-8')
    base = (SOURCE/'templates/parent_auth/base.html').read_text(encoding='utf-8')
    base = re.sub(r'<script\b[^>]*>.*?</script>', '', base, flags=re.S)
    shell = Environment(loader=DictLoader({'base.html':base, 'shell.html':'{% extends "base.html" %}{% block title %}確認用：登録済み保護者情報の引継ぎ{% endblock %}{% block content %}<div id="mock-view"></div>{% endblock %}'}))
    page = shell.get_template('shell.html').render()
    toolbar = '''<header class="preview-toolbar">
<strong>確認用モック · 登録済み保護者情報の引継ぎ</strong><p>架空データ／提案段階／本番への保存・メール送信なし</p>
<div class="preview-controls"><label>画面の比較<select id="preview-kind">
<option value="invite">修正案：この保護者を招待</option><option value="add">新しい保護者を追加</option>
<option value="current">比較：現在の登録済み保護者の招待</option><option value="new">比較：新入園</option></select></label>
<label>状態<select id="preview-state"><option value="initial">開いた直後</option><option value="empty">登録情報なし・未入力</option>
<option value="partial">一部だけ登録済み</option><option value="filled">本人が修正済み</option>
<option value="error">電話未入力のエラー</option><option value="expired">期限切れ</option></select></label>
<button type="button" class="secondary" id="start-over">入力画面を開き直す</button></div>
<p id="preview-scope" role="status"></p></header>'''
    page = page.replace('<body>', '<body>'+toolbar)
    page = page.replace('</head>', '''<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'">
<link rel="stylesheet" href="preview.css"><script src="fixtures.js"></script><script src="preview.js" defer></script></head>''')
    (OUT/'index.html').write_text(page,encoding='utf-8')
    css = (ROOT/'tools/parent-existing-guardian-preview/preview.css').read_text(encoding='utf-8')
    css += '\n.prefill-note{padding:.9rem 1rem;background:#eef2ff;border-left:4px solid #6366f1;border-radius:.25rem;line-height:1.7}\n'
    (OUT/'preview.css').write_text(css,encoding='utf-8')
    (OUT/'baseline.json').write_text(json.dumps({'app_commit':manifest['commit'],
        'source_copy':str(SOURCE), 'hashes':{path:manifest['new_hashes'][path] for path in paths},
        'basis':'Verified production deployment earlier in this conversation; no new production or business-data access',
        'previous_mock_unchanged':True},indent=2)+'\n',encoding='utf-8')
    print('Built fictional prefill mock; runtime sources and earlier approved mock unchanged.')


if __name__ == '__main__':
    main()
