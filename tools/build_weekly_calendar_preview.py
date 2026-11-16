"""Build an isolated UI proposal from deployed forms; never imports the app."""
from hashlib import sha256
import ast
import json
from pathlib import Path
import re
from types import SimpleNamespace

from jinja2 import DictLoader, Environment, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / '.local-dev/attendance-production-20261004'
OUT = ROOT / 'tools/weekly-calendar-preview'


def build_monthly(baseline):
    """Reuse deployed sheet markup and renderer, replacing only external effects."""
    paths = ['templates/plan_docs/monthly_library/_sheet.html', 'static/js/monthly-library.js',
             'static/css/monthly-library.css', 'plan_docs/services/monthly_library.py']
    sources = {p: (BASE / p).read_text(encoding='utf-8') for p in paths}
    baseline['monthly_sheet'] = {p: sha256(s.encode()).hexdigest() for p, s in sources.items()}
    def constants(source, wanted):
        return {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(source).body
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in wanted}
    contract = constants(sources[paths[3]], {'PERSONAL', 'COLUMNS', 'DOMAINS', 'TEMPLATES', 'TEMPLATE_VERSION'})
    contract['samples'] = constants((ROOT / 'tools/monthly_library_preview_data.py').read_text(encoding='utf-8'), {'COMMON', 'PERSONAL', 'GROUP'})
    (OUT / 'monthly-contract.js').write_text('window.monthlySheetContract = '+json.dumps(contract,ensure_ascii=False)+';\n',encoding='utf-8')
    js = sources[paths[1]]
    js = js.replace("JSON.parse(document.getElementById('monthly-library-boot').textContent)", 'window.monthlyPreview.context(1, "2026-10", 0)')
    for start, end, replacement in [
        ('  async function api(', '  function remember(', '  async function api(path, options = {}) { return window.monthlyPreview.request(path, options); }\n'),
        ('  async function mergeRequest(', '  function showCellConflicts(', '  async function mergeRequest(path, payload) { return window.monthlyPreview.request(path, {body:JSON.stringify(payload)}); }\n'),
        ('  function leavePresence(', '  async function refreshPresence(', '  function leavePresence() {}\n'),
        ('  function exportMonthly(', "  document.querySelector('[data-monthly-print]')", "  function exportMonthly(kind) { commitEdit(); if(kind==='pdf')window.print(); else announce('Excel出力の操作見本です。対象：'+ctx().classroom_name+'・'+ctx().target_month+'・'+ctx().age+'歳児。ファイル出力は本実装の既存機能に接続します。'); }\n"),
    ]:
        a, b = js.index(start), js.index(end)
        js = js[:a] + replacement + js[b:]
    js = js.replace("    q('#document-link').href = `/plans/documents/${ctx().document_id}`;", "    q('#document-link').href = '#';\n    window.monthlyPreview.onStatus?.(ctx(), [...cache.values()].some(dirty));")
    js = js.replace("'15秒ごとに確認。応答がなくなった職員は約1分で表示から外れます。'", "'同時編集者の表示は見本です。本番には接続していません。'")
    # Hidden monthly panels do not leave stale unload warnings after calendar navigation.
    js = js.replace('if(saving || [...cache.values()].some(dirty))', 'if(!root.closest("#monthly-editor").hidden && (saving || [...cache.values()].some(dirty)))')
    bridge = '''
  window.monthlyPreview.editor = {
    open(context) {
      searchSequence++; searchController?.abort(); historySequence++;
      cache.clear(); current=entry(clone(context)); cache.set(scopeKey(context),current);
      before=null; historyData=null; showHistory=false; keyword=''; mode='original';
      q('#keyword').value=''; render(); refreshPresence(); announce('');
    },
    refreshCandidates() { search(); },
    simulate(value) {
      if(!editable())return;
      commitEdit(); remember(); ctx().sheet.fields=window.monthlyPreview.sampleFields(ctx(),value);
      ctx().owner_name=value==='error'?'':'見本の保育士'; paper();panel();
      if(value==='error')announce('担任名を入力してください。入力した内容は残っています。',true);
    },
    discard() { this.open(window.monthlyPreview.context(ctx().classroom_id,ctx().target_month,ctx().age)); }
  };
  root.addEventListener('click',event=>{if(event.target.closest('a')){event.preventDefault();announce('確認用モックでは本番文書や原票へ移動しません。帳票の入力はこのまま続けられます。');}});
'''
    js = js.replace('  render();\n  refreshPresence();', bridge+'\n  render();\n  refreshPresence();')
    assert 'fetch(' not in js and 'form.submit()' not in js
    (OUT / 'monthly-sheet.js').write_text(js,encoding='utf-8')
    (OUT / 'monthly-sheet.css').write_text(sources[paths[2]],encoding='utf-8')
    template = re.sub(r'<script[\s\S]*$', '', sources[paths[0]])
    env=Environment(autoescape=select_autoescape(default=True))
    return env.from_string(template).render(detail_mode=False,boot={'editable':True},request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace())),
        classrooms=[{'id':i+1,'name':name} for i,name in enumerate(['ことり組（架空）','こりす組（架空）','ひかり組（架空）'])],
        static_asset_url=lambda path: 'monthly-sheet.css')


