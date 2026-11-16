"""Build the illustrated staff health manual from the captured example screens."""
from html import escape
from pathlib import Path
import re
from PIL import Image

dest = Path(__file__).resolve().parents[4] / "docs/manual-guide-preview/health"
# Each step contains the action, the matching pictures and an optional reminder.
pages = {
    "": ("健康管理一覧", "健康管理で園児を探す",
         "クラスの健康情報を見たいときや、記録を確かめたい園児を探すときに使います。", [
        ("open", "健康管理一覧を開く", [
            "職員メニューの「健康管理」を押します。最初は在園している園児が表示されます。",
            "上の数字は、今の条件で表示している園児の人数です。「対応が必要」は、健診の記録や期限などに確認項目がある園児の人数です。"],
         [("menu", "職員メニューで押す「健康管理」"), ("overview", "健康管理一覧の人数。右上の「印刷」で一覧を印刷できます。")], ""),
        ("filter", "クラスや名前で絞り込む", [
            "「クラス」を選ぶか、「検索」に園児の名前を入れて「絞り込む」を押します。家族名やクラス名でも探せます。",
            "確認項目がある園児だけを見るときは、「アラート」で「対応が必要のみ」を選びます。卒園・退園した園児を探すときは「在籍状況」を変えます。"],
         [("filter", "ひよこ組で「あおい」と入力し、「対応が必要のみ」を選んだ例。右下の「絞り込む」を押します。")], ""),
        ("choose", "園児の行を見て、次の画面を選ぶ", [
            "園児の名前とクラスを確かめます。「健康フラグ」には確認したい項目が並びます。アレルギーや園児の情報をまとめて見るには、その行の「健康サマリー」を押します。",
            "身長・体重の記録や訂正に進むときは、同じ行の「健診記録」を押します。画面が狭いときは表を横に動かすと「操作」が見えます。"],
         [("filtered-row", "「見本 あおい」の行。右端に「健康サマリー」と「健診記録」があります。")],
         "身長と体重を別々の日に記録したときは、「健康サマリー」を開き、それぞれの数字の下の日付を確かめます。"),
        ("empty", "名前が見つからないとき", [
            "「該当する園児がありません。」と出たら、「リセット」を押します。在園のみの一覧に戻るので、必要に応じて在籍状況を選び直すか、名前の一部で探します。"],
         [("empty", "0件の画面。「リセット」は「絞り込む」の左にあります。")], ""),
    ]),
    "summary": ("健康サマリー", "園児ひとりの健康情報を見る",
         "見るだけのときは、この画面で名前、測定日、登録されている内容を確かめます。", [
        ("name", "名前を確かめる", [
            "「健康管理一覧」で、見たい園児の「健康サマリー」を押します。画面の一番上に、園児の名前とクラスが出ます。別の園児を探すときは「健康一覧へ」を押します。"],
         [("summary-links", "「見本 あおい の健康サマリー」の上部。右側に各画面への入口があります。")], ""),
        ("dates", "身長・体重と、測った日を見る", [
            "「最新身長」「最新体重」の数字の下に、それぞれの日付が出ます。「健診アラート」に確認が必要と出たら、「健診記録とグラフ」を開き、「測定一覧」の日付と種別を確かめます。"],
         [("summary-status", "最新身長・最新体重の日付と、「アレルギー」「健診アラート」が並ぶところ。")],
         "「記録は最新です」には「入所時」の記録も含まれます。定期健診を受けた日を調べるときは、「測定一覧」で種別が「定期健診」の行を見ます。"),
        ("next", "知りたい内容の画面を開く", [
            "かかりつけ医や園で気をつけることは「健康プロフィール」を開きます。アレルギーの登録内容と有効期限は「アレルギー情報」で確認できます。詳しく見るときは「管理画面へ」を押します。",
            "健診の記録や測定値の推移を見るときは、上にある「健診記録とグラフ」を押します。"],
         [("summary-allergy", "「アレルギー情報」で対象と期限を確認する例。右上の「管理画面へ」で登録内容を開けます。")], ""),
    ]),
    "profile": ("健康プロフィール", "かかりつけ医や園で気をつけることを記録する",
         "健康サマリーで園児の名前を確かめ、「健康プロフィール」を押します。保存は編集できる職員が行います。", [
        ("basic", "連絡先を書く", [
            "「基本医療情報」に、園で確認した内容を入れます。「かかりつけ医」と「緊急搬送先」には、それぞれに対応する電話番号の欄があります。"],
         [("profile-basic", "「基本医療情報」の「かかりつけ医」に医院の名前を入れた例。")], ""),
        ("flags", "園で共有する項目を選ぶ", [
            "「重点管理項目」で該当する項目にチェックを付けます。欄にないことは「その他の管理事項」に書きます。続く「記録メモ」では、既往歴や服薬、保管場所などを記録できます。"],
         [("profile-flags", "「アレルギーあり」にチェックを付け、「その他の管理事項」を書いた例。")],
         "アレルギーの品目や有効期限は、健康サマリーの「アレルギー管理」で記録します。"),
        ("save", "保存して確かめる", [
            "画面の一番下にある「保存する」を押します。「健康プロフィールを更新しました。」と出たら保存できています。あとから直すときも、同じ欄を書き直して「保存する」を押します。"],
         [("profile-save", "入力欄の一番下にある「保存する」。"), ("profile-saved", "保存すると「健康プロフィールを更新しました。」と表示されます。")],
         "閲覧のみの職員には「保存する」が出ません。内容の変更は編集できる職員に依頼してください。"),
    ]),
    "allergies": ("アレルギー管理", "アレルギーを登録する・直す・解除する",
         "健康サマリーで「アレルギー管理」を押します。園で確認した資料を手元に置き、園児の名前を確かめて入力します。", [
        ("add", "品目と有効期限を入れる", [
            "「新しいアレルギーを追加」で「カテゴリー」「重症度」を確かめ、「アレルゲン名」に品目などの名前を書きます。症状や除去対応は、資料の内容に合わせて入力します。",
            "期限があるときは「有効期限」に日付を入れます。「根拠文書」には園で確認した資料の名前を書けます。"],
         [("allergy-form", "「アレルゲン名」に「卵」を入れた見本。"), ("allergy-date", "「診断日」と「有効期限」は別々の欄です。")], ""),
        ("save", "追加した内容を確かめる", [
            "「追加する」を押し、「登録済みアレルギー」に品目が出たことを確かめます。「アレルゲン名は必須です。」と出たら、品目を入れてもう一度「追加する」を押します。"],
         [("allergy-add", "新しい品目を登録するときの「追加する」。"), ("allergy-active", "登録した「卵」が「有効」と表示された例。品目ごとに編集と解除ができます。"),
          ("allergy-error", "名前が空欄のときに表示されるメッセージ。")],
         "「有効期限」を過ぎても「有効」の登録に残ります。期限の日付と園で確認した資料を見合わせてください。"),
        ("edit", "同じ品目の内容を直す", [
            "「登録済みアレルギー」で、直したい品目の「編集する」を押します。内容を直して「更新する」を押します。変更をやめるときは「キャンセル」を押します。"],
         [("allergy-update", "編集しているときは、右下の表示が「更新する」になります。")], ""),
        ("undo", "解除した品目を確認する", [
            "園で解除が決まったら、品目を確かめて「解除する」を押します。その品目は「解除済み」として登録一覧に残ります。もう一度有効にする必要があるときは、その品目の「再有効化する」を押します。"],
         [("allergy-inactive", "「解除済み」になった品目と「再有効化する」の位置。")], ""),
    ]),
    "checks": ("健診記録とグラフ", "健診を記録する・測定値を訂正する",
         "健康管理一覧で園児の「健診記録」を押します。健康サマリーの「健診記録とグラフ」からも同じ画面に進めます。", [
        ("measure", "種別と測定日を確かめて入力する", [
            "園児の名前を確かめて「健診記録を追加」まで進みます。「種別」を選び、「測定日」に実際に測った日を入れます。身長はcm、体重はkgの欄に数字を入れます。",
            "記録者や所見を残すときは、続きの欄に書きます。"],
         [("record-form", "「定期健診」を選び、測定日・身長・体重を入れた例。")],
         "測定日が空欄のまま送ると「checked_at」を含むエラー画面が出ることがあります。ブラウザーで戻り、測定日とほかの入力を確かめてから保存してください。"),
        ("save", "追加した記録を一覧で見る", [
            "「記録を追加する」を押します。「健康診断記録を追加しました。」と出たら、「測定一覧」で日付と数字を確かめます。"],
         [("record-save", "入力を終えたら「記録を追加する」を押します。"), ("record-list", "「測定一覧」に、11月9日の体重が15.2 kgで追加された例。")], ""),
        ("correct", "入力を間違えたとき", [
            "「測定一覧」で該当する日付の「訂正」を押します。「健診記録を訂正」と出たら、訂正理由を書き、間違えた欄を直します。",
            "「訂正を保存する」を押します。「訂正履歴」で該当する行を押すと、項目ごとに「訂正前」「訂正後」が開きます。保存前にやめるときは「訂正をやめる」を押します。"],
         [("correction", "測定票を確かめ、理由を書いて体重を15.0 kgに直した例。"), ("correction-save", "訂正の最後は「訂正を保存する」を押します。"),
          ("history", "訂正履歴の行を開き、体重が15.2から15.0に変わったことを確かめます。")],
         "「訂正」が見えないときは、編集できる職員に依頼してください。"),
        ("chart", "前の測定値と比べる", [
            "「身長・体重グラフ」で「直近1年」または「在籍期間すべて」を押します。身長と体重は別々のグラフで見ます。",
            "グラフに使うのは「入所時」「定期健診」の記録です。「日常観察」「病後登園」の記録は「測定一覧」で確かめます。"],
         [("chart-period", "「身長・体重グラフ」の右側で表示する期間を選びます。"), ("chart", "期間を「在籍期間すべて」にしたときの「身長推移」と「体重推移」の見本。")], ""),
    ]),
}

