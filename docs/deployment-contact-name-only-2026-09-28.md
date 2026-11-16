# 保護者連絡一覧・名前横の丸を削除する本番更新

状態：本番反映完了。2026-09-28 08:02:32 JSTに公開再開。08:02:41に稼働版と丸の削除を照合し、08:02:53に公開HTTPSと実際のHTMLが参照するCSS/JSの一致を確認した。

## 承認と変更

- ユーザーは「丸い部分を削除し、名前だけを表示する」を選択。修正モックを確認して実装を依頼し、その後「本番にも反映して」と依頼した。
- 反映先：`https://hikarinomori.hoikuict.net/daily-contacts/`。
- 名前横の頭文字を入れた丸と、そのための囲み・余白・CSSを削除。クラス・提出状態・日時・提出者・詳細リンクは保持。
- 変更は `templates/daily_contacts/_content_table.html` と `static/css/daily-contact-list.css` の2ファイルのみ。

## 基準と配備版

- 現行の稼働版：`33cee6a9026ae7cac30df921685657372c7eae53`。SSHで最新配備記録・イメージの一致を確認。
- 基準イメージ：`sha256:4a5b61e673b9e3e8d48e75297d712a1194926d7a8a26c1ea8353614c3e544527`。
- 更新版：`f79846c31e361da6fed3f02f13798c4e4720a534`。
- 本番用ブランチ：`codex/contact-name-only-20260928-production`。
- 本番用作業コピー：`.local-dev/truenas-monthly-export-20260927/source` を継続使用。
- 425ファイルのうち変更は上記2ファイルのみと照合。開発側の別作業は含めない。
- 基準deployment.json SHA256：`b1692e2f99a5467987a7316ad8276066a31b8cff9c69f1be2b5ee0b45a7c3ec1`。
- Compose SHA256：`f3cddda31ac5c20b7b7633fa6427e3cce28e21de02d0cb87c7d3d6812a611817`。
- DBスキーマ、依存関係、Compose、文例コーパスは変更しない。

## 検証・配備の準備

- 既存の連絡一覧17テスト成功。実装画面で丸の削除と名前から詳細への往復を確認済み。
- 配備手順の10テスト成功（設定保持、バックアップ／復元キュー保護、失敗時の復旧を含む）。
- 配備時の表示検査に、丸がないことと名前リンク数の一致を追加。架空DBの一覧32画面・詳細10画面で成功。
- 約8.5MBのコードと配備資材を実機へ転送。26資材ファイルのハッシュ一致と配備手順10テスト成功。この段階では本番未変更。
- 管理者起動後、候補イメージの209テスト、復元試験、本番DBコピーでの一覧と既存機能、バックアップ互換性を確認する。
- 合格後に公開を一時停止し、DB退避とZFSスナップショットを作成して切替。新しい稼働版で表示とデータ保持を確認して公開再開し、公開HTTPSのJS/CSSを照合する。

## 実行済みの管理者起動（再実行不要）

ユーザーがsudo認証を実行済み。`status.json` は `complete`。同じコマンドを再実行しない。

```sh
sudo python3 /home/truenas_admin/contact-name-only-20260928-f79846c/start-systemd.py
```

systemd：`hoikuict-contact-name-only-20260928-f79846c`。

## 証跡

`.local-dev/contact-name-only-20260928/` に保存。

- `application-tests.xml`、`prepared.json`、`transfer-verification.txt`
- `bundle/UPDATE.json`、`bundle/SHA256SUMS`
- `deploy_capture_completion.py`、`deploy_capture_public.py`

## 本番の確認結果

- 稼働版：`f79846c31e361da6fed3f02f13798c4e4720a534`。
- イメージ：`sha256:fd03c70bc0dfda27d4cb6292a2499e04e711b4de057ba03c955e54c0e467de61`。
- 更新後deployment.json SHA256：`1feadaccbd59f1800ceda4ebffe121105cd793dc2cec4ae3e83842a2a999ac1a`。
- 実機209テスト成功。失敗・スキップ0。復元試験、既存バックアップ10件の互換性も成功。
- 本番の稼働版で在園98名・一覧56画面・詳細98画面を描画し、丸と旧囲みの不存在、名前リンクの件数一致を確認。`avatars_removed: true`、検証による書き込み0。
- 一覧CSS `/static/css/daily-contact-list.css?v=06e1b1b8913384de` とJS `/static/js/daily-contact-list.js?v=475cfe4f772c203b` を実際のHTMLから取得し、公開HTTPSの内容と配備資材がバイト一致。
- 月案のJS/CSSも従来どおり一致。月案・既存帳票・文例検索・AIの架空条件での動作を確認。月案検査の `contexts` は旧検査の変数再利用により担当人数を示すため、表示条件数の根拠として使用しない。
- 公開healthz正常。HTML要求で未認証の一覧URLが職員ログインへ303遷移することを確認。
- アプリ・公開トンネル・backup-worker・restore-worker正常。業務データ・添付13ファイル・Compose・毎日02:00のバックアップ設定を保持。
- 退避：`/mnt/main/open-hoikuict-pilot/backups/before-contact-name-only28-20260927T225705Z`。
- ZFS：`main/open-hoikuict-pilot/runtime@before-contact-name-only28-20260927T225705Z`。
- 完了証跡：`bundle/verified-completion.json`、`completed-status.json`、`live-after.json`、`public-health-after.json`。
