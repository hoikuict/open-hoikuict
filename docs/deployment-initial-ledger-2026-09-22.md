# Excel初期台帳取り込み：実機反映（2026-09-22）

状態：2026-09-22 13:12:34 JST、実機反映完了。修正版（r2）はユーザーのsudo認証で13:08:08 JSTに開始。13:13:01 JSTに稼働版・イメージ・設定を独立照合し、公開ヘルスチェックもHTTP 200を確認した。起動コマンドは再実行しない。初回停止と修正の経緯は後述。

ユーザーから「実機に反映させてみよう」と配備依頼を受けた。直近の配備記録とSSHによる実機の状態を照合し、現在の本番版を直接の基準にした。

## 配備対象

- 現在の本番：`5dec9cf39da19f1ddcff82eadeaa0fac85bac162`。
- 今回の版：`15b13a9dd1eb6ae1b4d171186cb12c1dcc33326c`。直接の親は現在の本番版。
- ローカルブランチ：`codex/initial-ledger-20260922-production`。
- 固定ソース：`.local-dev/truenas-initial-ledger-20260922/source`。
- 固定配備ファイル：`.local-dev/truenas-initial-ledger-20260922/bundle`。
- 実機：`truenas_admin@100.65.124.96`。
- 実機専用ディレクトリ：`/home/truenas_admin/initial-ledger-20260922-15b13a9`。
- systemdサービス：`hoikuict-initial-ledger-20260922-15b13a9`。
- 基準Compose SHA256：`a15583b8d1edf8b23827986068b6e95af2eba17992ef91c6ab212cf128a2db3b`。
- 基準deployment.json SHA256：`76ca662535f4369110a95e3b1f64dab9679c555c9120af5b27e562cd985ef3a6`。

変更は今回の初期台帳機能11ファイルだけ。開発中のベータ導入機能や他の作業中ファイルは含めない。DBスキーマ、バックアップ形式、依存パッケージ、Composeは変更しない。

## 追加機能

「インポート・エクスポート」から「初期台帳をExcelから登録」を開く。園児1人1行で、保護者①②も同じ行に入力する。園児番号・家庭番号を自動採番し、家庭名は姓、同姓の別家庭がある場合は姓名を使う。任意のきょうだいグループが同じ行を同じ家庭にまとめる。

読み込み後の修正・再確認・最終確認を経て、台帳だけを一括登録する。保護者ログイン用アカウントは作らない。既存アカウント、園児との紐づけ、登録済み台帳は今回の配備で変更しない。旧PCの移行用CSVは取り込まない。

## 完了した事前検証

- 本番基準の配備用ソースで23モジュール、243テスト成功（184.25秒）。初期取り込み、98人への既存紐づけ保持、家庭アーカイブ、CSV、保護者同期・ログイン、権限、写真、請求、復元などを含む。
- 配備手順の6テストをWindowsと実機Linuxの両方で実行し成功。設定保持、処理中の更新拒否、切替失敗時の両ワーカー復旧、DBスキーマ差異時の停止などを確認した。
- 配備後の初期台帳検査を架空データで実行し、検査前後のDB全体のダンプが同一であることを確認。画面、Excelテンプレート、38項目、3園児・2家庭の確認表示、権限、静的ファイルを検査した。
- 固定配備ファイル14件、UPDATE.json、SHA256SUMSを実機で照合。配備対象のソース358ファイルのハッシュを固定した。
- 実機の現在版、イメージ、Compose、deployment.jsonが上記基準と一致することをSSHで確認した。

## 起動後に行う処理

1. 稼働中ソース349ファイル、マウント、設定、復元キューを照合し、差異があれば止める。
2. 新イメージを構築し、358ソースファイルを照合する。ネットワークを無効にした使い捨てコンテナで復元演習と243テストを行う。
3. 本番DBのコピーで起動、既存データの保持、家庭アーカイブ、初期台帳の読み取り専用検査、既存バックアップとの互換性を確認する。
4. 公開接続を短時間停止し、実行中バックアップ・復元の状態を確認してからアプリと両ワーカーを停止する。ZFSスナップショット、主DB、施設文例DB、設定を退避して切り替える。
5. 既存73テーブルの内容、添付、設定、スキーマ、全ソースを照合する。既存機能と初期台帳画面を読み取り専用で検査し、公開を再開する。

本番台帳への試験登録はしない。初期台帳検査では `PRAGMA query_only=ON` を用い、登録前の確認内容の計算と画面描画だけを行う。保護者アカウント数・紐づけ数・ID 4の紐づけ数を集計し、既存記録の比較も行う。

失敗時は旧コード・設定に切り戻す。DBの自動巻戻しは行わない。スキーマ差異がある場合は保守状態と退避物を保持して停止する。

## 管理者認証と完了確認

`sudo -n true` は `sudo: a password is required` を返した。配備の許可は依頼済みであり、追加の仕様承認ではなく実機の管理者認証が必要。

ユーザーのPowerShellで実行済み（再実行不要）：

```powershell
ssh -t truenas_admin@100.65.124.96 "sudo python3 /home/truenas_admin/initial-ledger-20260922-15b13a9/start-systemd.py"
```

`Update service started` と出たら再実行しない。過去の更新コマンドも実行しない。SSHを閉じてもsystemdが配備を継続する。

`status.json` が `complete` になった後、`.local-dev/truenas-initial-ledger-20260922/capture_completion.py` で現在の実機メタデータを独立して照合する。完了結果と実測値は本記録に追記する。

## 初回停止・復旧と配備用検査の修正

12:56:15 JSTに開始し、実機内で復元演習、243テスト、本番DBコピーの起動・台帳保持・アーカイブ確認・初期台帳確認、既存バックアップ7件との互換性確認が成功した。切替直前にスナップショットとDB・設定の退避も完了した。

