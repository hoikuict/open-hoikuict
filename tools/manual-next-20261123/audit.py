"""Check review assets and save the review-only output manifest."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
import hashlib
import json
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BASE = Path(__file__).parent / 'review'
OUT = ROOT / '.local-dev/manual-next-20261123'

class AssetParser(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.images = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        for key in ('src', 'href'):
            target = data.get(key)
            if not target or target.startswith('#'):
                continue
            url = urlsplit(target)
            assert not url.scheme and not url.netloc, (self.page.name, target)
            path = (self.page.parent / unquote(url.path)).resolve()
            assert path.is_relative_to(BASE.resolve()) and path.exists(), (self.page.name, target)
        if tag == 'img' and data.get('src'):
            with Image.open(self.page.parent / data['src']) as image:
                assert image.size == (int(data['width']), int(data['height']))
            assert data.get('alt')
            self.images.append(data['src'])

used = set()
for page in BASE.glob('*.html'):
    parser = AssetParser(page)
    parser.feed(page.read_text(encoding='utf-8'))
    used.update(parser.images)
assert len(used) == 36, len(used)
assert {p.name for p in (BASE / 'images').glob('*.jpg')} == {Path(p).name for p in used}
manifest = dict(published=False, user_review_pending=True, pages=5, images=len(used), assets=[])
for path in sorted(BASE.rglob('*')):
    if path.is_file():
        data = path.read_bytes()
        manifest['assets'].append(dict(path=path.relative_to(ROOT).as_posix(), bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
(OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(dict(passed=True,pages=manifest['pages'],images=manifest['images'],assets=len(manifest['assets']),published=False)))