def text(value):
    return re.sub(r"「([^」]+)」", r"「<strong>\1</strong>」", escape(value))

used = set()
for slug, (name, title, intro, steps) in pages.items():
    up = "../" if slug else "./"
    chapter = up + "../#chapter/2"
    nav = []
    for key, (label_name, *_) in pages.items():
        current = ' aria-current="page"' if slug == key else ""
        nav.append(f'<a href="{up}{key + "/" if key else ""}"{current}>{label_name}</a>')
    contents = "".join(f'<li><a href="#{key}">{heading}</a></li>' for key,heading,*_ in steps)
    sections = []
    for i, (key, heading, paragraphs, pictures, note) in enumerate(steps,1):
        sections.append(f'<section class="panel" id="{key}"><h2><span class="step">{i}</span>{heading}</h2>')
        sections.extend(f'<p>{text(p)}</p>' for p in paragraphs)
        for photo, caption in pictures:
            used.add(photo)
            url = up + "images/" + photo + ".jpg"
            with Image.open(dest/"images"/(photo+".jpg")) as im:
                width, height = im.size
            sections.append(f'<figure><a href="{url}" aria-label="{escape(caption)}（画像を拡大）"><img width="{width}" height="{height}" src="{url}" alt="{escape(caption)}"></a><figcaption>{escape(caption)}</figcaption></figure>')
        if note:
            sections.append(f'<p class="help">{text(note)}</p>')
        sections.append("</section>")
    bottom = f'<a href="{up}">健康管理一覧の手順へ</a>' if slug else f'<a href="{up}summary/">次へ　健康サマリー</a>'
    html = f'''<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,follow"><title>{title}｜職員用マニュアル</title>
<link rel="stylesheet" href="{up}../plans/style.css"><link rel="stylesheet" href="{up}../plans/forms.css">
</head><body><main id="top">
<header><a href="{chapter}">職員用マニュアル・園児と家庭の記録</a><span>健康管理</span></header>
<nav class="pages" aria-label="健康管理の画面">{' '.join(nav)}</nav>
<h1>{title}</h1><p class="intro">{text(intro)}</p>
<nav class="contents" aria-label="このページの目次"><strong>このページでできること</strong><ul>{contents}</ul></nav>
<p class="shot-note">画面は架空の園児の記録です。画像を押すと大きく見られます。</p>
{chr(10).join(sections)}
<nav class="foot" aria-label="ページ移動">{bottom}<a href="#top">このページの先頭へ</a></nav>
</main></body></html>
'''
    folder = dest/slug
    folder.mkdir(exist_ok=True)
    (folder/'index.html').write_text(html, encoding='utf-8')
assert used == {p.stem for p in (dest/'images').glob('*.jpg')}
print(f"{len(pages)} pages, {len(used)} images")
