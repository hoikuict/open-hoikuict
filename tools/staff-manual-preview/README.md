# 職員向けマニュアルのモック

モックID：`MANUAL-GUIDE-MOCK-001`、現行v1.3、2026-11-03 JST。
仕様記録：[SD-012](../../docs/spec-decisions.md#sd-012)。初回はローカルで作成し、2026-11-03にユーザーの依頼でHPへ試作版を公開した。業務アプリの動作は変更していない。

## 公開版

[スクショ付きガイドの試作版](https://open.hoikuict.net/manual-guide-preview/)を公開中。トップ・マニュアル目次・ナビから進める。[対象範囲と使い方](https://open.hoikuict.net/manual-guide/)も掲載した。

公開コミットは `dc6d92d209939bcd99a32fdfaec6e9d13d0781a4`、配備成功は2026-11-03 04:32:45 JST。公開版の正本は `docs/manual-guide-preview/`。このディレクトリの `dist/` は初回モックの編集用として残す。公開版には読み込み時の画像位置の保持、スマートフォンのヘッダー調整、資産の版番号を追加している。今後の改訂では公開版との差を先に確認し、初回モックからの再生成で公開側の変更を消さないこと。

`publish_assets.py` は初回の公開資産を空の保存先へ書き出すための補助であり、公開版を無条件で上書きする更新ツールではない。公開・照合の資料は `.local-dev/manual-guide-publication-20261103/` に保存した。

## 試す

`職員向けマニュアル・モック.html` をブラウザーで開く。画像・スタイル・検索用データを含む単体ファイルなのでサーバーは不要。既存の公開資料へのリンクを選ぶときだけ、外部サイトを別タブで開く。

編集用は `dist/index.html`、`dist/style.css`、`dist/app.js`。静的プレビューはリポジトリ直下で次を実行する。

```powershell
python -m http.server 8046 --bind 127.0.0.1 --directory tools/staff-manual-preview/dist
```

## 要望と解釈

- 要望：保育園職員にも分かる、スクリーンショット付きの体系的なマニュアルと「こんなときどうする」の状況別マニュアルをモックで試したい。
- 提案：同じ手順へ「業務別の7分野」と「状況・困りごと」から到達する。手順を二重に作らず、対象者・入口・保存時点・完了確認・訂正方法を一つの記事にまとめる。
- 提案した代表例：電話で欠席連絡を受けた、打刻が抜けている、パスワードを忘れた。対象業務の優先順位は未合意。
- 未確定：全編の見せ方、この情報量が現場に合うか、紙マニュアルを正式成果物とするか、全33項目の整備順、全編の公開方法・保守担当。画面付き3例以外を整備済みとは扱わない。

## 2026年11月の取り組み

2026-11-03、ユーザーがスクリーンショットの分かりやすさを評価し、確認と拡張を地道に繰り返すことを今月の取り組みとした。[SD-012の方針合意](../../docs/spec-decisions.md#sd-012)を参照。

進め方の具体案は「手順を一つ選ぶ → 現行画面・操作と照合する → 説明とスクショを直す → ユーザーに確認してもらう → 次の業務へ広げる」。今回の3例を足場に、利用頻度や迷いやすさを見て対象を選ぶ。個別の順序・件数・週ごとの締切は未合意。

各手順の確認日・対象版・残った疑問を記録し、内容確認と公開の状態を分けて管理する。今回の方針合意だけで、モックv1の構成・外観や全手順を確認済み・公開済みとは扱わない。

## 試用して確認すること

1. ホームから「こんなときどうする？」と「業務ごとに、順番に読む」を比較する。
2. 「欠席の電話」「打刻忘れ」「ログインできない」で検索する。存在しない検索語も試す。
3. 打刻・ログインの状況選択から、対応する説明へ進む。
4. 電話の手順を1つずつ読む。画像を拡大し、未入力・一部入力・入力済みを切り替える。
5. 一括補完のエラー例を表示する。全入力項目を縦に展開した画像で、画面の長さも確認する。
6. 「まとめて読む」、前後移動、完了チェック、間違えたときの説明、文字の拡大を試す。
7. スマートフォン幅の目次、画像の拡大・スクロール、文字の読みやすさを確認する。

検索と確認チェックはブラウザー内だけで動く。チェックは再読み込みでリセットされる。整備進捗や職員の習得状況を記録する機能ではない。

## スクリーンショットの根拠

- 2026-11-01の最新配備記録 `docs/deployment-billing-reopen-2026-11-01.md` を確認。基準ソースは `.local-dev/backup-v2-rollout-20261101/source`、対応する配備版 `225ea99d8ca39f773dd9b8e0920bca13854817b5`。後続の請求修正で今回のテンプレートは変更されていない。
- 6テンプレート、関連CSS/JSの8ファイルを作業ルートと改行正規化して照合。すべて一致。ハッシュ・基準は `baseline.json`。
- アプリ本体を起動せず、Jinja2のみでテンプレートを架空データに展開。撮影用の外枠・出欠一覧の要約行は簡略化した。電話連絡の入力3項目と取消理由、月間補完の全入力項目、職員再設定の全入力項目を保持している。
- `dist/screens/` は撮影用画面。番号枠はHTMLで重ねて撮影した。月間補完は入力画面全体を見せるため縦に展開し、その変更を画像内・キャプションに明記。
- `dist/assets/*.jpg` はブラウザーで実際に撮影した12枚。生成画像や手描きで実画面のスクショを装ったものではない。
- 氏名は「見本 あおい」「見本 はなこ」、連絡先は予約済みの `.invalid` ドメイン。実データ・業務DB・送信処理は使用していない。フォーム送信と外部接続はCSPで禁止し、撮影用HTMLの送信先も無効化。
- 実機の最新状態や全ロールの画面は今回未確認。正式公開前に対象の配備版・各画面の権限・園の運用との一致を再確認する。

## 再生成と検証

```powershell
python tools/staff-manual-preview/build_screens.py
python tools/staff-manual-preview/build_catalog.py
node --check tools/staff-manual-preview/dist/app.js
```

撮影用HTMLをブラウザーで開き、同じ名前のJPEGを `dist/assets/` へ保存してから `build_standalone.py` を実行する。`build_screens.py` はローカルの保存済み配備ソースが必要。外部配備版がない環境で最新コードへ自動的にフォールバックはしない。

```powershell
python tools/staff-manual-preview/build_standalone.py
```

動作・表示の確認結果は `verification.json`、出力ハッシュは `artifact-hashes.json`。実際の紙・PDFの印刷レイアウトは未検証。印刷時に全手順を表示するCSSを用意しただけで、正式な紙マニュアルの完成を意味しない。

## v1.1：画像修正（2026-11-03）

パスワード手順1は職員一覧で本人と認証管理を示す画像、手順2は発行理由と再設定コード発行の画像とする。SD-012の修正記録を参照。短いページで `fullPage: true` の撮影中に横幅がつぶれる現象を再現したため、画面全体が収まる1280×720の表示範囲を撮影した。撮影用画面のDOMが正常でも出力画像は崩れる場合があるため、保存したJPEGそのものを開いて確認する。

画像更新時は `dist/app.js` の `screenshotSizes` を実際の画像寸法と一致させ、`publish_assets.py` の参照版も更新する。HTMLを開き直すときは撮影元の更新が読み込まれたかも確認する。公開用UIは `docs/manual-guide-preview/` に出力し、撮影用フォームは公開しない。


## 2026-11-03 登録3種の拡張（v1.2）

ユーザー指定の優先分野は職員登録・園児登録・保護者登録。従来の3例に、職員6手順・園児4手順・在園児の保護者6手順を追加した。画像は18枚追加、計30枚。[SD-014](../../docs/spec-decisions.md#sd-014)を参照。上の初回v1の「優先順位未合意」「3例12枚」は、この範囲について本追記で更新する。

- 原稿：`registration_articles.json`。公開時は `build_registration_articles.py` で `dist/app.js` に差し込む。
- 撮影元：`build_registration_screens.py`。配備版285b67eの保存済みテンプレートを読み、業務アプリ・DBは読み込まない。親の承認画面は登録申請のセクションだけを抜粋し、その旨を画像内と記事に記載。
- 画像：ブラウザーで撮影したJPEGを `dist/assets/` に保存。元ファイルハッシュは `registration-baseline.json`。撮影元の表示に加えて、保存画像を開いて文字・番号枠を確認する。画像更新後に上記記事ビルダーを実行し、実寸を反映する。
- `build_standalone.py` でオフライン版を生成、`publish_assets.py --destination <空の保存先>` で公開候補を生成。版は20261103-v3。公開用34ファイルはUI4ファイルとJPEG30枚だけ。
- 検証：`registration-ui-checks.json` に全6記事の画像読込・手順数・横はみ出し確認を保存。職員の重複エラー、園児の途中入力と画像拡大も確認。チェックの変更はブラウザー内だけ。
- HP更新：クリーンな公開用checkoutから25ファイルだけを `87c07d42d8b8626e437410b4d3919a2e14f6a1b3` としてmainにpush。業務アプリの本番版とmainの機能差を混ぜていない。配備後の根拠は `.local-dev/manual-registration-expansion-20261103/`。

これは現場確認を進めるための試作版の拡張。すべての登録ルート・権限・園の運用や紙印刷を確認済みとは扱わない。


## 2026-11-03 名称の見分け方（v1.3）

[SD-015](../../docs/spec-decisions.md#sd-015)に従い、本文中のメニュー・画面を緑、ボタンを青紫、入力欄を茶色で区別した。種類の文字と枠の形も使う。`ui-labels.js` の辞書に照合済みの名称だけを登録し、本文中のかぎ括弧を `prose()` で表示する。例文・選択値・エラー文は辞書へ含めない。`ui-labels.css` が共通の見せ方。枠は静的なspanで、操作用buttonやリンクとしては生成しない。

登録原稿を編集したら `build_registration_articles.py` → `build_ui_labels.py` → `build_standalone.py` の順に実行する。出版候補は `publish_assets.py` で空のディレクトリへ書き出す。現行はv1.3、資産の参照版20261103-v4。実際のメニュー表示に合わせ、園児の入口は「園児一覧」、登降園の入口は「出欠一覧」とした。

既存の30画像はハッシュが一致し変更なし。名称装飾・HTMLエスケープ・非操作要素、6記事の手順/画像保持、390px幅の長いボタン名を検証した。根拠は `.local-dev/manual-ui-labels-20261103/`。新しい表示の園職員による試用と紙印刷は未確認。


## 2026-11-03 新入園児の2経路（v1.4）

[SD-016](../../docs/spec-decisions.md#sd-016)に従い、在園・卒園・退園した兄弟姉妹がいる家庭と、初めて入園する家庭を別記事にした。各6手順、全8記事・43画像。本文の種類ラベルは付けず、名称だけの色と枠を維持する（SD-015の後続変更）。

`admission_articles.json` が原稿、`build_admission_screens.py` が配備版285b67eのテンプレートを使う撮影用画面。台帳にない兄弟姉妹の記録を推測せず、閲覧許可と家族の紐付けを区別する。新規入園画面は28項目を保持し、保護者2の任意欄を開いて撮影する。フォームの保存・送信は無効化し、実DBは使わない。

画像を保存した後は `build_registration_articles.py` → `build_admission_navigation.py` → `build_ui_labels.py` → `build_standalone.py` の順に再生成する。`publish_assets.py` の参照版は20261103-v6。公開47資産はUI4ファイルとJPEG43枚に限る。既存30画像は変更しない。検証・公開の根拠は `.local-dev/manual-admission-20261103/`。


## 2026-11-03 共通QRを基本の受付へ修正（SD-017）

- 公開試作版v1.5、参照版20261103-v7。9記事・57画像・公開資産61ファイル。
- `qr_article.json` を主経路として追加。`admission_articles.json` の兄弟姉妹経路は既存アカウントを優先し、初回利用者のみQRへ案内。個別招待は補助手順に変更。
- `build_qr_screens.py` は配備保存版285b67eのテンプレートを架空データで描画する。QRには予約済み無効ドメインを使用し、実際の申請に使わない旨も表示する。
- 追加14画面の撮影元・検証は `qr-baseline.json` と `.local-dev/manual-qr-20261103/`。業務DB・メール送信へ接続しない。以前の43JPEGは変更しない。
- 記事の再生成は `build_registration_articles.py` → `build_admission_navigation.py` → `build_ui_labels.py` → `build_qr_reader.py`。最後の処理は複数フォームの見本の状態を手順ごとに分離する。生成後に `build_standalone.py` と `publish_assets.py` を実行する。
- 旧 `#article/child-new-family` は共通QRへ案内。個別招待は `#article/child-new-invite`。保存後の公開検証記録はSD-017へ追記する。


## 2026-11-03 保護者用・登園と降園（SD-018）

- 公開試作版v1.6、参照版20261103-v8。職員9記事・保護者2記事、73JPEG、公開資産77ファイル。
- 保護者用ホームは `#parents`、手順は `#article/parent-arrival` と `#article/parent-departure`、困ったときは `#parent-help`。業務端末の画面は変更しない。
- 原稿 `parent_attendance_articles.json`、保護者用UI `parent-guide.js`、撮影元 `build_parent_attendance_screens.py` と `parent-attendance-baseline.json`。16画面は配備保存版285b67eのテンプレートを使用し、通信・送信・自動遷移を止めて架空データだけを撮影。
- 再生成順は `build_registration_articles.py` → `build_admission_navigation.py` → `build_ui_labels.py` → `build_qr_reader.py` → **`build_parent_guide.py`** → `build_standalone.py`。最後に `publish_assets.py` で公開資産を空の出力先へ書き出す。
- 今回の検証記録は `.local-dev/manual-parent-attendance-20261103/`。新しい画像以外の57JPEGは旧版と同一。共有ルートの非公開資料を公開用チェックアウトへ一括コピーしない。

## 2026-11-03 v1.7 保護者アプリ

SD-019。配備版285b67eの実テンプレート・架空データで29画像を追加。全102画像。ホーム、朝の連絡、欠席、お迎え、お知らせ、アンケート、履歴の7記事。build_parent_app_screens.py → CUA撮影（短い画面は通常撮影。fullPage撮影の後は保存画像を必ず開いて確認）→ build_parent_app_content.py → build_parent_app_ui.py → build_registration_articles.py → build_ui_labels.py → build_qr_reader.py → build_parent_guide.py → build_standalone.py → publish_assets.py。画像・UIのみ公開し、撮影用フォームは公開しない。

## 2026-11-03 v1.7.1 ホーム案内の画像と説明の対応

SD-020。「保護者アプリの画面を見る」だけを5手順へ修正。build_parent_home_review_screens.py で専用5画面を作り、通常スクショを保存する。本文では .screen-focused の表示範囲を使い、拡大は元画像。保護者名と子ども名、押す前と押した後を混同しない。画像の読込成功だけで検証済みとせず、各手順で説明する名称・番号・操作箇所が実際に見えるか確認し、表示中のマニュアルを撮影して一組ずつ照合する。他の17記事の内容、既存102画像は変更しない。

## 2026-11-03 v1.7.2 日次連絡の入口（SD-021）

「朝の体調や連絡を送る」の最初の手順だけを修正。`build_parent_contact_entry_screen.py` で①日付・②園児名・③日次連絡を入力の専用画像を撮影し、本文・画像下の説明と照合する。既存107画像と他の手順は保持。全108画像、公開資産112ファイル。検証は `.local-dev/manual-contact-entry-20261103/`。

## 2026-11-03 v1.7.3 お休みの手順（SD-022）

欠席連絡の入口も確認済みの `app-contact-entry` を参照し、①日付・②園児名・③入力ボタンに対応させる。手順2は私用を選択した例、手順3は私用・病欠と各状態の説明を画像に合わせる。全4手順の対応を確認。他の17記事、108画像は保持。検証は `.local-dev/manual-absence-review-20261103/`。

## 2026-11-03 v1.7.4 お迎えの入口（SD-023）

`build_parent_pickup_entry_screen.py` で①日付・②園児名・③お迎え予定を登録・変更の専用画像を撮影し、本文と照合。全4手順・入力済み/未入力/途中/エラー例も確認。日次連絡とは③の操作先が異なるため画像を使い回さない。他の17記事・既存108画像は保持。全109画像、公開資産113ファイル。根拠は `.local-dev/manual-pickup-review-20261103/`。

## 2026-11-03 v1.8 通知設定（SD-024）

Android（Chrome）7手順・iPhone（ホーム画面のアプリ）8手順を追加。`build_notification_screens.py` は配備テンプレートの通信・許可要求を除去した見本5画面と、実機スクショではないことを明記した公式手順の図5枚を生成します。`notification_content.py` を `build_parent_app_content.py` から読み込みます。既存18記事・109画像は維持し、全20記事・119画像。以後の再構築は content → registration_articles → ui_labels → qr_reader → parent_guide → standalone の順。旧 `build_parent_app_ui.py` は初期移行用で、現在のナビゲーションに上書きしないでください。実機での受信試験は未実施。根拠と公開記録は `.local-dev/manual-notifications-20261103/`。

## 2026-11-03 v1.8.1 画像・説明の訂正（SD-025）

`build_audit_review_screens.py` は保存済み配備版から19画面を生成し、業務通信を行いません。撮影と画像そのものの目視後にJPGへ変換します。内容の訂正は `audit_review_content.py` と `build_audit_core_content.cjs`。再構築順は parent_app_content → registration_articles → audit_core_content → ui_labels → qr_reader → parent_guide → standalone。番号説明は見本の状態ごとに `stateCalls` を使います。全20記事・123画像。通知の定数は保存済み配備版ソースから取得します。公開資産に撮影用フォームを含めません。証跡は `.local-dev/manual-audit-fixes-20261103/`。

## 職員向けの画面別確認版

一般職員向けの原稿は `reviews/staff-home/`。制作中に見つけた問題は、再現できた範囲と改善案を[制作時の記録](../../docs/staff-manual-findings.md)へ追記し、作業報告にも含める。

2026-11-23、利用者の依頼で共通ヘッダーの「HPへ戻る」を削除した。初回出力ツールでも再追加しない。[SD-067](../../docs/spec-decisions.md#sd-067)。
