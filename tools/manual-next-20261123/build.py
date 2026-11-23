"""Build review-only guides outside docs; nothing here publishes the website."""
from pathlib import Path
from html import escape
import json
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DEST = Path(__file__).parent / 'review'
EVIDENCE = ROOT / '.local-dev/manual-next-20261123'

def photo(name, caption):
    with Image.open(DEST / 'images' / (name + '.jpg')) as im:
        width, height = im.size
    return f'<figure><a class="image-link" href="images/{name}.jpg" aria-label="{escape(caption)}（画像を拡大）"><img src="images/{name}.jpg" width="{width}" height="{height}" alt="{escape(caption)}" loading="lazy"></a><figcaption>{caption}</figcaption></figure>'

def states(items):
    buttons = ''.join(f'<button type="button" data-state="{i}" aria-pressed="{str(i == 0).lower()}">{label}</button>' for i, (label, _, _) in enumerate(items))
    figures = ''.join(f'<div data-state-panel="{i}" {"hidden" if i else ""}>{photo(name, caption)}</div>' for i, (_, name, caption) in enumerate(items))
    return f'<div class="states"><div class="state-controls" role="group" aria-label="画面例を切り替える">{buttons}</div>{figures}</div>'

def section(title, paragraphs, images=(), variants=()):
    body = ''.join(f'<p>{p}</p>' for p in paragraphs)
    body += ''.join(photo(*item) for item in images)
    if variants:
        body += states(variants)
    return title, body

def shell(title, body):
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{title}｜確認用マニュアル</title><link rel="stylesheet" href="review.css"><script src="review.js" defer></script></head>
<body><div class="review-banner">確認用・未公開 <span>画面の人物・記録はすべて架空です。</span></div><main id="top"><header><a href="index.html">今回の確認一覧</a><button id="font-toggle" type="button" aria-pressed="false">文字を大きく</button></header>{body}<footer><a href="index.html">今回の確認一覧へ</a><a href="#top">先頭へ</a></footer></main><dialog id="image-dialog" aria-label="拡大した画面"><button type="button" id="image-close">閉じる</button><img alt=""><p></p></dialog></body></html>'''

def guide(slug, title, audience, intro, path, steps, checks):
    nav = ''.join(f'<li><a href="#step-{i}">{name}</a></li>' for i, (name, _) in enumerate(steps, 1))
    panels = ''.join(f'<section class="panel manual-step" id="step-{i}"><h2><span class="number">{i}</span>{name}</h2>{body}</section>' for i, (name, body) in enumerate(steps, 1))
    checkboxes = ''.join(f'<label><input type="checkbox"> {text}</label>' for text in checks)
    body = f'''<p class="audience">{audience}</p><h1>{title}</h1><p class="intro">{intro}</p><p class="path"><strong>開く順番</strong><br>{path}</p>
