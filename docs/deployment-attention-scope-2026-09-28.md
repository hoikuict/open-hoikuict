# ホームの要確認件数を担当全クラスから集計する本番更新

状態：**本番反映完了**。2026-09-28 10:07:59 JSTに公開再開。10:08:14に稼働メタデータ、10:08:27に公開HTTPSと配信ファイルの一致を確認した。

## 承認内容

- ユーザーは集計範囲を「役割にかかわらず担当する全クラス」、判定を「未入力も含めるまま」と指定。
- 8924番の架空データモックを確認し、「これでいいよ。OK本番に反映しよう」と実装・本番反映を承認。
- ホームの担当／全クラス切替と先頭3クラスの表示制限から要確認を分離。
- 未入力または有効なアラームのある園児を1人1件、本人宛ての未回答アンケートを加算。
- ホームの要確認リンクは担当全クラスの一覧へ進み、件数を一致させる。
- 担当なしの管理者も出欠は0件。ホームの出欠カードが全体を表示する既存動作は維持。
- 一覧側で管理者が明示的に全クラスへ切り替える既存機能を維持。
- 集計範囲の説明と、取得エラー時の「取得不可」をモックどおり追加。

## 基準と更新版

- SSHで独立確認した本番稼働版：`4581393839d40d0e4eddbf71b9b4b28a7ba461ea`。
- 基準イメージ：`sha256:388d12fc7b97827352bc45349e71ee4a9fe3c1b62d836982384fa665a903d808`。
- 基準deployment.json SHA256：`22a4a4a562ab844b2da20f69de67d5d8b53891de3a99d911246b4951b9049b0a`。
- Compose SHA256：`f3cddda31ac5c20b7b7633fa6427e3cce28e21de02d0cb87c7d3d6812a611817`。
- 更新版：`2ff239ad8ed175ab7fc1ac067a038429af8ec43f`。
- 本番用ブランチ：`codex/attention-scope-20260928-production`。
- 本番用作業コピー：`.local-dev/truenas-monthly-export-20260927/source` を継続使用。
- 基準425ファイルの一致を確認し、変更4ファイル＋追加1ファイルの426ファイルをハッシュ照合。
- 開発mainの別作業は配備に含めない。DBスキーマ・依存関係・Composeの変更なし。

変更ファイル：

- `routers/staff_portal.py`
- `staff_portal_service.py`
- `templates/portal/index.html`
- `templates/portal/attention.html`
- `test_staff_attention_scope.py`（回帰テスト追加）

## 検証結果

- 開発側の関連47テスト成功。既存の一般職員の全クラス人数表示も別途1テスト成功。
- 本番用コードは既存209テスト＋新規24テスト＋既存ホーム11テストの計244テスト成功。失敗・スキップなし。
- 管理者・編集職員・閲覧職員で、4番目以降の担当、重複・期限切れ・未来・他職員の割当、担当なし、未回答アンケート、未入力とアラームの重複、入力済み、カードと要確認の独立した取得エラーを検証。
- 実装画面を架空DBでブラウザー操作し、担当表示62件→全クラス表示62件→担当一覧62件を確認。
- 本番用の読み取り検査も架空DBで実行し、検査前後のDBダンプが一致。
- 配備手順10テストがWindowsと実機Linuxで成功。設定保持・バックアップ／復元との排他・失敗時の復旧を確認。
- 約8.5MBのコードと配備資材を実機へ転送。27資材ファイルとUPDATE.json・SHA256SUMSを照合。
- 転送後にも稼働メタデータが基準と一致し、今回のstatus.jsonがまだ存在しないことを確認。
- `sudo -n true` は `sudo: a password is required`。起動にはユーザーのsudo認証が必要。

## 管理者起動（実行済み・再実行不要）

ユーザーが本番SSH端末から起動済み。同じコマンドを再実行しない。

```sh
sudo python3 /home/truenas_admin/attention-scope-20260928-2ff239a/start-systemd.py
```

Windowsから接続して起動する場合：

