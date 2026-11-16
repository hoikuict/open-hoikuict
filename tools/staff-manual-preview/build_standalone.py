"""Package the review mock as one offline, double-clickable HTML document."""
from pathlib import Path
import base64
import hashlib
import json

HERE = Path(__file__).parent
DIST = HERE / 'dist'
html = (DIST / 'index.html').read_text(encoding='utf-8')
css = (DIST / 'style.css').read_text(encoding='utf-8')
catalog = (DIST / 'catalog.js').read_text(encoding='utf-8')
js = (DIST / 'app.js').read_text(encoding='utf-8')
images = {p.stem:'data:image/jpeg;base64,'+base64.b64encode(p.read_bytes()).decode('ascii') for p in sorted((DIST/'assets').glob('*.jpg'))}
assert len(images) == 123, f'Expected 123 screenshots, found {len(images)}'
html = html.replace("script-src 'self'; style-src 'self';", "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';")
html = html.replace('<link rel="stylesheet" href="style.css">', '<style>'+css+'</style>')
html = html.replace('<script src="catalog.js" defer></script>', '').replace('<script src="app.js" defer></script>', '')
assert 'src="assets/${image}.jpg"' in js
js = js.replace('src="assets/${image}.jpg"', 'src="${manualImageSources[image]}"')
assert "'assets/'+b.dataset.zoom+'.jpg'" in js
js = js.replace("'assets/'+b.dataset.zoom+'.jpg'", 'manualImageSources[b.dataset.zoom]')
html = html.replace('</body>', '<script>const manualImageSources='+json.dumps(images)+';\n'+catalog+'\n'+js+'</script></body>')
out = HERE / '職員向けマニュアル・モック.html'
out.write_text(html, encoding='utf-8')
manifest = {p.relative_to(HERE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DIST.rglob('*')) if p.is_file()}
manifest[out.name] = hashlib.sha256(out.read_bytes()).hexdigest()
(HERE/'artifact-hashes.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'{out}: {out.stat().st_size:,} bytes; 123 embedded screenshots')
