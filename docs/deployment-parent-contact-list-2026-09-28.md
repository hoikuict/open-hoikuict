# 保護者連絡の内容一覧・本番反映

状態：本番反映完了。2026-09-28 07:36:34 JSTに公開再開。07:37:23に稼働メタデータ、07:38:17に公開HTTPSと実際の画面が参照するJS・CSSの一致を確認した。

## 依頼と範囲

- 既存項目のみを使うモックを試用し、実装と隔離した実機検証を完了後、ユーザーが「本番に移行しましょう」と依頼。
- 反映先：`https://hikarinomori.hoikuict.net`。
- 保護者連絡の既定を内容一覧にし、従来の提出状況一覧へ切り替え可能にする。入力項目、保存処理、DBスキーマの変更なし。
- 日付・クラス・並び順、一覧と詳細の往復、閲覧権限、長文、未提出・欠席・補食未確認の表示を検証済み。

## 版と既存機能の保持

- 基準：`c8928030b59817a1537292d0068decf6dc5154d2`。
- 更新：`33cee6a9026ae7cac30df921685657372c7eae53`。
- 本番用ブランチ：`codex/parent-contact-list-20260928-production`。
- 本番用作業コピー：`.local-dev/truenas-monthly-export-20260927/source` を再利用。
- 業務コード7ファイル・テスト1ファイル・架空画面検証用1ファイルの計9ファイルのみ変更。隔離した実機検証時のファイルハッシュと一致。
- 開発側の未反映作業を取り込まず、現在の本番機能を保持。425ファイルのハッシュを固定。
- Compose、Python依存関係、DBスキーマ、文例コーパスの変更なし。秘密設定と実データの転送なし。
- SSHで最新の稼働版・イメージ・配備記録と照合済み。基準のdeployment.json SHA256：`ebf0cb92dfe0cd05d646df624bfa24059bf1fecfc2ed4b2de1d4fdbd175ed191`、Compose SHA256：`f3cddda31ac5c20b7b7633fa6427e3cce28e21de02d0cb87c7d3d6812a611817`。

## 検証と配備手順

- 事前の隔離した実機検証：81テスト成功、在園98名の一覧56画面・詳細98画面、書き込み0・コピーのハッシュ保持。
- 配備手順の10テスト成功（設定保持・復旧・バックアップ／復元キュー保護を含む）。
- 配備後に使う表示検査コードを架空DBで試し、一覧32画面・詳細10画面の描画、JS/CSSの参照先を確認。
- 本番基準から作った配備版で、一覧機能81件と既存機能128件を組み合わせた209テストがすべて成功（94.19秒、失敗・スキップなし）。
- 約8.5MBのコードと配備資材を実機へ転送し、26ファイルのハッシュと配備手順10テストを照合済み。この段階では本番未変更。
- 管理者起動後、本番を公開したまま候補イメージを構築。復元試験・209テスト・本番DBコピーでの表示・既存機能・バックアップ互換性を検証する。
- 全検査合格後、一時的に公開を止め、DB退避とZFSスナップショットを作成してアプリと既存ワーカーを更新。失敗時は従来版の構成に復旧する。
- 公開再開前に稼働版で一覧と詳細の描画、既存機能、業務データ・添付・バックアップ設定の保持を確認する。公開再開後はHTTPSでhealthzと実際のHTMLが参照するJS/CSSを照合する。

## 実行済みの起動コマンド（再実行不要）

ユーザーがサーバーでsudo認証を実行済み。同じコマンドを再実行せず、`status.json` で経過を確認する。

```sh
sudo python3 /home/truenas_admin/parent-contact-list-20260928-33cee6a/start-systemd.py
```

systemd：`hoikuict-parent-contact-list-20260928-33cee6a`。

## 証跡

`.local-dev/parent-contact-list-20260928/` に保存。

- `real-machine-status.json`：配備前の隔離した実機検証。
- `prepared.json`、`deployment-bundle/UPDATE.json`、`deployment-bundle/SHA256SUMS`：確定した配備版。
- `deployment-application-tests.xml`：配備版の209テスト結果。
- `transfer-verification.txt`：実機への転送後照合。
- `deploy_capture_completion.py`、`deploy_capture_public.py`：配備完了と公開HTTPSの検査。

## 本番の確認結果

- 稼働コミット：`33cee6a9026ae7cac30df921685657372c7eae53`。
- イメージ：`sha256:4a5b61e673b9e3e8d48e75297d712a1194926d7a8a26c1ea8353614c3e544527`。
- ソース：`/mnt/main/open-hoikuict-pilot/releases/33cee6a9026a-20260927T223054Z`。
- 更新後deployment.json SHA256：`b1692e2f99a5467987a7316ad8276066a31b8cff9c69f1be2b5ee0b45a7c3ec1`。
- 実機で209テスト成功。失敗・スキップ0。復元試験と既存バックアップ10件の互換性も成功。
- 切替前のコピーと切替後の稼働版で、それぞれ在園98名・一覧56画面・詳細98画面を読み取り専用で描画。検証による書き込み0。
- 内容一覧のJS `/static/js/daily-contact-list.js?v=475cfe4f772c203b`、CSS `/static/css/daily-contact-list.css?v=c5ccd0ec10d6d6e9` を実際のHTMLから取得し、公開HTTPSの内容と配備資材がバイト一致。
- 従来の月案JS/CSSも公開HTTPSで一致。月案の担当判定・同時編集関連画面・PDF／Excel・主任印、文例検索、Ollamaの架空条件による生成を確認。
- 公開healthz正常。ブラウザー相当の `Accept: text/html` では未認証の一覧URLが職員ログインへ303遷移。API相当の要求では401となる既存認証動作も確認。
- アプリ・公開トンネル・backup-worker・restore-worker正常。既存業務データ、添付13ファイル、Compose、毎日02:00のバックアップ設定を保持。
- 退避：`/mnt/main/open-hoikuict-pilot/backups/before-parent-contact-list28-20260927T223054Z`。
- ZFS：`main/open-hoikuict-pilot/runtime@before-parent-contact-list28-20260927T223054Z`。
- 完了証跡：`deployment-bundle/verified-completion.json`、`completed-status.json`、`live-after.json`、`public-health-after.json`。

検証記録の注意：引き継いだ月案検査の `contexts` は変数再利用により最後のクラスの担当人数を示すため、画面条件数の証拠には使用していない。保護者連絡一覧の画面数は専用の `list_pages`・`detail_pages` で確認した。
