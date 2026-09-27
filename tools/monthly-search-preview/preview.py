"""Full deployed monthly UI, fictional DB, proposed search only, loopback only."""
from __future__ import annotations

import argparse
from contextvars import ContextVar
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

from search_behavior import EXAMPLES, matches
from added_phrases import PreviewPhraseStore, install_routes
from export_routes import install_export_routes

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_SOURCE = ROOT / ".local-dev/truenas-notice-order-20260927/source"
MATCH_MODE = ContextVar("preview_match", default="spelling")


def build_preview(source: Path):
    # Import the deployed baseline's test fixture, never main.py/application startup.
    os.chdir(source)
    sys.path.insert(0, str(source))
    os.environ["HOIKU_MONTHLY_OLLAMA_SOURCES"] = "{}"
    os.environ["HOIKUICT_COOKIE_SECURE"] = "0"
    from fastapi.responses import HTMLResponse, Response, JSONResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from test_monthly_library import MonthlyLibraryTests
    from tools.monthly_library_preview_data import seed_preview_phrases
    from plan_docs.routers import monthly_library as router_module
    from plan_docs.services import monthly_library as library_module
    from plan_docs.services.monthly_library import field_definitions, normalize

    fixture = MonthlyLibraryTests()
    fixture.setUp()
    fixture.app.state.monthly_library_fixture = True
    seed_preview_phrases(fixture.corpus)
    with closing(sqlite3.connect(fixture.corpus)) as con:
        con.execute("INSERT INTO source VALUES(3, 'fictional/search-comparison.xls')")
        con.execute("INSERT INTO cell VALUES(3, 3, '検索の比較（架空）')")
        rows = []
        for age in range(6):
            for month in range(1, 13):
                definitions = field_definitions({"age": age, "children": [{"ref": "child:1"}]}, f"2026-{month:02}")
                keys = ['common:goal', 'child:1:play'] if age < 3 else ['common:goal', 'group:expression:expected']
                for index, key in enumerate(keys):
                    d = definitions[key]
                    for variant, example in enumerate(EXAMPLES):
                        text = "【架空例】" + example
                        phrase_id = 100000 + age * 10000 + month * 100 + index * 20 + variant
                        rows.append((phrase_id, text, normalize(text), age, month, d['item'], d['section'], d['ryoiki']))
        con.executemany("INSERT INTO phrase VALUES(?,3,3,?,?,?,?,2026,?,?,?)", rows)
        con.commit()
    fixture.corpus_bytes = fixture.corpus.read_bytes()
    # A real save in the fixture's in-memory DB gives the initial page a stable scope.
    context = fixture.context().json()
    saved = fixture.save(fixture.payload(context))
    saved.raise_for_status()
    document_id = saved.json()['document_id']
    for month in ('2026-07', '2026-08', '2026-09'):
        context = fixture.context(month).json()
        fields = {f'child:1:{key}': {'body': f'【架空の履歴】{month}の{label}の記録。'}
                  for key, label in [('life', '生活'), ('play', '遊び'), ('help', '援助'), ('review', '振り返り')]}
        if month != '2026-08':
            fields['child:2:play'] = {'body': '【架空の履歴】身近な遊びを楽しんだ。'}
        fixture.save(fixture.payload(context, fields)).raise_for_status()

    original_search = library_module.search_phrases
    store = PreviewPhraseStore(field_definitions)

    def preview_search(nursery_ref, definition, age, month, keyword='', offset=0, **kwargs):
        phrase_ids = kwargs.get('phrase_ids')
        added = store.find(definition, age, month, phrase_ids) if nursery_ref == fixture.user.nursery_ref else []
        if phrase_ids is not None:
            page = original_search(nursery_ref, definition, age, month, keyword, offset, **kwargs)
            return {'items': page['items'] + added, 'has_more': False}
        # Fictional corpus only. Keep production facet checks and source identities.
        rows = [row for row in reversed(added) if matches(row['text'], keyword, MATCH_MODE.get())]
        start = 0
        while True:
            page = original_search(nursery_ref, definition, age, month, '', start)
            rows.extend(row for row in page['items'] if matches(row['text'], keyword, MATCH_MODE.get()))
            if not page['has_more']:
                break
            start += len(page['items'])
        return {'items': rows[offset:offset + 50], 'has_more': len(rows) > offset + 50}

    router_module.search_phrases = preview_search
    library_module.search_phrases = preview_search
    app = fixture.app
    # setUp/seed requests built the test stack; rebuild it once with this preview layer.
    app.middleware_stack = None
    install_routes(app, store)
    install_export_routes(app, fixture.temp.name, field_definitions)
    app.mount('/static', StaticFiles(directory=source / 'static'), name='static')
    controls = (HERE / 'controls.html').read_text(encoding='utf-8')
    controls += (HERE / 'add-dialog.html').read_text(encoding='utf-8')
    controls += (HERE / 'print-style.html').read_text(encoding='utf-8')
    controls += '<script id="preview-phrase-catalog" type="application/json">' + json.dumps(store.catalog) + '</script>'
    hooks = (HERE / 'hooks.js').read_text(encoding='utf-8')
    hooks += '\n' + (HERE / 'add-hooks.js').read_text(encoding='utf-8')
    hooks += '\n' + (HERE / 'print-hooks.js').read_text(encoding='utf-8')
    script = (source / 'static/js/monthly-library.js').read_text(encoding='utf-8')
    marker = '  render();\n  new ResizeObserver'
    if script.count(marker) != 1:
        raise RuntimeError('Deployed UI changed; review preview hooks before starting')
    script = script.replace(marker, hooks + '\n' + marker)

    @app.middleware('http')
    async def preview_layer(request, call_next):
        path = request.url.path
        if path == '/':
            return RedirectResponse(f'/plans/monthly-library?document_id={document_id}')
        if path == '/static/js/monthly-library.js':
            return Response(script, media_type='application/javascript', headers={'Cache-Control': 'no-store'})
        if path == '/plans/monthly-library/generate':
            return JSONResponse({'detail': '検索の見本ではAIは未接続です。'}, status_code=503)
        if path.endswith('/candidates') and request.query_params.get('preview_error') == '1':
            return JSONResponse({'detail': '【見本のエラー】候補を読み込めません。帳票の入力は保持されています。'}, status_code=503)
        mode = request.query_params.get('preview_match', 'spelling')
        token = MATCH_MODE.set(mode if mode in ('current', 'spelling', 'related') else 'spelling')
        try:
            response = await call_next(request)
        finally:
            MATCH_MODE.reset(token)
        if (path == '/plans/monthly-library' or path.startswith('/plans/documents/')) and response.status_code == 200 and 'text/html' in response.headers.get('content-type',''):
            content = b''.join([chunk async for chunk in response.body_iterator]).decode('utf-8')
            content = content.replace('<div id="drive-monthly-plan"', controls + '<div id="drive-monthly-plan"', 1)
            content = content.replace('<title>帳票から月案をつくる', '<title>月案の操作見本・検索・文例追加・印刷')
            headers = {k: v for k, v in response.headers.items() if k.lower() not in ('content-length', 'content-type')}
            headers['Cache-Control'] = 'no-store'
            return HTMLResponse(content, headers=headers)
        return response

    return fixture


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--port', type=int, default=8897)
    args = parser.parse_args()
    fixture = build_preview(args.source.resolve())
    import uvicorn
    try:
        uvicorn.run(fixture.app, host='127.0.0.1', port=args.port, log_level='warning')
    finally:
        fixture.tearDown()
