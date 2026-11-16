# 内容一覧の未送信から返信記入欄へ移動する本番更新

状態：本番反映完了。2026-09-28 08:37:38 JSTに公開再開。08:37:49に稼働版を照合し、08:38:02に公開HTTPSと配信ファイルの一致を確認した。

## 承認と変更

- ユーザーはモックを「これでいい。」と承認し、実装確認後に「本番に反映しよう」と依頼した。
- 対象：`https://hikarinomori.hoikuict.net/daily-contacts/` の内容一覧。
- 未送信3状態から該当する園児・日付の返信フォームへ直接移動する。日付・クラス・表示順を引き継ぎ、一覧のスクロール位置も保持。
- 閲覧のみの職員と返信済みは従来の状態表示。入力・保存・公開処理とDBスキーマは変更しない。

## 基準と更新版

- SSHで確認した稼働版：`f79846c31e361da6fed3f02f13798c4e4720a534`。
- 基準イメージ：`sha256:fd03c70bc0dfda27d4cb6292a2499e04e711b4de057ba03c955e54c0e467de61`。
- 基準deployment.json SHA256：`1feadaccbd59f1800ceda4ebffe121105cd793dc2cec4ae3e83842a2a999ac1a`。
- Compose SHA256：`f3cddda31ac5c20b7b7633fa6427e3cce28e21de02d0cb87c7d3d6812a611817`。
- 更新版：`4581393839d40d0e4eddbf71b9b4b28a7ba461ea`。
- ブランチ：`codex/contact-reply-jump-20260928-production`。
- 本番用作業コピー：`.local-dev/truenas-monthly-export-20260927/source` を継続使用。
- 425ファイルの基準一致を確認し、今回の4ファイルだけを変更した。開発側の他の変更は含めない。

変更ファイル：

- `templates/daily_contacts/_content_table.html`
- `templates/daily_contacts/detail.html`
- `static/css/daily-contact-list.css`
- `static/css/daily-contact-reply.css`

## 実施済みの準備

- 開発用ソースの53テストとブラウザ操作を確認済み。
- 本番用コードの既存209テストが成功。失敗・スキップなし。
- 配備手順の10テストがローカルと実機で成功。
- 表示検査を架空DBで実行し、48一覧画面・20詳細画面で成功。編集権限によるリンク表示、リンク56件の園児・日付・条件・遷移先、返信フォームの全5項目を確認。書込み0。
- 26資材ファイル、約8.5MBを転送し、すべてのハッシュとPython構文を照合済み。Compose保持、文例コーパスや実データの転送なし。
- 実機の `sudo -n true` は `a password is required`。起動にはユーザーによるsudo認証が必要。

## 実行済みの管理者起動（再実行不要）

ユーザーがsudo認証を実行済み。`status.json` は `complete`。同じコマンドを再実行しない。

```sh
sudo python3 /home/truenas_admin/contact-reply-jump-20260928-4581393/start-systemd.py
```

systemd：`hoikuict-contact-reply-jump-20260928-4581393`。
同フォルダーの `status.json` と稼働中の `deployment.json` の一致を確認済み。

起動後、ネットワークを切った候補イメージで209テスト・復元試験、本番DBコピーの表示検査、既存バックアップとの互換性を確認する。すべて成功したら公開を一時停止してDB退避とZFSスナップショットを作成し、更新版へ切替。業務データ・添付・設定・バックアップ予定を検査して公開を再開する。

切替後は稼働版の記録、公開HTTPSの応答、実際のHTMLが参照する一覧JS/CSS・返信CSSのバイト一致を確認する。

## 証跡

`.local-dev/contact-reply-jump-20260928/` に保存。

- `live-before.json`、`prepared.json`、`production-tests.xml`
- `prepare_source.py`、`prepare_bundle.py`、`verify-parent-contact-live.py`
- `bundle/UPDATE.json`、`bundle/SHA256SUMS`、`transfer-verification.txt`
- `deploy_capture_completion.py`、`deploy_capture_public.py`

## 本番の確認結果

- 稼働版：`4581393839d40d0e4eddbf71b9b4b28a7ba461ea`。
- イメージ：`sha256:388d12fc7b97827352bc45349e71ee4a9fe3c1b62d836982384fa665a903d808`。
- 更新後deployment.json SHA256：`22a4a4a562ab844b2da20f69de67d5d8b53891de3a99d911246b4951b9049b0a`。
- 実機209テスト成功。失敗・スキップ・収集エラー0。復元試験と既存バックアップ10件の互換性も確認。
- 稼働版の実データで在園98名、84一覧画面・196詳細画面を読み取り専用で描画。条件の組合せを含む返信リンク784件、編集・閲覧権限、日付・クラス・表示順と返信フォームの全5入力項目を確認。検査による書込み0。
- 公開HTTPSのhealthz正常。未認証の一覧は職員ログインへ303遷移。
- 一覧JS `/static/js/daily-contact-list.js?v=475cfe4f772c203b`、一覧CSS `/static/css/daily-contact-list.css?v=1ed3d256ac2f299b`、返信CSS `/static/css/daily-contact-reply.css?v=67fa94d9f2dda576` を実際のHTMLから取得し、公開配信内容が配備資材とバイト一致。
- 月案のJS/CSSも一致。月案・既存帳票・文例検索・AIの架空条件による動作確認も成功。月案検査の `contexts` は旧検査の変数再利用により担当人数を示すため、表示条件数の根拠には使用しない。
- アプリ・公開トンネル・backup-worker・restore-worker正常。既存データ・添付13ファイル・Compose・毎日02:00のバックアップ予定を保持。
- 退避：`/mnt/main/open-hoikuict-pilot/backups/before-contact-reply-jump28-20260927T233206Z`。
- ZFS：`main/open-hoikuict-pilot/runtime@before-contact-reply-jump28-20260927T233206Z`。
- 完了証跡：`bundle/completed-status.json`、`live-after.json`、`verified-completion.json`、`public-health-after.json`。
