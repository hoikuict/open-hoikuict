# 月案の担当者制限・同時編集の本番反映

状態：本番反映完了。2026-09-28 06:09:20 JSTに公開再開。06:10:11に稼働メタデータ、06:10:21に公開HTTPSで実際の画面が参照するJS・CSSの一致を確認した。

## 対象と承認

- ユーザーが8904番の欄ごとの保存見本を試用後、「実機に反映しよう」と依頼。
- 反映先は本番 `hikarinomori.hoikuict.net` と明示回答。公開デモは今回の反映対象外。
- 管理者も対象月の担当クラス割当が必要。主担当・補助・臨時の有効な割当を使う。
- 別欄の変更は両方保存し、同じ欄の異なる変更は比較して選び直す。保存は従来どおり明示操作。

## 版と保持する構成

- 基準：`5ae9e04af59c5ec5228c968ce11a56c9d49fa6f2`。
- 基準イメージ：`sha256:ec47e8bfff9244dabcb805282544da0638ff7b5db402a6d4e49b64ec3d916d55`。
- 更新：`c8928030b59817a1537292d0068decf6dc5154d2`。
- 本番用ブランチ：`codex/monthly-collaboration-20260928-production`。
- 本番用作業コピー：`.local-dev/truenas-monthly-export-20260927/source` を再利用。
- 16ファイルだけを基準版へ追加・変更。開発mainの別機能は配備に含めていない。
- DBスキーマ・Python依存関係・Compose・文例コーパスを変更しない。秘密設定・園児データの転送なし。
- 在席情報だけはアプリコンテナ内の専用一時SQLiteを使用する。再起動時の消失は許容し、60秒で失効する。業務データの復元対象には追加しない。
- SSHで基準deployment.json SHA256 `dd933ad3e150759066b645a6e1a802bcb05749fa5a1848b8434281c012d250de` とCompose SHA256 `f3cddda31ac5c20b7b7633fa6427e3cce28e21de02d0cb87c7d3d6812a611817` の一致を確認。

## 検証済み

- 開発側と本番用作業コピーで、それぞれ128テスト成功。
- 担当期間の境界・未割当管理者・閲覧ロール・失効職員・保存直前の担当解除・従来月案の経路を確認。
- 別欄の併合、同じ欄の競合と全件未保存、比較中の再更新、空欄化、担任名、同一内容への収束、初回作成の併合、署名基準の職員・対象範囲への拘束、出典保持を確認。
- 独立したSQLite接続から同時保存を開始する試験で、両方の欄が残ることを確認。
- 在席の範囲・失効・担当解除・閲覧職員の除外・同じ職員の別タブを確認。
- 実装した業務ルートと架空DBを使ったブラウザー二画面で、併合、比較、取消、入力保持、手直しして再保存を確認。JavaScriptエラーなし。
- 実機へ約8.5MBのコードと配備資材を転送。25ファイルのハッシュ一致、配備手順10テスト成功。この転送の段階では本番サービスを変更していない。
- 実機DBの担当割当は一般SSHユーザーから直接確認できなかったため、管理者起動後の読み取り専用検証でクラス別・対象月別の件数と認可判定を確認する。割当の追加や変更を配備処理で行わない。

## 実行済み（再実行不要）

```sh
sudo python3 /home/truenas_admin/monthly-collaboration-20260928-c892803/start-systemd.py
```

systemd：`hoikuict-monthly-collaboration-20260928-c892803`。
ユーザーがsudo認証を実行。06:03:40 JSTに開始し、06:09:20に完了。
同ディレクトリの `status.json` は `complete`。再実行しない。

切り替え前に実機で128テスト、復元試験、本番DBコピーによる既存機能・担当割当の読み取り専用確認、全様式PDF／Excel、バックアップ互換性、文例検索・Ollamaの架空条件による生成を検証する。
合格後に退避・ZFSスナップショットを作って更新。配備後は実際のHTMLが参照するJS・CSSのURLを公開HTTPSで照合する。

## 証跡

- `.local-dev/monthly-collaboration-20260928/application-tests-main.xml`
- `.local-dev/monthly-collaboration-20260928/application-tests-production.xml`
- `.local-dev/monthly-collaboration-20260928/actual-conflict.png`
- `.local-dev/monthly-collaboration-20260928/prepared.json`
- `.local-dev/monthly-collaboration-20260928/transfer-verification.txt`
- `.local-dev/monthly-collaboration-20260928/bundle/UPDATE.json`

続きの確認スクリプト：`capture_completion.py` と `capture_public.py`。完了後にこの記録へ実際の結果を追記する。

## 本番の確認結果

- 稼働コミット：`c8928030b59817a1537292d0068decf6dc5154d2`。
- イメージ：`sha256:91ad324e5905b2582ead6045a5a932d40d5c468ebd3c947218b95f524c0e33aa`。
- ソース：`/mnt/main/open-hoikuict-pilot/releases/c8928030b598-20260927T210341Z`。
- 更新後deployment.json SHA256：`ebf0cb92dfe0cd05d646df624bfa24059bf1fecfc2ed4b2de1d4fdbd175ed191`。
- 実機128テスト全件成功。復元試験、既存バックアップ10件の互換性が成功。
- 全6クラスで、2026年9月・10月の月案を編集できる実在の担当職員を確認。ID 1〜6の順に、9月は4・5・5・2・2・3名、10月は4・5・5・2・2・2名。担当割当・アカウント・ロールの変更なし。
- 月案の表示、担当判定、PDF／Excel、0〜5歳の主任印、文例検索が成功。検証で本番帳票を保存した件数は0。
- Ollama `qwen3:8b` は架空条件で2候補を生成。個人データをAIに送っていない。
- 本番HTMLから取得したJS `/static/js/monthly-library.js?v=cb44a40ca1358949` とCSS `/static/css/monthly-library.css?v=fbe5f1da3d3ff4b8` を、そのまま公開HTTPSで取得し、配備資材とバイト一致した。
- 公開healthz正常、未認証の月案ページは職員ログインへ遷移。アプリ・公開トンネル・backup-worker・restore-worker正常。
- 業務データ・添付13ファイル・Compose・毎日02:00のバックアップ設定を保持。
- 退避：`/mnt/main/open-hoikuict-pilot/backups/before-monthly-collaboration28-20260927T210341Z`。
- ZFS：`main/open-hoikuict-pilot/runtime@before-monthly-collaboration28-20260927T210341Z`。
- 完了証跡：同作業フォルダーの `bundle/verified-completion.json`、`completed-status.json`、`live-after.json`、`public-health-after.json`。

検証スクリプトの集計上の注意：`verify-monthly-live.py` の既存 `count` 変数を担当職員数の集計にも使ったため、JSONの `contexts: 2` は最後のクラスの担当職員数であり、帳票表示の条件数を表していない。実行コードは全6クラス×6年齢のループを完了している。元の証跡は改変せず保持し、条件数の証拠として `contexts` を使用しない。アプリケーションコード・権限判定・切り替え結果への影響はない。
