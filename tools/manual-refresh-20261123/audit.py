from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit,unquote
import hashlib,json,subprocess
ROOT=Path(__file__).resolve().parents[2];DOCS=ROOT/'docs';SOURCE=ROOT/'.local-dev/document-search-rollout-20261108/source'
class Links(HTMLParser):
 def __init__(self):super().__init__();self.links=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  for key in ['href','src']:
   if key in a:self.links.append(a[key])
paths=['docs/manual-guide-preview/app.js','docs/manual-guide-preview/index.html','docs/manual-guide-preview/health/index.html','docs/manual-guide-preview/health/profile/index.html','docs/parent-app-manual.md','docs/extended-care-billing-transfer-spec.md','docs/manual-index.md','docs/manual-guide.md']
paths += [p.relative_to(ROOT).as_posix() for p in (DOCS/'manual-guide-preview/refresh-20261123').glob('*.html')]
paths += [p.relative_to(ROOT).as_posix() for p in (DOCS/'manual-guide-preview/assets').glob('r2-*.jpg')]
paths += [p.relative_to(ROOT).as_posix() for p in Path(__file__).parent.iterdir() if p.is_file()]
missing=[]
for relative in paths:
 p=ROOT/relative
 if p.suffix!='.html':continue
 parser=Links();parser.feed(p.read_text(encoding='utf-8'))
 for link in parser.links:
  u=urlsplit(link)
  if u.scheme or not u.path:continue
  target=p.parent/unquote(u.path)
  if not target.exists():missing.append([relative,link])
assert not missing,missing
manifest={'files':sorted(paths),'hashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},'relative_links_valid':True}
(ROOT/'.local-dev/manual-refresh-20261123/manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'files':len(paths),'relative_links_valid':True,'images':len([x for x in paths if x.endswith('.jpg')])}))
