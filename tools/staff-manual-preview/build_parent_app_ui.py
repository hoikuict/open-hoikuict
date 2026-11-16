"""Extend the shared parent navigation and update publication metadata."""
from pathlib import Path
HERE=Path(__file__).resolve().parent
p=HERE/'parent-guide.js';js=p.read_text(encoding='utf-8')
start=js.index('function parentHome()');end=js.index('function parentScreenshot',start)
js=js[:start]+'''function parentHome(){return `<p class="eyebrow">保護者の方へ</p><h1>保護者のための使い方ガイド</h1><p class="lead">やりたいことを選んでください。<br>短い文と、画面の見本でご案内します。</p><section class="parent-tip"><h2>スマートフォンのアプリ</h2><p>朝の連絡、お休み、お迎え予定。<br>お知らせや、園からの返信を見るときはこちら。</p><a class="parent-app-start" href="#parent-app">保護者アプリの使い方を見る →</a></section><h2>園の受付画面</h2><p>園に着いたときと、お迎えのときに操作します。</p><div class="parent-cards">${['parent-arrival','parent-departure'].map(card).join('')}</div><a class="parent-help-link" href="#parent-help"><strong>受付で間違えた・うまくいかない →</strong><span>押し忘れ、名前が見つからない、画面が進まないとき</span></a><p class="source-note">ここは使い方を読むページです。実際の連絡や受付は、園のアプリ・受付画面で行ってください。画面の名前・日付・時刻は例です。</p>`;}
function parentAppHome(){return `<div class="breadcrumb"><a href="#parents">保護者用のホーム</a><span>›</span><span>保護者アプリ</span></div><p class="eyebrow">スマートフォンのアプリ</p><h1>保護者アプリの使い方</h1><p class="lead">「これをしたい」から選んでください。<br>1つずつ、画面を見ながら進められます。</p><div class="parent-cards">${parentAppIds.map(card).join('')}</div><div class="parent-tip"><h2>登園・降園の受付はこちら</h2><p>アプリで連絡を送っても、登園・降園の受付は終わりません。園にある受付画面も操作してください。</p><a href="#article/parent-arrival">園に着いたとき →</a><br><a href="#article/parent-departure">お迎えのとき →</a></div><p class="source-note">今回は、ホームの見方と毎日の連絡を案内しています。登録情報や通知設定などの詳しい手順は、画面を確認しながら追加します。</p>`;}
''' +js[end:]
js=js.replace('使い方を読んだあとの確認です。このページでは登園・降園を記録できません。','使い方を読んだあとの確認です。このページから園へ連絡を送ったり、受付をしたりすることはできません。')
js=js.replace('<a class="parent-help-link" href="#parent-help"><strong>間違えた・画面が進まないときはこちら →</strong></a>', '${a.section===\'app\'?\'<a class="parent-help-link" href="#parent-app"><strong>ほかのアプリの使い方を見る →</strong></a>\':\'<a class="parent-help-link" href="#parent-help"><strong>間違えた・画面が進まないときはこちら →</strong></a>\'}')
js=js.replace('完了画面は、読めるように止めて撮影しました。','長い画面は、手順に合わせて上・途中・下の部分を撮影しています。画面全体の見本もあります。受付の完了画面は、読めるように止めて撮影しました。')
p.write_text(js,encoding='utf-8')
p=HERE/'build_registration_articles.py';js=p.read_text(encoding='utf-8')
if "parent_app_articles.json" not in js:js=js.replace("articles['child']['title']", "articles.update(json.loads((HERE/'parent_app_articles.json').read_text(encoding='utf-8')))\narticles['child']['title']",1)
js=js.replace('len(sizes)==73','len(sizes)==102').replace('Built 11 articles and 73 screenshots total.','Built 18 articles and 102 screenshots total.')
p.write_text(js,encoding='utf-8')
p=HERE/'build_parent_guide.py';js=p.read_text(encoding='utf-8')
if "case 'parent-app'" not in js:js=js.replace("p.write_text(js,encoding='utf-8')",'''js=js.replace("case 'parents':html=parentHome();break;", "case 'parents':html=parentHome();break;case 'parent-app':html=parentAppHome();break;") if "case 'parent-app'" not in js else js
js=js.replace('園に着いたとき・お迎えのときの使い方','保護者アプリと、登園・降園の使い方').replace('保護者向け2例','保護者向け9例')
p.write_text(js,encoding='utf-8')''',1)
js=js.replace("html=html.replace('画面付きの手順：共通QR", "html=html.replace('モック v1.6','モック v1.7').replace('保護者向け2例','保護者向け9例')\nhtml=html.replace('画面付きの手順：共通QR",1) if "'モック v1.7'" not in js else js
js=js.replace('.parent-entry{display:flex;', '.parent-app-start{display:inline-block;background:#236b55;color:white;border-radius:8px;padding:13px 18px;text-decoration:none;font-weight:700}.parent-entry{display:flex;',1) if '.parent-app-start{' not in js else js
p.write_text(js,encoding='utf-8')
for filename in ['build_standalone.py','publish_assets.py']:
 p=HERE/filename;js=p.read_text(encoding='utf-8').replace('== 73','== 102').replace('Expected 73 screenshots','Expected 102 screenshots').replace('73 embedded screenshots','102 embedded screenshots').replace('== 77','== 106').replace('20261103-v8','20261103-v9').replace('v1.6</span>','v1.7</span>').replace('保育園職員向けのスクリーンショット付きマニュアル','保護者・保育園職員向けのスクリーンショット付きマニュアル');p.write_text(js,encoding='utf-8')
p=HERE/'ui-labels.js';js=p.read_text(encoding='utf-8')
if "'保護者ホーム'" not in js:js=js.replace("['menu',[", "['menu',['保護者ホーム','メニュー','日次連絡履歴','お知らせ','アンケート','子ども情報変更申請','登録情報','通知設定','パスワード変更',",1).replace("['button',[", "['button',['日付を変更','日次連絡を入力','日次連絡を編集','お迎え予定を登録・変更','未読・未回答','保存する','予定を保存','ホームへ戻る','戻る','表示','ダウンロード','出席・欠席を連絡する','回答する','回答を編集','内容を編集','履歴を見る','返信あり',",1).replace("['field',[", "['field',['出席','欠席','私用休み','病欠','体調メモ','園への連絡事項','現在の体温','症状','備考','性状',",1)
p.write_text(js,encoding='utf-8')
print('Updated parent navigation and metadata for v1.7.')
