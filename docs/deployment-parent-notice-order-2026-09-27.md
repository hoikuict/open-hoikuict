# 保護者のお知らせの並び順・本番反映

2026-09-27。ユーザーが未読優先のモックを確認後、「本番に反映して」と依頼。
仕様と検証は `docs/implementation-parent-notice-order-2026-09-27.md`。

## 現在の状態

**2026-09-27 05:52:08 JSTに本番反映が完了。**
05:52:20 JSTに稼働メタデータを独立照合し、05:52:42 JSTに公開HTTPSの正常応答を確認した。
配備開始は05:46:05 JST。

`sudo -n true` が `sudo: a password is required` を返したため、管理者認証だけをユーザーに依頼した。
ユーザーの「実行した」の連絡後、実機の処理開始から完了まで確認した。認証と配備は完了しており、起動コマンドの再実行は不要。

## 本番反映の結果

- 稼働commit：`51ddae0ad1ff641310fdd4edb22f369385d0f45b`。
- 実機イメージ：`sha256:e5d1ab380bc69383803655b02f348ad921a039f5b654eca29a38fd886b060dcb`。
- 本番ソース：`/mnt/main/open-hoikuict-pilot/releases/51ddae0ad1ff-20260926T204605Z`。
- 更新後deployment.json SHA256：`73ea5d5cd18a750271eb53f8680771ccc4b44596cc4195af421635b8dfcdfb15`。
- 実機の隔離環境でも40テストすべて成功。失敗・スキップ・収集エラーなし。復元演習と既存バックアップ10件の互換性検査も成功した。
- 保護者8アカウント分のホーム・一覧・未読画面、計24画面を読み取り専用で検査。未読優先、種類を混ぜた日時順、ホーム5件の制限と対象データの一致を確認。検査による既読の書き込みは0件。
- 既存の在籍98人の出欠画面・キオスク、33種類の職員権限と記録関連3,234ページ、連絡詳細98ページを検査。デスクトップ配置と既存機能を保持した。
- 既存テーブルの記録・添付13ファイル・Compose・設定を保持。園児100人、家庭134件、保護者アカウント8件、園児との紐づけ104件を保持した。
- アプリ・gateway・backup-worker・restore-workerが正常。定期バックアップの「有効・毎日02:00 JST・weekday=0」を保持した。
- 公開 `/healthz` はHTTP 200・`status: ok`。既存の出欠確認CSSも配備アーカイブとバイト単位で一致した。
- 直前退避：`/mnt/main/open-hoikuict-pilot/backups/before-notice27-20260926T204605Z`。
- スナップショット：`main/open-hoikuict-pilot/runtime@before-notice27-20260926T204605Z`。

完了証跡は `.local-dev/truenas-notice-order-20260927/bundle/` の `completed-status.json`、`live-after.json`、`verified-completion.json`、`public-health-after.json` に保存した。

本番の保護者ホーム：<https://hikarinomori.hoikuict.net/parent-portal/>。

## 本番基準と配備内容

- 最新配備記録：`docs/deployment-desktop-attendance-2026-09-25.md`（2026-09-27完了）。
- 基準commit：`c907275b94cabcb613b4cf2a8edf778c05ade8dd`。
- 基準イメージ：`sha256:1287fc69674e87be665794fcc25da38ff03547891a4d0eab55ac0035e4746367`。
- 基準deployment.json SHA256：`f149a351ce06687a02cd38de38a6d78d972c65388a37511f8d96b3ec6b612a73`。
- Compose SHA256：`a15583b8d1edf8b23827986068b6e95af2eba17992ef91c6ab212cf128a2db3b`。内容を保持。
- 配備commit：`51ddae0ad1ff641310fdd4edb22f369385d0f45b`。
- ローカルブランチ：`codex/parent-notice-order-20260927-production`。
- 専用作業コピー：`.local-dev/truenas-notice-order-20260927/source`。
- 固定配備ファイル：`.local-dev/truenas-notice-order-20260927/bundle`。
- 実機ディレクトリ：`/home/truenas_admin/notice-order-20260927-51ddae0`。
- systemdサービス：`hoikuict-notice-order-20260927-51ddae0`。

本番からの変更は `routers/parent_portal.py`、`templates/parent_portal/notices.html`、`test_parent_notice_order.py` の3ファイルだけ。
他の開発中変更を取り込まず、既存の家庭管理、記録の共有範囲、出欠訂正、デスクトップ配置、バックアップ・復元を保持する。

## 完了した準備

- 稼働commit・イメージ・deployment.json・ComposeをSSHで取得し、最新配備記録との一致を確認。
- 本番基準で40テストがすべて成功。配備手順8テストがWindowsと実機Linuxで成功。
- 読み取り専用の新規検査を架空2アカウント・6画面で実行し、DB全体のdumpの一致を確認。
- ソース393ファイルのハッシュを固定し、基準との差分が上記3ファイルだけであることを確認。
- 固定配備入力19ファイル、UPDATE.json、SHA256SUMSを転送し、実機でハッシュと構文を検証。

## 実施した配備手順

前回成功した配備処理を継承。更新ロックと基準照合、新イメージ構築、ネットワークなしの使い捨てコンテナで復元演習と40テストを実行した。
本番DBのコピーで既存機能と今回の未読優先・日時順を読み取り専用検査し、既存バックアップの互換性も検査した。
検証後に短時間の公開停止、DB退避・ZFSスナップショットを取り、アプリとバックアップ・復元ワーカーを切り替えた。
既存記録・添付・設定・スケジュールの保持と画面を検査し、公開を再開した。
本番の保護者ホーム・一覧・未読画面は全アカウント分を読み取り専用で描画し、既読状態は書き換えていない。
最後に `capture_completion.py` と `capture_public_health.py` で独立照合した。
実データの試験登録や検査メール送信は行っていない。DBを古いコピーに戻す処理も実行していない。

実機の完了状態・稼働メタデータ・公開ヘルスチェックの一致をもって、本番反映完了と判断した。
