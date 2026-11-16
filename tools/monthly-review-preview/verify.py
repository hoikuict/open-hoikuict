"""Check preserved fields, button adjacency and offline isolation."""
from pathlib import Path
import hashlib
import json
from lxml import html

root=Path(__file__).resolve().parent
baseline=json.loads((root/'baseline.json').read_text(encoding='utf-8'))
checked=[]
for page in baseline['pages']:
    doc=html.parse(str(root/page['file']))
    inputs=doc.xpath('//*[@id="preview-business"]//*[self::input or self::select or self::textarea]')
    assert [[e.tag,e.get('name'),e.get('type'),e.get('required') is not None] for e in inputs]==page['field_contract']
    csp=doc.xpath('//meta[@http-equiv="Content-Security-Policy"]/@content')[0]
    assert "connect-src 'none'" in csp and "form-action 'none'" in csp
    assert all(e.get('action')=='#' for e in doc.xpath('//form'))
    for asset in doc.xpath('//script/@src | //link[@rel="stylesheet"]/@href'):
        assert not asset.startswith(('http','/')) and (root/asset).is_file(),asset
    if page['kind']=='editor':
        pair=doc.xpath('//*[@id="save"]/parent::*')[0]
        assert [e.get('id') for e in pair]==['save','request-monthly-review']
    checked.append({'file':page['file'],'retained_static_fields':len(inputs)})
report={'source_commit':baseline['source_commit'],'verified':True,'pages':checked,
    'asset_hashes':{p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.suffix in ('.html','.css','.js','.py')}}
(root/'static-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(f'PASS {len(checked)} pages: existing fields, adjacent buttons and offline guards')
