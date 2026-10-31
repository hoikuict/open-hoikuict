# 職員のQR付き案内の実装・検証

2026-11-01 JST。ユーザーの「いいね、実装しよう」に基づき、[合意したモック](staff-auth-print-proposal-2026-11-01.md) `STAFF-PRINT-MOCK-001` を本体へ実装した。[決定記録 SD-004](spec-decisions.md#sd-004)。同日、ユーザーの配備依頼に基づき実機反映済み。[実機配備記録](deployment-staff-auth-print-2026-11-01.md)を参照。以下の検証欄は実装時点の結果。

## 追加した動作

職員の認証管理から初期設定コード・パスワード再設定コードを発行すると、「QR付き案内を印刷」を表示する。本人へ渡すA4縦の用紙に、園名、対象者、ログインID、6文字のコード、発行日時・期限、QR、URL、本人の操作手順をまとめた。初回設定と再設定の手順は分けている。

QRには設定画面のURLだけを入れる。コードは紙面から本人が入力する。QRは既存のqrcodeライブラリーで生成し、外部QRサービスへ通信しない。印刷・コピー・印刷取消は発行済みの表示を使い、追加発行・メール送信・期限延長・DB更新を行わない。

期限は発行済みトークンの正確なレコードから取得し、日本時間の日時を表示する。表示中の期限切れで印刷・コピーを無効にし、ブラウザー印刷でも期限切れ表示を出す。画面移動時に確認し、履歴から戻った場合も同じコードを再表示しない。再発行・使用・有効期限のサーバー側検証は従来のまま。

## 設定と保持する条件

- 施設URLは既存の `HOIKUICT_STAFF_RECOVERY_BASE_URL`、未指定なら `HOIKUICT_PARENT_REGISTRATION_BASE_URL` を使う。Hostや転送ヘッダーからURLを作らない。未設定・不正なURLならコード発行前に入力画面へエラーを返し、以前のコードや発行監査を変更しない。
- 園名は任意の `HOIKUICT_FACILITY_NAME`。未設定時は `open-hoikuict`。架空の園名を本番の既定値にしない。
- 管理者限定、CSRF、`private, no-store`、6文字・30分・1回限り、再発行時の旧コード失効、初回ID設定、再設定後のセッション失効を維持する。
- 発行理由は管理画面と既存監査にのみ残し、本人用の用紙に載せない。パスワード記入欄を設けない。
- 発行エラー時はログインID・発行理由を保持する。既に資格情報がある職員のログインID欄は従来どおり読取専用。
- 長い氏名・ID・URLは省略せず折り返す。印刷時だけ必要に応じて間隔・文字サイズを調整し、QR自体の印刷寸法は維持する。
- DBスキーマ・データ移行・依存関係の追加なし。

## 検証

- `test_staff_auth_handout.py`、`test_local_staff_auth.py`、`test_staff_auth.py`、`test_staff_password_recovery.py`、`test_spec_20260915.py`：**105件成功**。TestClient関連の既存の非推奨警告2件あり。
- 追加テストは、QRへのURLだけの格納、Host偽装の影響なし、保存済み日時との一致、URLエラー時の既存コード保持、入力保持、管理者権限・CSRF、HTMLエスケープを確認した。
- 実際のルーターに架空の職員とインメモリDBでリクエストし、応答HTMLをブラウザーへ渡した。印刷取消・画面移動の取消、コピー失敗、31分経過、履歴復帰、390pxのスマートフォン幅を確認した。外部通信は全てローカルの応答で置き換えた。想定外リクエスト・書込みリクエスト・JavaScript例外は0件。
- 初回・再設定・長文の3パターンで印刷からPDFを生成し、A4・各1ページを確認。長文は氏名100文字、園名80文字、ID246文字、長い施設URLを併用。Popplerで画像化し、文字・QRの重なりや欠けがないことを確認した。
- 変更したPythonのRuff、差分の空白検査に成功。通常の文書strictビルドは既存ページの目次未登録警告1種類で停止。元の設定を変更せず、その警告だけを情報扱いにした一時設定ではstrictビルドに成功し、リンク・アンカーを含めて確認した。
- 実機プリンター、実際のスマートフォンでのQR読取り、本番での職員発行・メール・ログイン操作は未実施。全体の回帰テストを再実行したものではない。

## 対象・再現資料

- 作業場所：`C:\python\open-hoikuict`、ブランチ `main`、HEAD `ab947ba718a8d2c64da66e2cafb255f01cda14ad`、未コミット差分。既存の他機能の変更は保持。
- 対象：`staff_auth_handout.py`、`routers/staff_auth.py`、`templates/staff_auth/action_code.html`・`authentication.html`、`static/css/staff-auth-handout.css`、`static/js/staff-auth-handout.js`、関連テスト・文書。
- 基準のモックと保存ソースのハッシュは `tools/staff-auth-print-preview/artifact-hashes.json`・`baseline.json` に保持。合意後にモックを上書きしていない。
- ルーター応答の生成：`tools/verify_staff_handout_render.py`、ブラウザー検証：`tools/verify_staff_handout_browser.cjs`。
- 一時の検証資料：`.local-dev/staff-handout-verification/`、pytestログ：`.local-dev/staff-handout-verified-tests.log`。
- 集約記録と実装ファイルのハッシュ：`verification-staff-auth-print-2026-11-01.json`。

配備する場合は、その時点の実機の更新記録・稼働版を確認し、既存の本番機能を保つ版へ取り込む。このmain作業ツリー全体をそのまま本番へ置き換える依頼として扱わない。