<nav class="contents" aria-label="このページの手順"><ol>{nav}</ol></nav><div class="reader"><button type="button" id="reading-toggle" aria-pressed="false">1つずつ読む</button><span>画像を押すと拡大できます。</span></div>
{panels}<div class="step-nav" hidden><button id="previous-step" type="button">前へ</button><span id="step-position" aria-live="polite"></span><button id="next-step" type="button">次へ</button></div>
<section class="panel checklist"><h2>読み終えたら確認すること</h2>{checkboxes}<p class="small">このチェックは読み進めるための目印です。業務記録や公開承認は送信されません。</p></section>'''
    (DEST / (slug + '.html')).write_text(shell(title, body), encoding='utf-8')

guide('attendance-checks', '朝の出欠を確認する・電話連絡を記録する', '職員向け｜出欠の編集ができる方',
      '打刻・保護者からの連絡・職員の確認結果を見比べます。電話で受けた欠席連絡と、職員が確認した出欠は、それぞれ記録します。',
      '職員メニュー → 出欠確認', [
    section('日付とクラスを確かめる', ['「出欠確認」を開き、「日付」と「クラス」を選んで<strong>「表示」</strong>を押します。「表示形態」は全園児／クラス別、「絞り込み」は未確認・アラームありなどから選べます。',
        '園児名、登園／降園の時刻、保護者連絡を見ます。打刻の「在園」と、職員が記録する「出席」は別の情報です。'], [('attendance-entry', '出欠確認の全体。日付・表示形態・絞り込み・クラスと、3人の架空の園児。')]),
    section('実際の出欠を確かめて記録する', ['園児本人の様子や職員の記録を確認し、その園児の<strong>「出席」「私用休み」「病欠」「不明」</strong>を選びます。',
        '<strong>初回はボタンを押した時点で保存されます。</strong>名前を取り違えないよう、押す前に確認します。「詳細」で確認者・確認時刻・操作履歴を見ます。'], [('attendance-present', '初回の出席を保存した後。目視確認の職員名・時刻と操作履歴を表示。')]),
    section('確認済みの出欠を変更する', ['別の出欠へ変更すると理由の画面が開きます。園児名と変更先を見直し、理由を入れて<strong>「記録する」</strong>を押します。「戻る」は変更を保存しません。',
        '見本は「私用休み」から「病欠」への変更です。「不明」へ変更するときには保護者への確認通知を選ぶ欄もあります。園の運用に沿って必要な場合に選びます。'], [('attendance-change', '出欠の変更理由を入力した画面。「記録する」で保存、「戻る」で中止。')]),
    section('アラームの理由を確認する', ['色の付いた行やアラーム表示があるときは、その園児の<strong>「詳細」</strong>を開きます。「保護者連絡」「目視確認」「アラーム理由」を見比べます。',
        '「連絡なし」と分かっていても、欠席や打刻を推測で変更しません。見本は職員が「私用休み」と記録した一方、保護者連絡の記録がない例です。'], [('attendance-alarm', '保護者連絡がない場合のアラームと、確認結果・履歴。')]),
    section('電話・口頭で受けた欠席連絡を保存する', ['同じ詳細画面の<strong>「電話・口頭連絡の受付」</strong>で「連絡方法」「欠席理由」「連絡内容」を入力します。誰から、どのような連絡を受けたかを残し、「連絡受付を記録」を押します。',
        '保存後に詳細を開き、受付内容・職員・日時を確認します。同じ日・同じ欠席理由なら「保護者連絡なし」のアラームは解消します。打刻や目視確認は変わらず、ほかの不一致は残ります。'], variants=[('入力例', 'attendance-phone-input', '電話で病欠連絡を受けた入力例。連絡方法・欠席理由・連絡内容の全項目。'), ('保存後', 'attendance-phone-saved', '電話受付を保存した後。アラームの解消と受付履歴を確認。')]),
    section('電話受付を間違えたときは理由を付けて取り消す', ['誤って受け付けた記録の「取消理由」に、日付や園児の取り違えなどの理由を入力し、<strong>「受付を取り消す」</strong>を押します。',
        '取消も履歴に残り、アラームが再判定されます。これは電話・口頭の受付記録の取消です。登園・降園の時刻を直す場合は、<a href="attendance-times.html">打刻の補記・修正・取消</a>へ進みます。'], variants=[('取消前', 'attendance-phone-cancel', '電話受付の取消理由を入力した状態。'), ('取消後', 'attendance-phone-cancelled', '受付と取消の履歴が残り、保護者連絡なしのアラームが再表示された状態。')])
], ['対象日と園児を確認できた', '初回と変更時の保存タイミングが分かった', '電話受付と目視確認・打刻を区別できた'])

guide('attendance-times', '登降園の時刻を補記・修正・取消する', '職員向け｜登降園記録の編集ができる方',
      '打刻忘れは実際の時刻を補い、時刻の誤りは理由を付けて修正します。別の園児を打刻したときなどは、取り消す範囲を確かめます。',
      '職員メニュー → 登降園管理 → 園児別・月間修正', [
    section('登降園管理から月間修正を開く', ['「登降園管理」で園児名と日付を確認し、<strong>「園児別・月間修正」</strong>を押します。',
        'お迎え予定は実際の打刻時刻とは別です。予定時刻を実績として入力せず、保護者や職員の記録で実際の時刻を確認します。'], [('punch-list', '登降園管理の全体。「園児別・月間修正」の入口と日別の打刻。')]),
    section('対象月・クラス・園児から、その日を開く', ['「対象月」「クラス」「園児」を選んで<strong>「表示する」</strong>を押します。「打刻漏れ・要確認だけ表示」で絞り込めます。',
        '対象日の<strong>「補記する」または「詳細・修正」</strong>を押します。出欠未確認の表示だけで、その日に登園していたとは判断しません。'], [('punch-month', '月間修正で打刻漏れ・要確認だけを表示した例。')]),
    section('確認した時刻と理由を入力する', ['「登園時刻」「降園時刻」「降園の日付」を確認し、必要な時刻を入力します。補記・修正理由は必須です。翌日の降園は、必要な場合だけ「翌日（03:00まで）」を選びます。',
        '見本では登園を08:30から08:25へ訂正し、早退時の降園09:20を補います。<strong>「この日の記録を保存」</strong>で確定します。「変更せず閉じる」や右上の×では保存されません。',
        '降園が登園より前などのエラーが出たときは、日付・時刻を確認して直します。確定・調整・対象外・請求転送済みの料金がある日は編集できません。'], variants=[('開いた直後', 'punch-empty', '登園だけ保存されている日。時刻・降園の日付・理由と履歴の全体。'), ('入力例', 'punch-filled', '登園の訂正と早退時の降園を入力した保存前の例。'), ('時刻のエラー', 'punch-error', '降園時刻が登園より早い場合のエラー。入力内容を直してから保存する。')]),
    section('保存後に開き直して確かめる', ['同じ日の「詳細・修正」をもう一度開き、保存済みの時刻と<strong>「補記・修正・取消の履歴」</strong>を確認します。職員名、理由、変更前後が残ります。',
        '保存時に未確定の延長料金を再計算します。出欠確認の結果や、お迎え予定を変更する操作ではありません。'], [('punch-saved', '保存後に開き直した例。登園08:25・降園09:20と変更理由・履歴。')]),
    section('誤った打刻を取り消す', ['「打刻の取消・履歴を開く」から対象の園児・日付・時刻を見ます。登降園管理の「打刻の取消・履歴」や出欠確認の「誤打刻を取り消す」からも開けます。',
        '「取り消す記録」で<strong>「降園打刻のみ（登園は残す）」</strong>または<strong>「登園・降園とお迎え予定を取り消す」</strong>を選び、取消理由を入れます。取消範囲を見直して「確認した打刻を取り消す」を押します。このボタンで取消が確定します。',
        '中止するときは、保存ボタンを押さず上の戻るリンクで戻ります。料金が確定・調整・対象外・請求転送済みなら取消できません。'], variants=[('開いた直後', 'punch-cancel-empty', '打刻の取消画面。対象の園児・日付と取消範囲を確認。'), ('取消前', 'punch-cancel-filled', '誤って押した降園だけを取り消す例。登園は残す選択と理由。')]),
    section('取消後の時刻と履歴を確認する', ['見本は降園だけを取り消したため、登園08:45が残り、降園が「未打刻」になります。元の打刻・職員・理由は履歴で確認できます。',
        '取消前の未確定料金は取り消され、次の降園で再計算されます。出欠確認に別のアラームが残っていれば、その理由も確かめます。複数日の空欄をまとめて補う操作は、管理者用の既存手順で扱います。'], [('punch-cancelled', '降園だけを取り消した後。登園は残り、取消の理由と元の打刻が履歴に残る。')])
], ['予定ではなく実際の時刻を確認できた', '保存前の中止と保存後の履歴確認が分かった', '降園だけの取消と全体の取消を区別できた'])

guide('emergency-parent', 'いつもの緊急連絡順を登録する・その日だけ変える', '保護者向け',
      '園から先に電話してほしい順番を、お子さまごとに登録します。いつもの順番と、その日だけの変更を使い分けます。',
      '保護者ホーム → メニュー → 緊急時の連絡先', [
    section('メニューからお子さまを選ぶ', ['保護者ホームで<strong>「メニュー」→「緊急時の連絡先」</strong>を開きます。お子さまが複数いる場合は、登録するお子さまを選びます。一人の場合は直接入力画面が開きます。'], [('emergency-home', '保護者ホームのメニューを開いた状態。「緊急時の連絡先」を選ぶ。'), ('emergency-choose', '兄弟姉妹がいる場合のお子さま選択。')]),
    section('連絡先と、電話してほしい順番を確認する', ['見出しのお子さまの名前を確認します。「連絡先の名前」と「電話番号」を確かめ、<strong>「上へ」「下へ」</strong>で順番を変えます。',
        '初めて開いたときは、台帳の電話番号が候補として入る場合があります。そのまま確定せず、ご家庭で使う番号と順番を確認してください。'], [('emergency-initial', '初回表示の全入力欄。まだ登録していない連絡順に台帳の候補が入っている例。')]),
    section('必要な連絡先を追加し、保存する', ['<strong>「連絡先を追加」</strong>で行を増やし、名前と電話番号を両方入れます。不要な行は「外す」で除きます。「台帳の電話番号から選ぶ」も利用できます。',
        '名前・番号・順番を見直して<strong>「いつもの連絡順を保存」</strong>を押します。並べ替えや行の追加だけでは保存されません。入力エラーが出たときは該当の行を直して、もう一度保存します。'], variants=[('入力途中', 'emergency-partial', '祖母の携帯を追加し、電話番号をまだ入力していない状態。'), ('入力例', 'emergency-filled', '母の携帯を先頭に並べ、祖母の番号を追加した保存前の例。'), ('入力エラー', 'emergency-error', '追加した5番目の電話番号が未入力のため、保存されていない例。')]),
    section('保存完了と、お子さまごとの順番を確かめる', ['<strong>「いつもの連絡順を保存しました。」</strong>と表示されたことを確認します。開き直しても番号と順番が残ります。',
        '兄弟姉妹へ自動的に同じ順番は入りません。別のお子さまも必要に応じて登録します。保存した順番は、そのお子さまに紐付く保護者と園で確認できます。'], [('emergency-saved', '通常の連絡順の保存完了。'), ('emergency-sibling', '別のお子さまの初回表示。先ほどの並べ替えや追加は引き継がれない。')]),
    section('その日だけ変えるときは日次連絡で入力する', ['ホームで対象の日付を選び、お子さまの「日次連絡を入力」または「日次連絡を編集」を開きます。緊急連絡先の<strong>「今日は変更する」</strong>を選び、その日の順番に並べます。',
        '見本は、その日だけ祖母の携帯を先頭にした例です。日次連絡のほかの項目も確認し、画面下の<strong>「保存する」</strong>で保存します。通常の順番、ほかの日、兄弟姉妹の順番は変わりません。'], variants=[('変更の入力例', 'emergency-day-change', '日次連絡の緊急連絡先欄だけを抜粋。その日だけ祖母を先頭にする。'), ('保存後', 'emergency-day-saved', '保存後に日次連絡を開き直した状態。「この日は連絡順が変わっています」と表示。')]),
    section('その日の変更を元に戻す', ['日次連絡を開き直し、<strong>「この日の連絡先を変更」→「いつもの順番に戻す」</strong>を選び、画面下の「保存する」を押します。選んだだけでは保存されません。',
        '「変更をやめる」は、入力中の変更をやめるためのボタンです。すでに保存済みの回答を取り消す操作ではありません。',
        'いつもの順番を後から変更しても、すでに登録したその日の回答は自動で変わりません。当日も変える場合は、その日の日次連絡を確認します。'], [('emergency-day-return', '日次連絡で「いつもの順番に戻す」を選択した保存前の状態。')])
], ['お子さまごとに登録することが分かった', '通常の登録と、その日だけの変更を区別できた', '変更を選んだ後に保存する操作を確認できた'])

guide('emergency-staff', '緊急連絡先の変更を口頭で受け付ける', '職員向け｜園児情報の編集ができる方',
      '電話や口頭で伝えられた緊急連絡順を、職員が記録します。その日だけか、今後も使ういつもの順番かを、伝えてくれた方に確認します。',
      '園児一覧 → 対象の園児の詳細 → 家族プロフィール → 口頭の連絡を記録', [
    section('園児を選び、今日の連絡先を確認する', ['園児一覧から対象の園児の詳細を開き、「家族プロフィール」の<strong>「今日の緊急連絡先」</strong>を確認します。「口頭の連絡を記録」を押します。',
        'きょうだいがいる場合も園児一人ずつ扱います。欠席連絡を受けたときは、これとは別に<a href="attendance-checks.html">出欠確認の電話・口頭連絡受付</a>で記録します。'], [('oral-entry', '園児詳細の家族プロフィール。「口頭の連絡を記録」が入口。')]),
    section('対象日と、伝えてくれた方を入力する', ['その日だけなら<strong>「その日だけ」</strong>を選びます。別の日は「別の日を開く」で日付を入れ、「表示」を押します。見出しの園児名と日付を確認してください。',
        '<strong>「伝えてくれた方」</strong>に「お母さま」などを記入します。連絡先の名前・電話番号・順番を確認し、「上へ」「下へ」「外す」や「この日だけの連絡先を追加」を使って整えます。'], variants=[('開いた直後', 'oral-empty', '口頭受付の全体。対象日・伝えてくれた方・全連絡先・保存とキャンセル。'), ('入力例', 'oral-day-filled', 'その日だけ祖母の携帯を先頭にし、お母さまからの連絡として記録する例。')]),
    section('保存する前に範囲を見直す', ['確認した内容で<strong>「この日だけの連絡順を保存」</strong>を押します。「キャンセル」では入力内容を保存せず園児詳細に戻ります。',
        '保存すると、この園児に紐付く保護者にも連絡順が表示されます。口頭受付だけで、保護者の日次連絡を提出済みにはしません。'], [('oral-parent-view', '保存後に保護者の日次連絡で見える表示。「園で口頭受付」と記録される。')]),
    section('園児詳細と履歴で保存結果を確認する', ['「今日の緊急連絡先」で先に連絡する相手を確認します。<strong>「連絡順の変更履歴」</strong>を開くと、内容・受付職員・伝えてくれた方・日時を確認できます。',
        '間違いに気付いたときは、正しい園児と日付を選んで口頭受付を開き直し、確認した順番を保存します。保存前の「キャンセル」と、保存済みの記録の修正を区別します。'], [('oral-saved', 'その日の連絡順と変更履歴。過去の回答も残る。')]),
    section('いつもの順番を変える場合', ['今後も使う番号や順番の変更なら<strong>「いつもの連絡順」</strong>へ切り替えます。「伝えてくれた方」と連絡先を入力し、「いつもの連絡順を保存」を押します。',
        '今日の回答がすでに届いている場合、通常の順番を変えても今日の回答は変わりません。今日も変更する場合は「その日だけ」で記録します。',
        'エラーが出たら入力を見直します。ほかの方が先に変更した案内が出た場合は、「最新の連絡順を確認する」で開き直し、最新の内容を確かめてから入力します。'], variants=[('通常の順番', 'oral-usual', 'いつもの連絡順の入力画面。今日の回答がすでにある場合の案内。'), ('番号のエラー', 'oral-error', '電話番号が短すぎる場合のエラー。入力は保持される。')]),
    section('閲覧のみの方が確認する場合', ['閲覧のみの職員も登録された連絡順と履歴を確認できますが、「口頭の連絡を記録」は表示されません。変更が必要なときは、編集できる職員へ依頼します。'], [('oral-view-only', '閲覧のみの職員が見る家族プロフィール。口頭受付のボタンは表示されない。')])
], ['その日だけと通常の変更を区別できた', '伝えてくれた方・対象日・園児を確認できた', '保存後の表示と履歴を確認できた'])

queue = [
 ('M19・M27', '児童票の入力・確認依頼／職員ホームと要確認', '既存の画面付き確認原稿を現行版と再照合して提示'),
 ('M12', 'お知らせ・アンケート', '職員の作成・公開・回答集計を新規制作'),
 ('M14', '園児・家庭・保護者の台帳編集', '既存登録の修正・保存・履歴を補完'),
 ('M18', '子どもの観察記録', '記録・訂正・無効化・振返りを新規制作'),
 ('M24', 'カレンダー', '表示切替・予定とカレンダーの作成を新規制作'),
 ('M25', '職員ルーム', 'ルームの作成・共有・日常の投稿を補完'),
 ('M26', '文書の確認依頼', '添付・提出・判定・再提出を新規制作'),
 ('M28', '保育認定・保育必要量', '期間別登録・変更・重複時の確認を新規制作'),
 ('M29', '延長保育料金', '設定・月次確認・再計算・確定・調整を新規制作'),
 ('M30', '請求への転送', '延長料金からの転送・再転送を補完'),
 ('M07', '保護者の利用停止・再開', '停止・再開・再設定付き再開を新規制作'),
 ('M15', '園児・保護者の写真', '登録・差替え・削除・承認を新規制作'),
 ('M04', '初期台帳のExcel登録', '準備・取込・結果確認・取消を新規制作'),
 ('M16', '家庭・園児CSVの取り込み', '列の準備・比較・登録を新規制作'),
 ('M01・M02', '導入・Windowsの利用開始', '配布版の起動と園内LAN・園外利用を画面付きにする'),
 ('M03', 'TrueNASへの導入', '検証環境で導入・起動・復旧の画面を確認して制作'),
 ('M31・M32', 'バックアップ・復元', '取得・確認・復元前退避・復元後確認を検証環境で制作'),
 ('M33', '毎日の点検・障害時の対応', '現行構成の確認箇所と一次対応を画面付きにする')
]
(EVIDENCE / 'queue.json').write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding='utf-8')
cards = [
 ('attendance-checks', '1', '朝の出欠を確認する・電話連絡を記録する', '職員向け／M08', '初回確認、理由付き変更、電話受付、受付取消'),
 ('attendance-times', '2', '登降園の時刻を補記・修正・取消する', '職員向け／M08', '時刻の補記・修正、保存後の確認、誤打刻の取消'),
 ('emergency-parent', '3', 'いつもの緊急連絡順を登録する・その日だけ変える', '保護者向け／M37', '通常の登録、並べ替え、その日だけの変更と戻し方'),
 ('emergency-staff', '4', '緊急連絡先の変更を口頭で受け付ける', '職員向け／M37', '対象日・伝えた方、通常と当日の使い分け、履歴')
]
card_html = ''.join(f'<a class="card" href="{slug}.html"><span class="audience">{audience}</span><h2><span class="number">{n}</span>{title}</h2><p>{detail}</p><span class="open">手順を確認する →</span></a>' for slug,n,title,audience,detail in cards)
queue_html = ''.join(f'<tr><td>{i}</td><td>{ids}</td><td>{title}</td><td>{detail}</td></tr>' for i,(ids,title,detail) in enumerate(queue,2))
body = f'''<p class="audience">スクショ付きマニュアル整備／第1回</p><h1>今回確認する4つの手順</h1><p class="intro">出欠・登降園の確認と、園児別の緊急連絡順を追加しました。まずこの4本を確認し、了承後にHPへ公開します。</p>
<p class="path"><strong>進め方</strong><br>確認用原稿を制作 → 内容を試読・修正 → 了承後にHPへ公開 → 次の項目を制作</p>
<div class="cards">{card_html}</div><section class="panel"><h2>今回、見ていただきたいこと</h2><ul><li>初めて使う職員・保護者が、入口から保存後の確認まで進めるか。</li><li>園で使う言い方と、説明の詳しさが合っているか。</li><li>通常の変更・その日だけの変更・保存前の中止を区別できるか。</li></ul><p>画像を押すと拡大できます。各手順の「1つずつ読む」と、入力途中・保存後・エラーの画面切替も試せます。</p></section>
<section class="panel"><h2>次の制作・確認予定</h2><p>日常業務、台帳、料金、導入・運用の順に進めます。「公開済み」には文字のみの資料もあるため、画面付き手順が足りない操作を単位にしています。</p><div class="table-wrap"><table><thead><tr><th>順</th><th>管理番号</th><th>対象</th><th>進める内容</th></tr></thead><tbody>{queue_html}</tbody></table></div></section>
<section class="panel"><h2>既存手順に残る確認</h2><p>健康管理・指導計画の印刷、複数職員の同時操作、共用端末の通信断からの復帰、スマートフォンの通知到着は、画面付き原稿の制作とは別に確認を残しています。今回の4本だけで全機能の確認完了にはしません。</p><p class="small">2026年11月23日作成。今回はローカル確認版です。HPの公開内容と公開状況は変更していません。</p></section>'''
(DEST / 'index.html').write_text(shell('今回確認する4つの手順', body), encoding='utf-8')
print(json.dumps({'guides':4,'index':str(DEST / 'index.html'),'queue_groups':len(queue)}, ensure_ascii=False))