def main():
    OUT.mkdir(exist_ok=True)
    baseline = {'latest_deployment_record': 'deployment-plan-reflection-review-2026-10-11.md',
                'latest_deployed_commit': 'a9706b69137f1c14e2177be14f5806e7eae79a6a',
                'snapshot': '.local-dev/attendance-production-20261004',
                'synthetic_data_only': True, 'production_connections': False, 'forms': {}}
    base = (BASE / 'templates/base.html').read_text(encoding='utf-8')
    css = re.search(r'<style>\s*(\.plan-docs-content\s*\{.*?)</style>', base, re.S).group(1)
    (OUT / 'deployed.css').write_text(css, encoding='utf-8')
    forms = {}
    for kind in ('weekly',):
        path = f'templates/plan_docs/{kind}_plans/form.html'
        raw = (BASE / path).read_text(encoding='utf-8')
        baseline['forms'][kind] = {'path': path, 'sha256': sha256(raw.encode()).hexdigest(),
                                   'input_names': sorted(set(re.findall(r'name="([^"]+)"', raw)))}
        raw = re.sub(r'{% extends .*?%}', '', raw)
        raw = re.sub(r'{% block title %}.*?{% endblock %}', '', raw, flags=re.S)
        raw = raw.replace('{% block content %}', '').replace('{% endblock %}', '')
        raw = re.sub(r'<section class="form-header">.*?</section>', '', raw, flags=re.S)
        raw = re.sub(r'<form class="form-layout"[^>]+>', f'<form class="form-layout" id="{kind}-form" novalidate>', raw)
        raw = raw.replace('<a class="button button--ghost" href="/plans/">戻る</a>', '<button class="button button--ghost" type="button" data-cancel>取消してカレンダーへ</button><button class="button button--ghost" type="button" data-revert>保存した内容に戻す</button>')
        raw = raw.replace('週案帳票を作成', '下書きを保存（モック内）').replace('月案帳票を作成', '下書きを保存（モック内）')
        raw = raw.replace('<form class="form-layout"', '<form autocomplete="off" class="form-layout"')
        if kind == 'weekly':
            raw = raw.replace('type="week" required', 'type="week" required aria-describedby="week-range"')
            raw = raw.replace('土曜を含める</span>', '土曜を含める</span>')
            pos = raw.index('    </section>', raw.index('<form')) + len('    </section>')
            raw = raw[:pos] + '''
            <p id="week-range" class="field-note"></p>
            <section class="form-panel" id="source-panel">
              <h2>参考になる週案例を探す</h2>
              <p class="field-note">活動名から詳細を開き、必要な計画だけを下書きへコピーできます。ここでは原票の様式に合わせた架空例を表示しています。</p>
              <div class="field-grid search-fields">
                <label>参考例の年齢<select id="search-age"><option value="">すべて</option>''' + ''.join(f'<option value="{n}">{n}歳児</option>' for n in range(6)) + '''</select></label>
                <label>参考例の月<select id="search-month"><option value="">すべて</option>''' + ''.join(f'<option value="{n}" {"selected" if n == 10 else ""}>{n}月</option>' for n in range(1,13)) + '''</select></label>
                <label>キーワード<input type="search" id="search-keyword" placeholder="活動・ねらい・援助・準備"></label>
              </div>
              <p id="source-count" class="field-note" role="status"></p><div id="source-list"></div>
            </section>
            <section class="form-panel" id="plan-paper">
              <div class="paper-heading"><div><h2>週日指導計画（週案）</h2><p id="paper-scope" class="field-note"></p></div>
                <label>帳票の様式（年齢から自動選択）<select id="layout" disabled><option value="infant">0～2歳：月内の週を一覧</option><option value="older">3～5歳：曜日別</option></select></label>
              </div>
              <p class="field-note" id="paper-format-note"></p>
              <p class="field-note">園長印は承認表示のため、参考例から取り込みません。</p>
              <div id="paper-fields"></div>
            </section>
            ''' + raw[pos:]
        forms[kind] = raw
    env = Environment(loader=DictLoader(forms), autoescape=select_autoescape(default=True))
    user = SimpleNamespace(name='見本の保育士', can_edit=True, classroom_refs=('ことり組（架空）', 'こりす組（架空）', 'ひかり組（架空）'))
    rendered = {kind: env.get_template(kind).render(user=user, errors=[], form_values={},
                monthly_documents=[], annual_documents=[], default_classroom_ref=user.classroom_refs[0],
                age_class_options=[f'{n}歳児' for n in range(6)]) for kind in forms}
    monthly_sheet = build_monthly(baseline)
    shell = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'; frame-src 'none'">