切替後、以前の配備から引き継いだ `verify-family-live.py` が「全家庭に削除リンクが表示される」と検査して停止した。現在の本番にはアーカイブ済み52家庭があり、その家庭一覧には削除リンクを表示しない仕様である。以前の配備時点ではアーカイブ済み0家庭だったため顕在化していなかった。

初回の例外は `switch_release` → `verify_live` → `verify-family-live.py` の実行箇所。失敗時処理で旧版の起動・更新前とのDB照合・公開接続再開を完了してから、元の例外を記録して終了した。旧版のcommit・image・Compose・deployment.jsonが基準と一致し、公開 `/healthz` がHTTP 200を返すことも独立して確認した。DBの巻戻しは行っていない。

- 初回失敗記録：`.local-dev/truenas-initial-ledger-20260922/bundle/failed-status.json`。
- 復旧後の実機メタデータ：`.local-dev/truenas-initial-ledger-20260922-r2/bundle/live-before.json`。
- 退避：`/mnt/main/open-hoikuict-pilot/backups/before-initial-ledger-20260922T035615Z`。
- スナップショット：`main/open-hoikuict-pilot/runtime@before-initial-ledger-20260922T035615Z`。

配備用の検査を、通常家庭では削除リンク、アーカイブ済み家庭では復帰リンクと削除リンクの非表示を確認するよう修正した。同じ検査を切替前の本番DBコピーでも実行するようにした。アプリのコードと配備対象commitは変更しない。

架空データで旧検査の失敗を該当assert行まで再現した。修正後は通常・アーカイブ済み・復帰済みの3状態すべてで検査が成功し、検査前後のDB全体のダンプが同一だった。修正版の配備手順6テストがWindowsと実機Linuxで成功し、14入力ファイルと各ハッシュを実機で照合した。

## 修正版（r2）の起動・照合

- 固定配備ファイル：`.local-dev/truenas-initial-ledger-20260922-r2/bundle`。
- アプリのソース・commit：初回と同じ `15b13a9dd1eb6ae1b4d171186cb12c1dcc33326c`。
- 実機専用ディレクトリ：`/home/truenas_admin/initial-ledger-20260922-15b13a9-r2`。
- systemdサービス：`hoikuict-initial-ledger-20260922-15b13a9-r2`。

ユーザーが実行済みの修正版の起動コマンド（再実行不要）：

```powershell
ssh -t truenas_admin@100.65.124.96 "sudo python3 /home/truenas_admin/initial-ledger-20260922-15b13a9-r2/start-systemd.py"
```

起動したら再実行しない。完了後の独立照合には `.local-dev/truenas-initial-ledger-20260922-r2/capture_completion.py` を使用する。初回の配備ファイルと失敗記録はそのまま保持する。

## 本番反映の結果

- 完了：2026-09-22 13:12:34 JST。独立照合：13:13:01 JST。
- 稼働版：`15b13a9dd1eb6ae1b4d171186cb12c1dcc33326c`。
- 実機イメージ：`sha256:8eee8704af57ee8bac122f01e4dfd50cfe4bec3c115de16eb64c329bd0d92d1b`。
- 本番ソース：`/mnt/main/open-hoikuict-pilot/releases/15b13a9dd1eb-20260922T040808Z`。
- Compose SHA256：`a15583b8d1edf8b23827986068b6e95af2eba17992ef91c6ab212cf128a2db3b`（変更なし）。
- 更新後deployment.json SHA256：`84234a295ab7d2d32c6e3ea963f1e905ef965ec828d9165a818c7ca1d306a3d0`。
- 実機の隔離環境で243テスト成功。失敗・スキップ・収集エラーは0件。復元演習、本番DBコピーの起動と読み取り専用検査、既存バックアップ7件の互換性確認も成功。
- アプリ・gateway・backup-worker・restore-workerが正常。公開用tunnelを再開済み。公開 `/healthz` のHTTP 200を独立確認した。
- 更新前の既存73テーブルの記録、添付8ファイル、DBスキーマ、既存設定を照合し保持した。園児100人、家庭134件、保護者アカウント8件、園児との紐づけ105件を維持。
- テスト用保護者ID 4の98人への紐づけを維持。家庭は通常表示82件・アーカイブ済み52件、アーカイブ履歴52件を保持した。
- 全134家庭の一覧、削除確認、アーカイブ・復帰確認、編集・記録画面を読み取り専用で検査。今回の家庭削除・アーカイブ・台帳への試験登録はすべて0件。
- 初期台帳の実機画面、Excelテンプレート38項目、3園児・2家庭の確認内容、自動採番・家庭名、権限、CSS・JavaScriptの配信を読み取り専用で検査した。試用専用の架空データ登録ボタンは表示されない。
- 定期バックアップは更新直前と同じ「有効・毎日02:00 JST・weekday=0」を保持した。
- 直前退避：`/mnt/main/open-hoikuict-pilot/backups/before-initial-ledger-20260922T040808Z`。
- スナップショット：`main/open-hoikuict-pilot/runtime@before-initial-ledger-20260922T040808Z`。

完了記録は `.local-dev/truenas-initial-ledger-20260922-r2/bundle/completed-status.json`、`live-after.json`、`verified-completion.json` に保存した。

利用者は本番の「データ入出力」→「初期台帳をExcelから登録」を開く。直接URLは `https://hikarinomori.hoikuict.net/initial-ledger/`。ログイン後、入力用Excelをダウンロードして利用できる。読み込み・画面上の修正・最終確認を経て「台帳に登録する」を押した時点で保存する。
