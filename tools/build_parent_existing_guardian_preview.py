"""Disconnected proposal based on the verified live parent registration templates."""
import ast
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace as NS

from jinja2 import DictLoader, Environment, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tools/parent-existing-guardian-preview'
SOURCE = ROOT / '.local-dev/staff-handout-rollout-20261101/source'


def main():
    baseline = json.loads((OUT/'baseline.json').read_text())
    for path, digest in baseline['hashes'].items():
        assert hashlib.sha256((SOURCE/path).read_bytes()).hexdigest() == digest, path
    tree = ast.parse((SOURCE/'parent_enrollment.py').read_text(encoding='utf-8'))
    constants = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id in ('CHILD_FIELDS', 'GUARDIAN_FIELDS')}
    original = (SOURCE/'templates/parent_auth/enrollment.html').read_text(encoding='utf-8')
    proposal = original
    heading = "{{ '保護者アカウントの初回情報入力' if public_application else '入園時の初回情報入力' }}"
    proposal = proposal.replace(heading, '保護者アカウントの登録')
    start = proposal.index('{% if public_application %}<p>')
    end = proposal.index('{% if form_error %}', start)
    proposal = proposal[:start] + '''<p>{{ enrollment.child_name }}さんの保護者として利用する、ご本人の情報を入力してください。</p>
<div class="target-summary"><span class="muted">対象のお子さま</span><strong>{{ enrollment.child_name }} さん</strong><p>お子さまは園の台帳に登録されています。再入力は必要ありません。</p></div>
<p class="muted">メールアドレスは招待先をそのまま使用します。園が内容を確認して承認すると、パスワード設定の案内メールが届きます。入力画面の有効時間は2時間です。</p>
<p class="muted">園児情報・ご自宅の連絡先に変更がある場合は、園へお知らせください。</p>
''' + proposal[end:]
    start = proposal.index('  <fieldset><legend>お子さま</legend>')
    end = proposal.index('  <fieldset><legend>入力する保護者ご本人</legend>', start)
    proposal = proposal[:start] + proposal[end:]
    start = proposal.index('  <fieldset><legend>健康面で伝えたいこと')
    end = proposal.index('  <button type="submit">', start)
    proposal = proposal[:start] + proposal[end:]
    env = Environment(loader=DictLoader({'parent_auth/base.html': '{% block content %}{% endblock %}',
                       'current.html': original, 'proposal.html': proposal}), autoescape=select_autoescape(['html']))
    views = {}
    for kind in ('add', 'invite', 'current', 'new'):
        context = dict(request=NS(state=NS(csrf_token='mock-only')), public_application=False,
                       enrollment=NS(child_id=None if kind == 'new' else 900001, child_name='見本 はる'),
                       values={}, form_error='', child_fields=constants['CHILD_FIELDS'], guardian_fields=constants['GUARDIAN_FIELDS'])
        markup = env.get_template('proposal.html' if kind in ('add', 'invite') else 'current.html').render(**context)
        markup = re.sub(r'<input[^>]*type="hidden"[^>]*>', '', markup)
        markup = markup.replace('method="post"', 'method="dialog" novalidate')
        markup = re.sub(r'action="[^"]+"', 'action="#"', markup)
        views[kind] = markup
    fixture = dict(views=views, child_fields=constants['CHILD_FIELDS'], guardian_fields=constants['GUARDIAN_FIELDS'],
                   sample={'last_name':'見本','first_name':'はる','last_name_kana':'ミホン','first_name_kana':'ハル',
                           'birth_date':'2022-04-05','enrollment_date':'2026-04-01','home_address':'見本市さくら町1-2-3',
                           'home_phone':'03-0000-0000','allergy':'見本：卵','medical_notes':'見本：園へ共有済み',
                           'g1_last_name':'見本','g1_first_name':'あおい','g1_last_name_kana':'ミホン','g1_first_name_kana':'アオイ',
                           'g1_relationship':'母','g1_phone':'090-0000-0000','g1_workplace':'見本事業所',
                           'g1_workplace_address':'見本市さくら町4-5-6','g1_workplace_phone':'03-0000-0001'},
                   version='PARENT-EXISTING-GUARDIAN-MOCK-001')
    (OUT/'fixtures.js').write_text('window.ParentGuardianFixture='+json.dumps(fixture, ensure_ascii=False)+';\n', encoding='utf-8')
    base = (SOURCE/'templates/parent_auth/base.html').read_text(encoding='utf-8')
    base = re.sub(r'<script\b[^>]*>.*?</script>', '', base, flags=re.S)
    shell = Environment(loader=DictLoader({'base.html':base, 'shell.html':'{% extends "base.html" %}{% block title %}確認用：在園児の保護者登録{% endblock %}{% block content %}<div id="mock-view"></div>{% endblock %}'}))
    page = shell.get_template('shell.html').render()
    toolbar = '''<header class="preview-toolbar">
<strong>確認用モック · 在園児の保護者登録</strong><p>架空データのみ／実装前の提案／保存・メール送信は行いません</p>
<div class="preview-controls"><label>画面の比較<select id="preview-kind">
<option value="add">修正案：新しい保護者を追加</option><option value="invite">修正案：登録済みの保護者を招待</option>
<option value="current">比較：現在の在園児向け画面</option><option value="new">比較：新入園向け画面</option></select></label>
<label>入力状態<select id="preview-state"><option value="empty">未入力</option><option value="filled">入力済み</option>
<option value="partial">一部入力</option><option value="error">入力エラー</option><option value="expired">期限切れ</option></select></label>
<button type="button" class="secondary" id="start-over">入力画面へ戻す</button></div>
<p id="preview-scope" role="status"></p></header>'''
    page = page.replace('<body>', '<body>'+toolbar)
    page = page.replace('</head>', '''<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'">
<link rel="stylesheet" href="preview.css"><script src="fixtures.js"></script><script src="preview.js" defer></script></head>''')
    (OUT/'index.html').write_text(page, encoding='utf-8')
    print('Built disconnected parent registration mock from verified live source.')


if __name__ == '__main__':
    main()