<title>週案・月案カレンダー｜確認用モック</title><link rel="icon" href="data:,"><link rel="stylesheet" href="deployed.css"><link rel="stylesheet" href="preview.css"></head>
<body><div class="app-shell"><aside class="mock-sidebar"><div class="brand">open-hoikuict<small>STAFF CONSOLE</small></div><div class="staff-card">見本の保育士<small>編集可・架空の職員</small></div><div class="sidebar-links"><span>日々の業務</span><p>園児一覧</p><p>家族・兄弟姉妹の管理</p><p>児童票作成状況</p><p class="active">指導計画</p><p>健康管理</p><p>出欠一覧</p><span>連絡と記録</span><p>日次連絡</p><p>連絡タイムライン</p><p>設定</p></div></aside>
<main class="plan-docs-content">
<section class="mock-controls" aria-label="モックの確認操作"><div><strong>確認用モック・未確定の提案</strong><p>すべて架空データです。保存はこの画面内だけで、再読み込みすると元に戻ります。</p></div>
<div class="control-row"><label>入力状態<select id="mock-state"><option value="empty">未入力</option><option value="partial">一部入力</option><option value="filled">入力済み</option><option value="error">入力エラー</option></select></label>
<label>参考例の状態<select id="mock-source"><option value="normal">候補あり</option><option value="none">候補なし</option><option value="error">読込エラー</option></select></label>
<label class="inline-check"><input type="checkbox" id="save-error">保存失敗を試す</label><button type="button" id="reset-all">最初から試す</button></div></section>
<header class="page-header"><p class="eyebrow">指導計画</p><h1>月と週の計画をつなぐ</h1><p class="lead">作成状況を確認し、必要な月・週から計画を開けます。</p></header>
<nav class="view-tabs" aria-label="指導計画の画面"><button type="button" data-view="weekly" aria-pressed="true">週案カレンダー</button><button type="button" data-view="monthly" aria-pressed="false">月案カレンダー</button><button type="button" id="new-weekly">週案を作成</button></nav>
<div id="status-message" class="message" role="status" hidden></div><div id="error-message" class="error-message" role="alert" hidden tabindex="-1"></div>
<section id="calendar-view"><div class="calendar-toolbar"><label>クラス<select id="calendar-class"><option value="0">ことり組（架空・0歳児）</option><option value="1">こりす組（架空・2歳児）</option><option value="2">ひかり組（架空・5歳児）</option></select></label>
<label id="calendar-age-control" hidden>月案の年齢<select id="calendar-age"><option value="0">0歳児</option><option value="1">1歳児</option><option value="2">2歳児</option><option value="3">3歳児</option><option value="4">4歳児</option><option value="5">5歳児</option></select></label>
<div class="period-controls"><button type="button" id="previous-period" aria-label="前の期間">‹</button><label id="month-control">表示月<input type="month" id="calendar-month" value="2026-10" min="1900-01" max="2199-12"></label><label id="year-control" hidden>年度<select id="calendar-year"><option>2025</option><option selected>2026</option><option>2027</option></select></label><button type="button" id="next-period" aria-label="次の期間">›</button><button type="button" id="current-period">2026年10月</button></div></div>
<div class="calendar-intro"><h2 id="calendar-title"></h2><p id="calendar-description"></p><div class="legend"><span class="pill empty">未作成</span><span class="pill draft">下書き</span><span class="pill approved">承認済み</span></div></div>
<div id="calendar-content"></div><p class="field-note">週は月曜始まり。月をまたぐ週も同じ計画を表示します。祝日・休園日は自動判定せず、見本の活動欄に記入しています。</p></section>
<section id="weekly-editor" hidden><div class="editor-heading"><h2>週案を作成・編集</h2><span id="weekly-status" class="pill draft">未保存</span></div>
<p class="field-note">既存の月案接続・前週の振り返り・子どもの姿・家庭情報などは、帳票の下にすべて残しています。</p>''' + rendered['weekly'] + '''</section>
<section id="monthly-editor" hidden><div class="editor-heading"><h2>月案を作成・編集</h2><span id="monthly-status" class="pill draft">未保存</span></div><p class="field-note">追加済みの月案帳票へ接続しています。カレンダーで選んだ月・クラス・年齢の計画を開きます。園児・文例・履歴はすべて架空です。</p><button type="button" id="monthly-back">月案カレンダーへ戻る</button>''' + monthly_sheet + '''</section>
<details class="proposal-notes"><summary>今回の提案・参照した様式</summary><p>乳児：1か月の週別計画。幼児：1週間の曜日別計画。Google Driveの原票から項目を確認し、内容と氏名は架空のものに置き換えています。参考例のコピーでは、過去の評価反省・氏名・対象期間・承認印を引き継ぎません。</p><p>カレンダーは作成状況の管理を想定した提案です。対象年度、週区切り、承認方法、取り込む例の範囲は未確定です。</p></details>
</main></div>
<dialog id="confirm-dialog" aria-labelledby="confirm-title"><h2 id="confirm-title">入力内容の確認</h2><p id="confirm-message"></p><div class="dialog-actions"><button type="button" id="confirm-cancel">やめる</button><button type="button" id="confirm-yes" class="primary">続ける</button></div></dialog>
<script src="monthly-contract.js"></script><script src="monthly-preview.js"></script><script src="preview.js"></script><script src="monthly-sheet.js"></script></body></html>'''
    (OUT / 'index.html').write_text(shell, encoding='utf-8')
    (OUT / 'baseline.json').write_text(json.dumps(baseline, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(OUT / 'index.html')


if __name__ == '__main__':
    main()
