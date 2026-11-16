"""Verify the static prototype's input inventory and isolation without a browser or DB."""
from pathlib import Path
import hashlib
import json
from lxml import html

here = Path(__file__).resolve().parent
baseline = json.loads((here / 'baseline.json').read_text(encoding='utf-8'))
checked = []
for page in baseline['pages']:
    doc = html.parse(str(here / (page['key'] + '.html')))
    fields = doc.xpath('//*[@id="mock-business"]//*[self::input or self::select or self::textarea]')
    contract = [[el.tag, el.get('name'), el.get('type'), el.get('required') is not None] for el in fields]
    assert contract == page['field_contract'], page['key']
    csp = doc.xpath('//meta[@http-equiv="Content-Security-Policy"]/@content')[0]
    assert "connect-src 'none'" in csp and "form-action 'none'" in csp
    for form in doc.xpath('//form'):
        assert form.get('action') == '#' and 'novalidate' in form.attrib
    for url in doc.xpath('//script/@src | //link[@rel="stylesheet"]/@href'):
        assert not url.startswith(('http', '/', '//')) and (here / url).is_file(), url
    checked.append({'key': page['key'], 'original_fields_retained': len(fields)})
result = {
    'source_commit': baseline['source_commit'],
    'pages': checked,
    'input_contracts_match': True,
    'external_connections_blocked': True,
    'native_form_submissions_blocked': True,
    'artifact_sha256': {
        str(p.relative_to(here)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(here.rglob('*'))
        if p.is_file() and p.suffix in {'.html', '.css', '.js', '.py'}
    },
}
(here / 'static-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f"PASS: {len(checked)} pages; all original static inputs retained; offline guards present")