```powershell
ssh -t truenas_admin@100.65.124.96 "sudo python3 /home/truenas_admin/attention-scope-20260928-2ff239a/start-systemd.py"
```

パスワードはSSH端末内で入力する。会話には送らない。
systemd：`hoikuict-attention-scope-20260928-2ff239a`。
起動後は同じコマンドを再実行せず、同ディレクトリのstatus.jsonを確認する。

起動後、候補イメージで244テスト・復元試験を実施し、本番DBコピーで全有効職員の担当件数・ホーム両表示・一覧の一致を読み取り検査する。既存機能とバックアップ互換性も確認する。
合格後に公開を短時間停止し、DB退避・ZFSスナップショットを作成して切替。稼働版でも全職員の要確認と既存機能、業務データ・添付・設定・バックアップ予定の保持を検証して公開を再開する。
配備処理で実データへの試験登録やメール送信はしない。

## 続きの確認と証跡

作業フォルダー：`.local-dev/attention-scope-20260928/`。

- `live-before.json`、`live-prestart.json`、`prepared.json`
- `application-tests.xml`、`production-tests.xml`
- `implementation-home.png`、`implementation-attention.png`
- `prepare_source.py`、`prepare_bundle.py`、`verify-attention-live.py`
- `bundle/UPDATE.json`、`bundle/SHA256SUMS`、`transfer-verification.txt`

完了後の独立照合は `deploy_capture_completion.py`、公開HTTPS・配信ファイル照合は `deploy_capture_public.py` で実施済み。

## 本番の確認結果

- 稼働コミット：`2ff239ad8ed175ab7fc1ac067a038429af8ec43f`。
- イメージ：`sha256:54aad3a40e408b9cbebee82cd2e6017e4786bbeaac90522f326ec7a228a7fcc7`。
- 更新後deployment.json SHA256：`bfc5b68d2c8dcf264533f746bac59f16a7061645ac2c88e9a03bd349566d49ff`。
- ソース：`/mnt/main/open-hoikuict-pilot/releases/2ff239ad8ed1-20260928T010216Z`。
- 実機244テスト成功。失敗・スキップ・収集エラー0。復元演習、既存バックアップ10件の互換性検査も成功。
- 有効な職員32名（管理者4・編集職員28）に対し、ホームの担当表示・全クラス表示・担当要確認一覧の計96画面を検査。ホームの切替に関係なく担当全クラスの件数を表示し、一覧と一致した。本番DBコピーと更新後の稼働版の両方で成功。
- 件数検査はSQLの読み取り専用トランザクションで実施し、書き込み0。件数は職員により1〜98件で、個人名や園児名は検証結果へ出力していない。
- 保護者連絡の一覧84画面・詳細196画面・返信リンク784件を検査。名前横の丸の削除と返信欄への移動、閲覧権限を保持。
- 月案の担当制限・同時編集、全6クラス・年齢0〜5歳の帳票、PDF／Excel、文例検索、AIの架空条件での生成を確認。個人データのAI送信なし。
- 月案検査の既存 `contexts` フィールドは別用途の担当職員数に上書きされるため、表示条件数の証拠には使用しない。元の証跡は保持。
- 公開 `/healthz` 正常。保護者連絡一覧の未認証アクセスは職員ログインへ303遷移。
- 実際のHTMLが参照する月案と保護者連絡のJS/CSS計5ファイルを公開HTTPSで取得し、配備資材とバイト一致。
- アプリ・公開トンネル・backup-worker・restore-worker正常。業務データ・添付13ファイル・Compose・毎日02:00のバックアップ設定を保持。
- 退避：`/mnt/main/open-hoikuict-pilot/backups/before-attention-scope28-20260928T010216Z`。
- ZFS：`main/open-hoikuict-pilot/runtime@before-attention-scope28-20260928T010216Z`。
- 完了証跡：作業フォルダー内 `bundle/completed-status.json`、`live-after.json`、`verified-completion.json`、`public-health-after.json`。
