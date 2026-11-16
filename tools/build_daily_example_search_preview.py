"""Render an offline mock from the deployed daily form, using synthetic data only."""
from hashlib import sha256
import json
from pathlib import Path
import re
from types import SimpleNamespace

from jinja2 import DictLoader, Environment, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / '.local-dev/attendance-production-20261004'
OUT = ROOT / 'tools/daily-example-search-preview'
FORM = 'templates/plan_docs/daily_plans/form.html'
EXPECTED = '6f9fa3417859598b9f4d4062c91ca73f34a3f0092618232d264522c5415712ae'


def main():
    source = (BASELINE / FORM).read_text(encoding='utf-8')
    if sha256(source.encode()).hexdigest() != EXPECTED:
        raise RuntimeError('The baseline form changed; review it before regenerating')
    base = (BASELINE / 'templates/base.html').read_text(encoding='utf-8')
    plan_css = re.search(r'<style>\s*(\.plan-docs-content\s*\{.*?)</style>', base, re.S).group(1)
    start = source.index('    {% if examples %}')
    end = source.index('\n  </section>', start)
    source = source[:start] + '''
    <div class="candidate-list-heading"><strong id="result-count">主な活動</strong><span>年齢・月</span><span>詳細</span></div>
    <div id="activity-list" class="activity-list"></div>
    <p id="no-examples" class="field-note" hidden>条件に合う日案例がありません。下の表へ手入力して作成できます。</p>
    <div id="corpus-error" class="notice" hidden><strong>文例DBを読み込めません</strong><span>接続エラーの表示例です。下の表から手入力できます。</span></div>
    <p class="field-note preview-source">架空の日案例を使用しています。</p>
''' + source[end:]
    source = source.replace('{% block content %}', '''{% block content %}
  <section class="mock-controls" aria-label="モックの確認操作">
    <div><strong>検索条件の確認用モック</strong><p>架空データのみ。本番への接続・保存はありません。年齢・月の「すべて」を試せます。</p></div>
    <div class="mock-control-fields">
      <label>検索のケース<select id="mock-search-case"><option value="both">年齢・月を指定</option><option value="age">年齢だけ指定</option><option value="month">月だけ指定</option><option value="none">両方とも指定しない</option><option value="custom" hidden>任意の条件</option></select></label>
      <label>下書きの状態<select id="mock-state"><option value="empty">未入力</option><option value="partial">一部入力</option><option value="filled">入力済み</option><option value="error">入力エラー</option></select></label>
      <label>候補の状態<select id="mock-results"><option value="normal">候補あり</option><option value="none">候補なし</option><option value="error">読み込みエラー</option></select></label>
      <button type="button" id="reset-mock" class="button button--ghost">最初の状態に戻す</button>
    </div>
  </section>
  <div id="mock-status" role="status" hidden></div>
  <section id="mock-validation" class="notice" role="alert" hidden><strong>入力を確認してください</strong><span id="validation-message"></span></section>
''', 1)
    # The mock cannot navigate or submit to the production routes.
    source = source.replace('href="/static/css/daily-example-list.css"', 'href="daily-example-list.css"')
    source = source.replace('<select name="month">', '<select name="month">\n            <option value="">すべて</option>', 1)
    source = source.replace('    <form method="get" action="/plans/daily-plans/new"',
                            '    <p class="field-note search-guidance">年齢・月は、それぞれ「すべて」で絞り込みを外せます。</p>\n    <form method="get" action="/plans/daily-plans/new"', 1)
    source = source.replace('action="/plans/daily-plans/new"', 'action="#" id="example-search"')
    source = source.replace('method="post" action="/plans/daily-plans"', 'method="get" action="#"')
    source = source.replace('href="/plans/"', 'href="#" id="mock-back"')
    source = source.replace('<form class="form-layout"', '<form novalidate class="form-layout"', 1)
    source = source.replace('過去の日案例を探し、', '主な活動の一覧から詳細を開いて確認し、')
    source = source.replace('候補DBは読み取り専用です。選択した内容は独立した下書きになるため、その後は自由に書き換えられます。',
                            '主な活動を選ぶと詳細が開きます。内容を確認し、必要な候補を下書きへコピーできます。')
    source = source.replace('  </script>\n{% endblock %}', '  </script>\n  <script src="preview.js"></script>\n{% endblock %}')
    shell = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'">
<title>日案例の検索条件｜確認用モック</title><style>''' + plan_css + '''</style><link rel="stylesheet" href="preview.css"></head>
<body><div class="app-shell"><aside class="mock-sidebar"><div class="brand">open-hoikuict<small>STAFF CONSOLE</small></div>
<div class="staff-card">確認用の職員<small>編集可・架空の職員</small></div><div class="sidebar-links"><span>日々の業務</span><p>園児一覧</p><p>家族・兄弟姉妹の管理</p><p>児童票作成状況</p><p class="active">指導計画</p><p>健康管理</p><p>出欠一覧</p><span>連絡と記録</span><p>日次連絡</p><p>連絡タイムライン</p><p>設定</p></div></aside>
<main class="plan-docs-content">{% block content %}{% endblock %}</main></div></body></html>'''
    env = Environment(loader=DictLoader({'base.html':shell,'form.html':source}),autoescape=select_autoescape(['html']))
    user = SimpleNamespace(name='確認用の職員',can_edit=True,classroom_refs=('ことり組（架空）','こりす組（架空）'))
    values = {'target_date':'2026-10-11','classroom_ref':'ことり組（架空）','age_class':'0歳児','owner_name':user.name,
              'timeline_rows':[{'row_key':'preview_1','time_label':'','activity_name':'','child_state':'','support':'','considerations':''}]}
    document = env.get_template('form.html').render(user=user,errors=[],corpus_info={},corpus_error='',
                default_classroom_ref=user.classroom_refs[0],age_class_options=[f'{a}歳児' for a in range(6)],
                form_values=values,selected_month=10,search_query='')
    OUT.mkdir(exist_ok=True)
    (OUT/'index.html').write_text(document,encoding='utf-8')
    (OUT/'baseline.json').write_text(json.dumps({'app_commit':'ae885472c82c48e343d8eceeaecac1375c29b928',
                    'form_sha256':EXPECTED,'synthetic_data_only':True,'production_connections':False,
                    'scope':'日案例検索で年齢・月の指定をそれぞれ外す'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(OUT/'index.html')


if __name__=='__main__':
    main()
