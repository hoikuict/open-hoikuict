# 月案の主任印欄の本番反映

後続の不具合：通常のJS URLにはCloudflareの古いキャッシュが残り、利用者の画面では主任印が表示されないことが判明した。
以下の公開コード照合は確認用クエリ付きのURLで行ったため、通常画面への反映確認としては不十分だった。
原因と修正は [配信キャッシュの修正記録](deployment-monthly-asset-cache-2026-09-27.md) を参照。
2026-09-27 13:54 JSTに修正版 `5ae9e04` の配備が完了し、13:56 JSTに実際の画面のURLで公開配信を照合した。
以下は13:36時点の配備履歴。

2026-09-27。ユーザーが操作見本の配置を確認し「はい、本番に反映しましょう」と依頼した。
状態：本番反映完了。2026-09-27 13:36:46 JSTに公開再開、13:36:54に稼働メタデータ、13:37:06に公開URLを独立して照合した。

## 配備結果

- 稼働版：`cd036c3dbbec4030afc09251c333ceb48405369a`。
- イメージ：`sha256:baa165e85edd71827848f3eac6f25b3f747c95c02e4ae5c21d80b3245f1c54b2`。
- ソース：`/mnt/main/open-hoikuict-pilot/releases/cd036c3dbbec-20260927T043143Z`。
- 更新後deployment.json SHA256：`0f0557f67bc420bfa9d3a5b725f77065c55e29b99d2d9ed7548d995285f1d8e8`。
- 公開URL：<https://hikarinomori.hoikuict.net/plans/monthly-library>。
- 本番Linuxイメージで112テスト、架空データを使ったgateway・workerの復元試験が成功。
- 本番DBコピーと切り替え後の読み取り専用検証で6クラス・36条件の表示が成功。
  0〜5歳全様式の主任印欄を印刷確認・フォント埋め込みPDF・Excelで確認した。
- 文例検索とOllama `qwen3:8b` の2候補生成が成功。AIには架空の条件だけを送り、個人データは送っていない。
- 既存バックアップ10件の互換性を確認。アプリ・gateway・backup-worker・restore-workerが正常。
- 既存データ、添付13ファイル、Compose、日次02:00のバックアップ設定を保持した。
- 公開healthzは正常。主任印欄を含むJS、CSS、日本語フォントの配信内容は配備資材とバイト一致。
  月案ページへの未認証アクセスはログインへ遷移することを確認した。
- 退避先：`/mnt/main/open-hoikuict-pilot/backups/before-chief-stamp27-20260927T043143Z`。
- ZFS：`main/open-hoikuict-pilot/runtime@before-chief-stamp27-20260927T043143Z`。
- 証跡：`.local-dev/truenas-chief-stamp-20260927/bundle/verified-completion.json`、`public-health-after.json`。

## 実装

- 全ての年齢（0〜5歳）の様式に「園長印」「主任印」の空欄を隣接して表示する。
- 0歳・2歳の主任印欄を追加し、1歳・3〜5歳の「主任」を「主任印」に統一した。
- 編集画面、保存済み文書、直接印刷、印刷確認、PDF、Excelの全ページで同じ配置にする。
- 紙の押印用の空欄であり、新しい入力・保存・承認処理は追加しない。
- アプリの変更は `static/js/monthly-library.js` と `plan_docs/services/monthly_export_layout.py` の2ファイル。
  合意した見本とバイト一致。既存の本文、入力項目、保存仕様、権限は変更しない。

## 基準版と更新版

- SSHで確認した基準版：`696a8609d75a91da5f39c7a4d67d76a9d5dddd0f`。
- 基準イメージ：`sha256:69e9c87a9f85ba4b0c09e18d7205d369737713eb285bcd928a6ad067ba90d38c`。
- 基準deployment.json SHA256：`6e79466f94b8345d8c2a798d6c7a1f760db7318c765e6f558eaba73c6b1b6090`。
- Compose SHA256：`f3cddda31ac5c20b7b7633fa6427e3cce28e21de02d0cb87c7d3d6812a611817`。内容は変更しない。
- 更新コミット：`cd036c3dbbec4030afc09251c333ceb48405369a`。
- ブランチ：`codex/monthly-chief-stamp-20260927-production`。
- 本番用作業コピー：`.local-dev/truenas-monthly-export-20260927/source` を再利用。
- 今回の配備資材と証跡：`.local-dev/truenas-chief-stamp-20260927/`。
- 元の開発側の2ファイルにも同じ変更を適用した。既存モックの専用ソースは変更していない。

## 検証・転送

- 本番用コードで既存112テスト成功。PDF・Excel、長文の全本文保持、全様式、認証、CSRF、
  文例検索、AI、通知、出欠確認、バックアップ復元等を含む。JavaScript構文チェックも成功。
- 0〜5歳について印刷確認、フォント埋め込みPDF、Excelの主任印セルを生成し、
  園長印との隣接・高さの一致を確認した。
- 実機へ約8.5MBのコードと配備ツールを転送。25ファイルのSHA256と配備手順10テストが成功。
- 今回は依存パッケージ、DBスキーマ、Compose、本番秘密設定、文例コーパスの変更はない。
  実データや秘密設定の転送もない。

## 実行

転送先：`/home/truenas_admin/chief-stamp-20260927-cd036c3`。
ユーザーが以下を実行済み。再実行しない。

```sh
sudo python3 /home/truenas_admin/chief-stamp-20260927-cd036c3/start-systemd.py
```

systemdユニット：`hoikuict-chief-stamp-20260927-cd036c3`。
開始済みの場合は再実行せず、同ディレクトリの`status.json`を確認する。

既存の配備ガードを再利用し、実機の基準版・設定・ソースを再照合する。
現在の本番イメージを継承してコードだけを更新し、公開停止前に112テスト、架空データの復元試験、
本番DBコピーでの既存画面と全様式の主任印出力、バックアップ互換性、文例検索、Ollama接続を確認する。
出力確認には架空の本文を使い、本番帳票・園児名簿は出力しない。

合格後に短時間の公開停止、ZFSスナップショットとDBコピーを取り、アプリとワーカーを切り替える。
既存データ・添付ファイル・バックアップ設定の不変を確認して公開を再開する。
公開再開前に異常があれば旧コード・設定へ戻し、DBを過去の状態へ自動上書きしない。
