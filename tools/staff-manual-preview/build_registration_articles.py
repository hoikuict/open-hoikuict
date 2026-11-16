"""Insert the reviewed registration articles and actual image dimensions into the reader."""
import json
import re
from pathlib import Path
from PIL import Image

HERE=Path(__file__).resolve().parent
dist=HERE/'dist'
articles=json.loads((HERE/'registration_articles.json').read_text(encoding='utf-8'))
admissions=json.loads((HERE/'admission_articles.json').read_text(encoding='utf-8'))
articles={**json.loads((HERE/'qr_article.json').read_text(encoding='utf-8')),**admissions,**articles,**json.loads((HERE/'parent_attendance_articles.json').read_text(encoding='utf-8'))}
articles.update(json.loads((HERE/'parent_app_articles.json').read_text(encoding='utf-8')))
from audit_review_content import apply_review
apply_review(articles)
articles['child']['title']='園で直接入力して、園児台帳に登録する'
articles['child']['summary']='園が氏名・家族・保護者の情報を直接入力する方法です。新入園児は、先に家庭の状況に合う手順を確認してください。'
articles['child']['admission']=True
articles['child']['relatedArticles']=['parent-qr','child-sibling','parent']
articles['child']['source']='guardian-account-sync/'
js=(dist/'app.js').read_text(encoding='utf-8')
js=re.sub(r'  // BEGIN REGISTRATION ARTICLES.*?  // END REGISTRATION ARTICLES\n','',js,flags=re.S)
block='  // BEGIN REGISTRATION ARTICLES\n'+json.dumps(articles,ensure_ascii=False,indent=2)[2:-2]+',\n  // END REGISTRATION ARTICLES\n'
js=js.replace('const manualArticles = {\n','const manualArticles = {\n'+block,1)
sizes={p.stem:list(Image.open(p).size) for p in sorted((dist/'assets').glob('*.jpg'))}
assert len(sizes)==123
for article in articles.values():
    for step in article['steps']:
        if 'image' in step: assert step['image'] in sizes
        for state,_ in step.get('states',[]): assert step.get('imagePrefix',article['imagePrefix'])+'-'+state in sizes
js=re.sub(r'const screenshotSizes = .*?;', 'const screenshotSizes = '+json.dumps(sizes)+';',js,count=1)
js=js.replace("id==='phone'?'#article/phone':'#help/'+id", "['clock','password'].includes(id)?'#help/'+id:'#article/'+id")
js=js.replace("['欠席の電話','打刻忘れ','ログインできない']","['職員登録','園児登録','保護者登録','打刻忘れ']")
js=js.replace('このモックで試せるのは、3つの場面です。','この試作版では、登録3種と日々の困りごと、計6つの場面を試せます。')
js=js.replace('このモックで画面付きの手順があるのは3例です。','この試作版で画面付きの手順があるのは6例です。')
js=js.replace("const prefix=currentArticle==='phone'?'phone':'monthly';", "const prefix=a.imagePrefix||(currentArticle==='phone'?'phone':'monthly');")
js=js.replace('こんな場面から、試してみる','登録の準備と、日々の困りごと')
js=js.replace('2026-11-01の配備記録と保存済みテンプレートをもとに','2026-11-01〜03の配備記録と保存済みテンプレートをもとに')
excerpt_note='保護者の承認画面は登録申請欄を抜粋しています。'
if excerpt_note not in js:
    js=js.replace('一括補完の画面は入力欄を縦に展開しています。','一括補完の画面は入力欄を縦に展開しています。'+excerpt_note)
js=re.sub('(?:'+re.escape(excerpt_note)+'){2,}',excerpt_note,js)
(dist/'app.js').write_text(js,encoding='utf-8')
p=dist/'index.html'; p.write_text(p.read_text(encoding='utf-8').replace('モック v1.1','モック v1.2'),encoding='utf-8')
print('Built 20 articles and 123 screenshots total.')
