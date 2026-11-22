"""Export only the reviewed manual UI and synthetic screenshots into MkDocs."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shutil

parser = argparse.ArgumentParser()
parser.add_argument('--destination', type=Path, required=True)
args = parser.parse_args()
source = Path(__file__).resolve().parent / 'dist'
destination = args.destination.resolve()
destination.mkdir(parents=True, exist_ok=True)
if any(destination.iterdir()):
    raise SystemExit('Destination must be empty; inspect existing published assets before replacing them.')
version = '20261103-v15'
for name in ['index.html', 'style.css', 'app.js', 'catalog.js']:
    text = (source / name).read_text(encoding='utf-8')
    if name == 'index.html':
        text = text.replace('<title>', '<meta name="robots" content="noindex,follow">\n  <meta name="description" content="保護者・保育園職員向けのスクリーンショット付きマニュアルの試作版。業務別の目次と、困りごとから手順を探せます。">\n  <title>', 1)
        text = text.replace('href="style.css"', f'href="style.css?v={version}"')
        text = text.replace('src="catalog.js"', f'src="catalog.js?v={version}"').replace('src="app.js"', f'src="app.js?v={version}"')
        text = text.replace('モック v1.8.1</span>', '試作版 v1.8.1</span>')
    elif name == 'style.css':
        text += '\n.site-return{display:inline-flex;align-items:center;font-size:.78rem;padding:8px;text-decoration:none;white-space:nowrap}@media(max-width:760px){.site-return{font-size:.66rem;padding:6px}.site-head{gap:7px}.head-actions{flex-wrap:wrap;justify-content:flex-end}.brand{flex-shrink:0}}@media(max-width:760px){.site-head{height:auto;min-height:81px;flex-wrap:wrap;padding:12px 17px}.head-actions{margin-left:auto;flex-wrap:nowrap}}\n'
    elif name == 'app.js':
        text = text.replace('assets/${image}.jpg', f'assets/${{image}}.jpg?v={version}')
        text = text.replace("'assets/'+b.dataset.zoom+'.jpg'", f"'assets/'+b.dataset.zoom+'.jpg?v={version}'")
    (destination/name).write_text(text, encoding='utf-8', newline='\n')
images = sorted((source/'assets').glob('*.jpg'))
assert len(images) == 123
(destination/'assets').mkdir()
for image in images:
    shutil.copyfile(image, destination/'assets'/image.name)
files = {p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.rglob('*') if p.is_file()}
assert len(files) == 127
for name in ['index.html', 'app.js', 'catalog.js', 'style.css']:
    text = (destination/name).read_text(encoding='utf-8')
    assert not re.search(r'(?:localhost|127\.0\.0\.1|C:\\\\|\.local-dev)', text)
print(json.dumps({'destination':str(destination),'files':files},ensure_ascii=False,indent=2))
