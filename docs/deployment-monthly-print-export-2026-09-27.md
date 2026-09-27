# 月案の印刷・Excel出力の本番反映

後続更新：2026-09-27 13:36 JSTに全様式へ主任印欄を追加した。
13:54 JSTに画面へ古いJSが届く配信キャッシュの不具合を修正した。
最新の稼働版は `5ae9e04`。[最新の配備記録](deployment-monthly-asset-cache-2026-09-27.md) を参照。
以下は13:14時点の配備履歴。

2026-09-27。ユーザーの「本番に反映しましょう」に基づく配備。
状態：本番反映完了。2026-09-27 13:14:37 JSTに公開再開、13:14:40に稼働メタデータ、13:14:52に公開URLを独立して確認した。

## 配備結果

- 稼働版：`696a8609d75a91da5f39c7a4d67d76a9d5dddd0f`。
- 稼働イメージ：`sha256:69e9c87a9f85ba4b0c09e18d7205d369737713eb285bcd928a6ad067ba90d38c`。
- 配備ソース：`/mnt/main/open-hoikuict-pilot/releases/696a8609d75a-20260927T040920Z`。
- 更新後deployment.json SHA256：`6e79466f94b8345d8c2a798d6c7a1f760db7318c765e6f558eaba73c6b1b6090`。
- 公開URL：<https://hikarinomori.hoikuict.net/plans/monthly-library>。
- 本番Linuxイメージで112テスト成功。実際のgateway・workerを使った架空データの復元試験成功。
- 本番DBコピーと切り替え後の読み取り専用検証で、6クラス・36条件の月案表示、印刷・Excelボタン、
  架空本文によるPDFの日本語フォント埋め込みとExcelのA4横設定を確認した。本番帳票の生成・保存はしていない。
- 文例検索とOllama `qwen3:8b` の2候補生成が成功。AIには架空の条件だけを送り、個人データは送っていない。
- 既存バックアップ10件の互換性を確認。アプリ・gateway・backup-worker・restore-workerが正常。
- 既存データ、添付13ファイル、Compose、日次02:00のバックアップ設定を保持。
- 公開healthzは正常。配信されたJS・CSS・日本語フォントは更新資材とバイト一致。
  月案ページの未認証アクセスはログイン画面へ遷移することを確認した。
- 退避先：`/mnt/main/open-hoikuict-pilot/backups/before-monthly-export27-20260927T040920Z`。
- ZFS：`main/open-hoikuict-pilot/runtime@before-monthly-export27-20260927T040920Z`。
- 最終証跡：同作業ディレクトリの`bundle/verified-completion.json`と`bundle/public-health-after.json`。

## 対象と基準

- 対象は合意した印刷調整とExcel出力の13ファイル。検索の表記ゆれ・共有文例追加のモックは含めない。
- 実機の稼働版を読み取り確認：`579e683c77000ad2238be2cdd3fc3df7513bf8b6`。
- 基準イメージ：`sha256:de594c07a5f75c6512a42932ad9578e2a78436f0457196de956827f22e4e2d52`。
- 基準deployment.json SHA256：`92cc5a31cec887ff9ed56904bfe5db4a09bc956a1705fada5af9bb43f12c799d`。
- Compose SHA256：`f3cddda31ac5c20b7b7633fa6427e3cce28e21de02d0cb87c7d3d6812a611817`。内容は変更しない。
- 更新版：`696a8609d75a91da5f39c7a4d67d76a9d5dddd0f`。
- 本番基準の独立した作業コピー：`.local-dev/truenas-monthly-export-20260927/source`。
  既存の配備用コピーやモックが参照するソースは変更していない。
- ブランチ：`codex/monthly-print-export-20260927-production`。

## 準備と検証

- 本番基準のコードで、印刷・Excel・月案・AI・通知順・出欠確認・バックアップ・復元等の112テスト成功。
- 実機へ約10.6MBのコード、公開依存パッケージ、日本語フォント、配備ツールを転送。
  実データ、文例コーパス、本番秘密設定は転送していない。
- 転送先で28ファイルのSHA256、構文、配備手順10テスト、Compose不変を確認。
- PythonにはReportLab 4.4.9とXlsxWriter 3.2.9だけをオフライン追加。
  既存パッケージのバージョン不変をビルド時に検証する。
- フォントライセンスは原文を保持。ライセンス原文内の末尾空白は変更していない。

## 実行手順

転送先：`/home/truenas_admin/monthly-export-20260927-696a860`。

```sh
sudo python3 /home/truenas_admin/monthly-export-20260927-696a860/start-systemd.py
```

systemdユニット：`hoikuict-monthly-export-20260927-696a860`。
開始済みの場合は再実行せず、同ディレクトリの`status.json`を確認する。

上記コマンドはユーザーが実行済み。再実行しない。
スクリプトは実機の基準版・設定・全対象ソースを再照合し、別イメージをビルドする。
本番停止前に112テスト、架空データでの復元試験、DBコピーでの既存画面と印刷・Excel生成、
既存バックアップの互換性、文例検索とOllama接続を検証する。
実機での出力確認には架空の本文だけを使い、本番の園児名簿・帳票本文は出力しない。

合格後に短時間の公開停止、ZFSスナップショットとDBコピーを取り、アプリとワーカーを切り替える。
スキーマ変更はなく、既存データ・添付ファイル・バックアップ設定の不変を確認する。
公開再開前の異常は旧コード・設定へ戻す。DBを過去の状態へ自動上書きしない。

証跡：`.local-dev/truenas-monthly-export-20260927/`。
実プリンターとデスクトップExcelでの最終確認は別途必要。
