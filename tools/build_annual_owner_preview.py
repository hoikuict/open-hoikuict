"""Create an isolated fictional annual-owner proposal from the deployed release."""
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace as NS
from jinja2 import Environment, DictLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.local-dev/weekly-production-20261011'
OUT = ROOT / 'tools/annual-owner-preview'
BASELINE = '5b142edd546a4a1761b8dc5aa3cf82d685a5241c'


def deployed(path):
    return subprocess.check_output(['git', '-c', f'safe.directory={SOURCE.as_posix()}',
        '-C', str(SOURCE), 'show', BASELINE + ':' + path]).decode('utf-8')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fixtures = (ROOT / 'tools/annual-creation-preview/fixtures.js').read_text(encoding='utf-8')
    classes = json.loads(fixtures.split('=', 1)[1].strip().rstrip(';'))
    (OUT / 'fixtures.js').write_text(fixtures, encoding='utf-8')
    env = Environment(loader=DictLoader({'sheet': deployed('templates/plan_docs/annual_library/_sheet.html')}), autoescape=select_autoescape())
    env.globals['static_asset_url'] = lambda path: Path(path).name
    markup = env.get_template('sheet').render(boot={}, classrooms=[NS(id=c['id'], name=c['name']) for c in classes], request=NS(app=NS(state=NS())), detail_mode=False)
    base = deployed('templates/base.html')
    (OUT / 'base.css').write_text('\n'.join(re.findall(r'<style>(.*?)</style>', base, re.S)[:2]), encoding='utf-8')
    (OUT / 'annual-library.css').write_text(deployed('static/css/annual-library.css'), encoding='utf-8')
    script = deployed('static/js/annual-library.js')
    script = script.replace("let boot = JSON.parse(document.getElementById('annual-library-boot').textContent);", 'let boot = window.AnnualOwnerMock.initial();')
    start = script.index('  async function api(')
    end = script.index('  async function load(', start)
    script = script[:start] + '  async function api(path, options = {}) { return window.AnnualOwnerMock.api(path, options, boot); }\n' + script[end:]
    script = re.sub(r'^.*history\.replaceState.*\n', '', script, flags=re.M)
    start = script.index('    const response=await fetch(')
    end = script.index('    boot.reflection_states=', start)
    script = script[:start] + '    const result=await window.AnnualOwnerMock.saveReflection(boot,reflection);\n' + script[end:]
    script = re.sub(r'function openReview\(index\)\{.*?\}', "function openReview(index){window.AnnualOwnerMock.notice('承認状況は今回の見本の対象外です。本番には接続しません。');}", script)
    script = script.replace('window.location.assign(`/plans/documents/${boot.document_id}/reflections/${index}/confirm`);', "window.AnnualOwnerMock.notice('反省の下書きをこの画面内に保存しました。承認依頼の送信は行いません。');")
    hooks = """
  window.AnnualOwnerMock.current=()=>({boot:clone(boot),dirty:dirty()});
  window.addEventListener('annual-owner-reset',()=>{adopt(window.AnnualOwnerMock.initial());message('確認用の状態を切り替えました。');});
  window.addEventListener('annual-owner-reopen',()=>{
    if(dirty()&&!confirm('未保存の入力を取り消して開き直しますか？'))return;
    adopt(window.AnnualOwnerMock.reopen(boot));message('この画面内に保存した内容を開き直しました。');
  });
"""
    script = script.replace('  adopt(boot);', hooks + '\n  adopt(boot);')
    assert 'fetch(' not in script and 'window.location' not in script and 'history.replaceState' not in script
    (OUT / 'annual-library.js').write_text(script, encoding='utf-8')
    shell = '''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'">
<title>確認用見本：年案の担任名</title><link rel="stylesheet" href="base.css"><link rel="stylesheet" href="preview.css"><script src="fixtures.js"></script><script src="preview.js" defer></script></head>
<body><header class="preview-toolbar no-print"><div><strong>確認用見本：年案の担任名</strong><span>架空データ・保存はこの画面内だけ／本番への保存・送信なし</span></div>
<div class="preview-controls"><label>表示ルール<select id="preview-rule"><option value="proposed">修正案：管理者を除く</option><option value="current">現在：管理者も含む</option></select></label>
<label>クラス担当登録<select id="preview-registration"><option value="both">担任2人＋管理者1人</option><option value="admin-only">管理者のみ（担任なし）</option></select></label>
<label>入力状態<select id="preview-state"><option value="new">新規・原本取込済み</option><option value="empty">本文未入力</option><option value="partial">本文一部入力</option><option value="filled">保存済み</option><option value="legacy">保存済み・管理者名あり</option><option value="error">保存エラー</option><option value="approved">承認済み・管理者名あり</option></select></label>
<button id="preview-reopen" type="button">保存内容を開き直す</button><a href="#annual-owner">担任名へ</a></div>
<p id="preview-note" role="status"></p></header>
<div class="preview-layout"><aside class="preview-sidebar no-print"><strong>hoikuict</strong><small>確認用</small><a href="#annual-plan-sheet">年間指導計画</a><a href="#annual-reflection-editor">年間指導計画反省</a></aside><main class="preview-main">__SHEET__</main></div></body></html>'''
    (OUT / 'index.html').write_text(shell.replace('__SHEET__', markup), encoding='utf-8')
    print(json.dumps({'baseline': BASELINE, 'classes': len(classes), 'fields': sum(len(c['sheet']['fields']) for c in classes), 'output': str(OUT)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
