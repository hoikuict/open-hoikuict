"""Keep the two new-admission paths together in the existing manual reader."""
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
p=HERE/'dist/app.js'
js=p.read_text(encoding='utf-8')
js=re.sub(r'// BEGIN ADMISSION NAVIGATION.*?// END ADMISSION NAVIGATION\n','',js,flags=re.S)
helper='''// BEGIN ADMISSION NAVIGATION
function admissionChoices(){return `<section class="admission-choices" aria-label="新入園児の登録"><div class="section-head"><h2>新入園児を登録する</h2><span>家庭の状況から選ぶ</span></div><div class="admission-grid">${['child-sibling','parent-qr'].map(card).join('')}</div></section>`;}
// END ADMISSION NAVIGATION
'''
js=js.replace('function home(){',helper+'function home(){',1)
js=js.replace('${searchBox()}<section class="entrances"','${searchBox()}${admissionChoices()}<section class="entrances"')
# The dedicated pair above is not repeated in the ordinary examples on the home page.
start=js.index('function home(){');end=js.index('function chapters(){',start)
home=js[start:end].replace('Object.keys(manualArticles).map(card)',"Object.keys(manualArticles).filter(id=>!['child-sibling','parent-qr'].includes(id)).map(card)")
js=js[:start]+home+js[end:]
entry="  admission:[['兄弟姉妹が在園している・以前在園していた','同じ家族へ追加し、保護者の閲覧対象を確認する','#article/child-sibling'],['初めて入園する家庭','共通QRで申し込み、園が確認・承認する','#article/parent-qr']],\n"
if '  admission:[' not in js: js=js.replace('const helpOptions={\n','const helpOptions={\n'+entry)
js=js.replace("${id==='clock'?'打刻の記録は、どんな状態ですか。':'どこで進めなくなりましたか。'}", "${id==='admission'?'新入園児のご家庭は、どちらですか。':id==='clock'?'打刻の記録は、どんな状態ですか。':'どこで進めなくなりましたか。'}")
js=js.replace('この試作版では、登録3種と日々の困りごと、計6つの場面を試せます。','この試作版では、共通QRの受付と新入園児の登録を含む9つの場面を試せます。')
js=js.replace('この試作版で画面付きの手順があるのは6例です。','この試作版で画面付きの手順があるのは9例です。')
js=js.replace('<p class="lead">${a.summary}</p><dl class="article-intro">','<p class="lead">${a.summary}</p>${a.admission?`<p class="admission-back"><a href="#help/admission">← 新入園児の登録方法を選び直す</a></p>`:""}<dl class="article-intro">')
if 'a.relatedArticles?.length' not in js:
    js=js.replace('</section><section class="faq">','</section>${a.relatedArticles?.length?`<section class="article-related"><h2>関連する手順</h2><div class="topic-list">${a.relatedArticles.map(articleLink).join(\'\')}</div></section>`:""}<section class="faq">')
js=js.replace('保護者の承認画面は登録申請欄を抜粋しています。','保護者の承認画面は登録申請欄を抜粋しています。新規入園の入力画面は、任意のもう1人の保護者欄を開いて撮影しています。') if '任意のもう1人の保護者欄を開いて撮影' not in js else js
p.write_text(js,encoding='utf-8')
p=HERE/'dist/index.html';html=p.read_text(encoding='utf-8').replace('モック v1.3.1','モック v1.5').replace('画面付きの手順：登録3種＋日々の3例','画面付きの手順：共通QR・新入園児など9例')
if 'href="#help/admission"' not in html:
    html=html.replace('<p class="nav-label">業務別の目次</p>','<a href="#help/admission" class="nav-main">新入園児を登録する <span>→</span></a>\n        <p class="nav-label">業務別の目次</p>')
p.write_text(html,encoding='utf-8')
p=HERE/'dist/style.css';css=p.read_text(encoding='utf-8')
css=re.sub(r'/\* BEGIN ADMISSION NAVIGATION \*/.*?/\* END ADMISSION NAVIGATION \*/\n?','',css,flags=re.S)
css+='''\n/* BEGIN ADMISSION NAVIGATION */
.admission-choices{margin:34px 0}.admission-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.admission-choices .issue-card{background:#fff;border-top:4px solid #629577}.admission-back{margin:-8px 0 22px;font-size:.88rem}.article-related{margin:32px 0}.admission-grid .issue-card h3{font-size:1.2rem;line-height:1.6}@media(max-width:760px){.admission-grid{grid-template-columns:1fr}.admission-choices .section-head{align-items:flex-start;gap:8px;flex-direction:column}}@media print{.admission-back,.article-related{display:none!important}}
/* END ADMISSION NAVIGATION */
'''
p.write_text(css,encoding='utf-8')
