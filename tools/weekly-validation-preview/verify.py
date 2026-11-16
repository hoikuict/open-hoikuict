"""Check the generated input inventory and the prototype's offline boundary."""
from pathlib import Path
import json
import hashlib
from lxml import html

here=Path(__file__).resolve().parent
baseline=json.loads((here/'baseline.json').read_text(encoding='utf-8'))
checked=[]
for page in baseline['pages']:
    doc=html.parse(str(here/page['file']))
    fields=doc.xpath('//*[@id="preview-business"]//*[self::input or self::select or self::textarea]')
    assert [[e.tag,e.get('name'),e.get('type'),e.get('required') is not None] for e in fields]==page['field_contract']
    csp=doc.xpath('//meta[@http-equiv="Content-Security-Policy"]/@content')[0]
    assert "connect-src 'none'" in csp and "form-action 'none'" in csp
    for form in doc.xpath('//form'):assert form.get('action')=='#' and 'novalidate' in form.attrib
    for url in doc.xpath('//script/@src | //link[@rel="stylesheet"]/@href'):
        assert not url.startswith(('/', 'http')) and (here/url).is_file(),url
    if page['kind']=='editor':
        assert doc.xpath('//*[@id="weekly-save-feedback"]/..')[0]==doc.xpath('//*[@id="weekly-save"]/../..')[0]
        assert doc.xpath('//*[@id="weekly-save"]/following-sibling::button[@id="weekly-review"]')
        assert doc.xpath('//*[@id="weekly-review-target"]')
    checked.append({'file':page['file'],'static_fields_retained':len(fields)})
report={'source_commit':baseline['source_commit'],'pages':checked,'all_original_static_inputs_retained':True,
        'network_and_form_submission_blocked':True,'artifact_sha256':{
            p.relative_to(here).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in here.rglob('*') if p.is_file() and p.suffix in ('.py','.html','.js','.css')}}
(here/'static-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(f'PASS: {len(checked)} pages, input inventory and offline guards')
