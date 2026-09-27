"""Chief stamp mock from the deployed export release, using fictional memory data."""
from pathlib import Path
import hashlib
import json
import os
import sys
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORK = ROOT/'.local-dev/monthly-chief-stamp-preview-20260927'
SOURCE = WORK/'source'
BASE = ROOT/'.local-dev/truenas-monthly-export-20260927/bundle'


def prepare():
    manifest = json.loads((BASE/'UPDATE.json').read_text(encoding='utf-8'))
    assert manifest['commit'] == '696a8609d75a91da5f39c7a4d67d76a9d5dddd0f'
    archive = BASE/'source.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['source_sha256']
    if not SOURCE.exists():
        SOURCE.mkdir(parents=True)
        with tarfile.open(archive) as tar:
            tar.extractall(SOURCE, filter='data')
        layout = SOURCE/'plan_docs/services/monthly_export_layout.py'
        value = layout.read_text(encoding='utf-8')
        value = value.replace("        chief = c['age'] == 1 or c['age'] >= 3\n", '')
        value = value.replace("('園長印：', 50, 11 if chief else 22)]\n        if chief:\n            labels.append(('主任：', 61, 11))", "('園長印：', 50, 11), ('主任印：', 61, 11)]")
        assert 'if chief' not in value and '主任印：' in value
        layout.write_text(value, encoding='utf-8', newline='\n')
        script = SOURCE/'static/js/monthly-library.js'
        value = script.read_text(encoding='utf-8')
        value = value.replace('    const chief = ctx().age === 1 || !individual();\n', '')
        value = value.replace("${chief?'<th>主任</th>':''}", '<th>主任印</th>')
        value = value.replace("${chief?'<td></td>':''}", '<td></td>')
        assert 'chief' not in value and '<th>主任印</th>' in value
        script.write_text(value, encoding='utf-8', newline='\n')


def build_preview():
    prepare()
    os.chdir(SOURCE)
    sys.path.insert(0, str(SOURCE))
    os.environ['HOIKU_MONTHLY_OLLAMA_SOURCES'] = '{}'
    os.environ['HOIKUICT_COOKIE_SECURE'] = '0'
    from fastapi.responses import HTMLResponse, Response, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from test_monthly_library import MonthlyLibraryTests
    from tools.monthly_library_preview_data import seed_preview_phrases
    fixture = MonthlyLibraryTests()
    fixture.setUp()
    fixture.app.state.monthly_library_fixture = True
    seed_preview_phrases(fixture.corpus)
    fixture.corpus_bytes = fixture.corpus.read_bytes()
    context = fixture.context().json()
    saved = fixture.save(fixture.payload(context))
    saved.raise_for_status()
    document_id = saved.json()['document_id']
    app = fixture.app
    app.middleware_stack = None
    controls = (HERE/'controls.html').read_text(encoding='utf-8')
    script = (SOURCE/'static/js/monthly-library.js').read_text(encoding='utf-8')
    marker = '  render();\n  new ResizeObserver'
    assert script.count(marker) == 1
    script = script.replace(marker, (HERE/'hooks.js').read_text(encoding='utf-8')+'\n'+marker)
    script = script.replace("form.action='/plans/monthly-library/export-file'", "form.action='/plans/monthly-library/export-file'+(chiefPreviewError?'?preview_error=1':'')")

    @app.middleware('http')
    async def preview_layer(request, call_next):
        if request.url.path == '/':
            return RedirectResponse('/plans/monthly-library?document_id='+str(document_id))
        if request.url.path == '/static/js/monthly-library.js':
            return Response(script, media_type='text/javascript', headers={'Cache-Control':'no-store'})
        if request.url.path == '/plans/monthly-library/export-file' and request.query_params.get('preview_error') == '1':
            return HTMLResponse('<!doctype html><html lang="ja"><meta charset="utf-8"><h1>出力エラーの見本</h1><p>元の編集画面の入力は保持しています。「帳票の状態」を切り替えると再試行できます。</p></html>', status_code=503)
        response = await call_next(request)
        if response.status_code == 200 and request.url.path == '/plans/monthly-library':
            content = b''.join([chunk async for chunk in response.body_iterator]).decode('utf-8')
            assert '<main' in content
            insert = content.index('>', content.index('<main'))+1
            return HTMLResponse(content[:insert]+controls+content[insert:], headers={
                key:value for key,value in response.headers.items() if key not in {'content-length','content-type'}})
        return response

    app.mount('/static', StaticFiles(directory=SOURCE/'static'), name='static')
    return fixture


if __name__ == '__main__':
    import uvicorn
    fixture = build_preview()
    try:
        uvicorn.run(fixture.app, host='127.0.0.1', port=8901, log_level='warning')
    finally:
        fixture.tearDown()
