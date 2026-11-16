"""Apply reviewed name formatting to all six manual articles, without changing screenshots."""
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
DIST=HERE/'dist'
js=(DIST/'app.js').read_text(encoding='utf-8')
js=re.sub(r'// BEGIN UI LABELS\n.*?// END UI LABELS\n','',js,flags=re.S)
helper=(HERE/'ui-labels.js').read_text(encoding='utf-8')
js=js.replace('const manualArticles = {','// BEGIN UI LABELS\n'+helper+'// END UI LABELS\nconst manualArticles = {',1)
for old,new in [
    ('${s.text}','${prose(s.text)}'),('${s.note}','${prose(s.note)}'),
    ('${s.stateNotes[imageState||s.states[0][0]]}','${prose(s.stateNotes[imageState||s.states[0][0]])}'),
    ('<span>${c}</span></li>','<span>${prose(c)}</span></li>'),
    ('<p>${ans}</p>','<p>${prose(ans)}</p>'),
    ('<dd>${a.before}</dd>','<dd>${prose(a.before)}</dd>'),
    ('${c}</label>','${prose(c)}</label>'),
    ('<p>${a[1]}</p>','<p>${prose(a[1])}</p>'),
    ('<div class="notice">${a[2]}</div>','<div class="notice">${prose(a[2])}</div>'),
    ('<div class="path"><strong>開く画面</strong>　${a.path}</div>','${openingPath(a.path)}${uiLegend()}'),
]: js=js.replace(old,new)
# Match the deployed navigation labels, rather than general descriptions of the feature.
js=js.replace("path:'登降園管理 → 園児別・月間修正 → 管理者：まとめて補完'", "path:'出欠一覧 → 園児別・月間修正 → 管理者：まとめて補完'")
js=js.replace("path:'管理者：設定 → 職員管理 → 本人の「認証管理」'", "path:'管理者でログイン → 設定 → 職員管理 → 本人の「認証管理」'")
# Fields previously described without quotes are now named explicitly in the instructions.
for old,new in [('連絡方法：電話か口頭を選びます。','「連絡方法」：電話か口頭を選びます。'),('欠席理由：「病欠」または「私用休み」を選びます。','「欠席理由」：「病欠」または「私用休み」を選びます。'),('連絡内容：誰から、どんな連絡を受けたかを書きます。','「連絡内容」：誰から、どんな連絡を受けたかを書きます。'),('発行理由に「本人からパスワード紛失の申告」','「発行理由」に「本人からパスワード紛失の申告」')]: js=js.replace(old,new)
(DIST/'app.js').write_text(js,encoding='utf-8')
css=(DIST/'style.css').read_text(encoding='utf-8')
css=re.sub(r'/\* BEGIN UI LABELS \*/.*?/\* END UI LABELS \*/\n?','',css,flags=re.S)
css+='\n/* BEGIN UI LABELS */\n'+(HERE/'ui-labels.css').read_text(encoding='utf-8')+'/* END UI LABELS */\n'
(DIST/'style.css').write_text(css,encoding='utf-8')
p=DIST/'index.html';p.write_text(p.read_text(encoding='utf-8').replace('モック v1.2','モック v1.3'),encoding='utf-8')
print('Formatted menu/button/field references in all articles. Images unchanged.')
