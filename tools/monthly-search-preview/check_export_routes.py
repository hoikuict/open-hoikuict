"""Export API checks using only the disposable mock application."""
from pathlib import Path
from unittest.mock import patch

from preview import build_preview, DEFAULT_SOURCE


def main():
    fixture = build_preview(DEFAULT_SOURCE)
    client = fixture.client
    try:
        before = fixture.context().json()
        snapshot = fixture.context().json()
        snapshot['sheet']['fields']['common:goal'] = {'body': '=1+1\n【架空】保存前の出力確認。'}
        snapshot['sheet']['fields']['child:2:play'] = {'body': '【架空】別の園児も出力する。'}
        for kind in ('pdf', 'xlsx'):
            response = client.post('/plans/monthly-library/preview-export', json={'kind': kind, 'context': snapshot})
            response.raise_for_status()
            result = response.json()
            assert result['pages'] == 1
            url = result['url']
            if kind == 'pdf':
                html = client.get(url)
                assert html.status_code == 200 and 'この帳票を印刷' in html.text
                url = url.removesuffix('/preview')
                page = client.get(url + '/page/1')
                assert page.status_code == 200 and page.content.startswith(b'\x89PNG')
                assert client.get(url + '/page/2').status_code == 404
            output = client.get(url)
            assert output.status_code == 200
            assert output.content.startswith(b'%PDF' if kind == 'pdf' else b'PK')
            assert output.headers['cache-control'] == 'no-store'
            dest = Path(__file__).resolve().parents[2] / '.local-dev/monthly-print-export-20260927'
            (dest / f'api-output.{kind}').write_bytes(output.content)
            assert fixture.context().json() == before, 'Export must not save the document'
        snapshot['sheet']['fields']['unknown:field'] = {'body': 'invalid'}
        assert client.post('/plans/monthly-library/preview-export', json={'kind':'pdf','context':snapshot}).status_code == 422
        del snapshot['sheet']['fields']['unknown:field']
        with patch('export_routes.subprocess.run', side_effect=OSError('fictional export failure')):
            failed = client.post('/plans/monthly-library/preview-export', json={'kind':'pdf','context':snapshot})
            assert failed.status_code == 503 and '画面の入力は保持' in failed.text
        assert fixture.context().json() == before
        assert client.get('/plans/monthly-library/preview-export/not-found').status_code == 404
        assert fixture.corpus.read_bytes() == fixture.corpus_bytes
        print('Export routes passed: PDF preview/download, Excel download, unsaved snapshot, no DB writes, validation, failure, missing file.')
    finally:
        fixture.tearDown()


if __name__ == '__main__':
    main()
