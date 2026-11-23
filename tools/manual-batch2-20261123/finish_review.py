import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[2]
REVIEW=Path(__file__).resolve().parent/'review'
EVIDENCE=ROOT/'.local-dev/manual-batch2-20261123'
path=REVIEW/'entry.html'
html=path.read_text(encoding='utf-8')
if 'entry-full-new.jpg' not in html:
    full='<details><summary>入力画面全体と、保存・エラーの例を見る</summary><p>5つの本文欄と参考記録を含む画面全体です。画像を押すと拡大できます。</p>'
    for state,title,alt in [('new','未入力','児童票の入力画面全体。期間、5つの本文欄、参考記録、下書き保存。'),('saved','入力して保存した後','対象期間の子どもの姿と参考記録を保存した後の全体。ほかの本文欄は空欄。'),('error','必須欄が空のエラー','対象期間の子どもの姿が空のエラー。育ちと変化の入力内容は保持されている。')]:
        full+=f'<h3>{title}</h3><figure><img src="entry-full-{state}.jpg" alt="{alt}"><figcaption>{alt}</figcaption></figure>'
    full+='<p>エラーが出たら、案内された欄を修正して保存し直します。保存を確認できないときは入力を続け、画面を閉じる前に保存結果を確認してください。</p></details>'
    marker='    <section class="panel" id="logs">'
    html=html.replace(marker,full+'\n'+marker)
    path.write_text(html,encoding='utf-8')
path=REVIEW/'home.html'
html=path.read_text(encoding='utf-8').replace('パソコンの左のメニューで「ホーム」が選ばれ、右上の濃い色の欄に日付、職員名、担当クラスが出ています。','パソコンのホーム上部全体。日付、職員名、担当クラスと、要確認・在園中・次の予定が出ています。').replace('href="plans.html"','href="https://open.hoikuict.net/manual-guide-preview/plans/"')
marker='この例の「承認済み」は、週案の承認が済んだという意味です。</p>'
if '再承認の結果' not in html:
    html=html.replace(marker, marker+'<p>日案では、承認後の修正依頼・再承認依頼・再承認の結果もここに届きます。通知の種類と文書名を確認して開きます。</p>')
path.write_text(html,encoding='utf-8')

class Assets(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[];self.images=[];self.ids=set()
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if 'id' in attrs:self.ids.add(attrs['id'])
        if tag=='img' and attrs.get('src'):
            self.images.append(attrs)
            assert attrs.get('alt'),attrs
        for attribute in ('src','href'):
            if attribute in attrs:self.links.append(attrs[attribute])

parsers={}
for path in REVIEW.glob('*.html'):
    html=path.read_text(encoding='utf-8')
    def dimensions(match):
        tag=match.group(0)
        source=re.search(r'src="([^"]+)"',tag).group(1)
        with Image.open(REVIEW/source) as image:
            width,height=image.size
        tag=re.sub(r'\s(?:width|height)="[^"]*"','',tag)
        return tag[:-1]+f' width="{width}" height="{height}">'
    html=re.sub(r'<img[^>]+src="[^"]+"[^>]*>',dimensions,html)
    path.write_text(html,encoding='utf-8')
    parser=Assets();parser.feed(html);parsers[path.name]=parser
images=set();links=0
for name,parser in parsers.items():
    for attrs in parser.images:
        if attrs.get('src'):images.add(attrs['src'])
    for link in parser.links:
        split=urlsplit(link)
        if split.scheme:
            assert link.startswith('https://open.hoikuict.net/manual-guide-preview/'),link
            continue
        assert not split.scheme and not split.netloc,link
        target=REVIEW/(split.path or name)
        assert target.exists(),(name,link)
        if split.fragment:assert split.fragment in parsers[target.name].ids,(name,link)
        links+=1
assets=[{'path':p.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in REVIEW.rglob('*') if p.is_file()]
(EVIDENCE/'manifest.json').write_text(json.dumps({'published':False,'user_review_pending':True,'pages':len(parsers),'images':len(images),'links':links,'assets':assets},ensure_ascii=False,indent=2),encoding='utf-8')
for group in range((len(images)+11)//12):
    sheet=Image.new('RGB',(1200,960),'#e8eee9');draw=ImageDraw.Draw(sheet)
    for i,name in enumerate(sorted(images)[group*12:group*12+12]):
        with Image.open(REVIEW/name) as image:
            image.thumbnail((290,275));x=i%4*300;y=i//4*320
            sheet.paste(image,(x+(300-image.width)//2,y+25));draw.text((x+5,y+5),name,fill='#13271e')
    sheet.save(EVIDENCE/f'contact-{group+1}.jpg',quality=90)
print(json.dumps({'pages':len(parsers),'images':len(images),'links':links,'unpublished':True}))
