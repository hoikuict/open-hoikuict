"""Add a plain-language parent entrance without replacing staff guidance."""
from pathlib import Path
import re
HERE=Path(__file__).resolve().parent
p=HERE/'dist/app.js';js=p.read_text(encoding='utf-8')
js=re.sub(r'// BEGIN PARENT GUIDE.*?// END PARENT GUIDE\n','',js,flags=re.S)
block='// BEGIN PARENT GUIDE\n'+(HERE/'parent-guide.js').read_text(encoding='utf-8')+'\n// END PARENT GUIDE\n'
js=js.replace("let currentArticle=",block+"let currentArticle=",1)
js=js.replace("function article(id){const a=manualArticles[id];return", "function article(id){const a=manualArticles[id];if(a.audience==='parents')return parentArticle(id);return")
js=js.replace("let html;switch(page){case 'chapters'", "setManualAudience(page,arg);let html;switch(page){case 'parents':html=parentHome();break;case 'parent-help':html=parentHelp();break;case 'chapters'")
js=js.replace("Object.keys(manualArticles).filter(id=>!['child-sibling','parent-qr'].includes(id))", "Object.keys(manualArticles).filter(id=>manualArticles[id].audience!=='parents'&&!['child-sibling','parent-qr'].includes(id))")
js=js.replace('Object.keys(manualArticles).map(card)',"Object.keys(manualArticles).filter(id=>manualArticles[id].audience!=='parents').map(card)")
js=js.replace('a.chapter===i)',"a.chapter===i&&a.audience!=='parents')")
js=js.replace('function home(){return `','function home(){return `<a class="parent-entry" href="#parents"><strong>保護者の方はこちら →</strong><span>園に着いたとき・お迎えのときの使い方</span></a>',1) if 'class="parent-entry"' not in js else js
js=js.replace('画面付きの手順があるのは9例','画面付きの手順があるのは職員向け9例・保護者向け2例')
js=js.replace('配備記録に対応する画面の見本・架空データ${',"${a.audience==='parents'?'画面の見本。名前や時刻は例です。':'配備記録に対応する画面の見本・架空データ'}${")
js=js.replace('保護者向け9例','保護者向け11例')
js=js.replace('見本の状態 <select',"${a.audience==='parents'?'ほかの画面を見る':'見本の状態'} <select")
js=js.replace('｜オープン保育ICT・モック','｜オープン保育ICT・使い方ガイド')
js=js.replace("case 'parents':html=parentHome();break;", "case 'parents':html=parentHome();break;case 'parent-app':html=parentAppHome();break;") if "case 'parent-app'" not in js else js
js=js.replace('園に着いたとき・お迎えのときの使い方','保護者アプリと、登園・降園の使い方').replace('モック v1.8</span>','モック v1.8.1</span>').replace('保護者向け2例','保護者向け11例')
p.write_text(js,encoding='utf-8')
p=HERE/'dist/index.html';html=p.read_text(encoding='utf-8').replace('モック v1.5','モック v1.6')
if 'href="#parents"' not in html:html=html.replace('<p class="nav-label">探し方を選ぶ</p>','<a href="#parents" class="nav-main">保護者用のマニュアル →</a><p class="nav-label">探し方を選ぶ</p>')
html=html.replace('モック v1.6','モック v1.7').replace('モック v1.7</span>','モック v1.8</span>').replace('モック v1.8</span>','モック v1.8.1</span>').replace('保護者向け2例','保護者向け11例')
html=html.replace('画面付きの手順：共通QR・新入園児など9例','画面付きの手順：職員向け9例・保護者向け2例')
p.write_text(html,encoding='utf-8')
p=HERE/'dist/style.css';css=p.read_text(encoding='utf-8')
css=re.sub(r'/\* BEGIN PARENT GUIDE \*/.*?/\* END PARENT GUIDE \*/\n?','',css,flags=re.S)
css+='''\n/* BEGIN PARENT GUIDE */
.parent-app-start{display:inline-block;background:#236b55;color:white;border-radius:8px;padding:13px 18px;text-decoration:none;font-weight:700}.parent-entry{display:flex;align-items:center;justify-content:space-between;gap:15px;text-decoration:none;border:1px solid #b3caba;border-left:5px solid #236b55;border-radius:10px;padding:18px 22px;background:#fff;margin-bottom:30px}.parent-entry span{font-size:.85rem}.parent-cards{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:30px 0}.parent-guide .issue-card{padding:28px;border-top:5px solid #639378}.parent-guide .issue-card h3{font-size:1.5rem}.parent-guide .issue-card p{font-size:1rem}.parent-guide .issue-card .bottom{font-size:.9rem}.parent-guide .eyebrow{font-size:.9rem}.parent-guide .lead,.parent-guide .step-body>p{font-size:1.05rem}.parent-guide .notice,.parent-guide .callouts,.parent-guide .faq details p{font-size:1rem}.parent-guide .step-heading h2{font-size:1.25rem}.parent-before{border-left:4px solid #7ca58c;padding-left:16px}.parent-help-link{display:block;background:#fff;padding:20px;border:1px solid var(--line);border-radius:10px;margin:22px 0;text-decoration:none}.parent-help-link span{display:block;color:var(--muted);font-size:.9rem;margin-top:8px}.parent-tip{background:white;border:1px solid var(--line);padding:25px;border-radius:12px;margin:24px 0}.parent-tip p{font-size:1rem}.parent-related{display:grid;gap:15px;margin-top:26px}.parent-guide .ui-ref{padding:.05em .3em}.parent-guide .faq summary{font-size:1rem}.parent-guide .screen figcaption{font-size:.75rem}.parent-guide .parent-cards .tiny{font-size:.8rem}.parent-guide .state-select select{max-width:100%}
@media(max-width:760px){.parent-cards{grid-template-columns:1fr}.parent-entry{align-items:flex-start;flex-direction:column;gap:6px}.parent-guide main{padding:24px 17px}.parent-guide .parent-tip{padding:20px}.parent-guide .step-nav button{min-width:150px}.parent-guide .step-body{padding:20px 16px}.parent-guide .step-heading h2{font-size:1.12rem}.parent-guide .next-prev button{padding:10px}.parent-guide .screen figcaption{font-size:.7rem}}
@media print{.parent-entry,.parent-help-link,.parent-related{display:none!important}.parent-guide .step-body>p,.parent-guide .notice,.parent-guide .callouts{font-size:12px}}
.parent-guide .screen-focused{max-width:600px}.screen-focused button{position:relative;aspect-ratio:600/340}.screen-focused img{position:absolute;top:0;left:0;width:100%;height:auto}.screen-focused[data-frame="app-home-child"] button{aspect-ratio:600/280}.screen-focused[data-frame="app-home-unread"] button{aspect-ratio:600/195}.screen-focused[data-frame="app-home-updates"] button{aspect-ratio:600/575}.screen-focused[data-frame="app-home-menu"] button{aspect-ratio:600/410}.screen-focused[data-frame="app-contact-entry"] button,.screen-focused[data-frame="app-pickup-entry"] button{aspect-ratio:585/965}@media print{.screen-focused img{max-height:none;object-fit:fill}}
.screen-compact[data-frame="app-pickup-save"] button{position:relative;aspect-ratio:585/330}.screen-compact[data-frame="app-pickup-save"] img{position:absolute;top:0;left:0;width:100%;height:auto}.parent-guide .screen-compact{max-width:600px}.screen-compact[data-frame="push-menu"] button,.screen-compact[data-frame="push-preferences"] button{position:relative;aspect-ratio:600/410}.screen-compact[data-frame="push-preferences"] button{aspect-ratio:600/480}.screen-compact[data-frame="push-menu"] img,.screen-compact[data-frame="push-preferences"] img{position:absolute;top:0;left:0;width:100%;height:auto}
/* END PARENT GUIDE */\n'''
p.write_text(css,encoding='utf-8')
print('Built the parent home, arrival/departure articles, and trouble page.')
