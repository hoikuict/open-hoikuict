# 月案の古いJavaScriptが配信される不具合

2026-09-27。主任印欄を配備済みと報告した後、ユーザーから本番の0歳児画面に主任印がない画像が届いた。
状態：本番反映完了。2026-09-27 13:54:21 JSTに公開再開、13:55:45に稼働メタデータ、
13:56:00に画面が実際に参照するURLで公開配信内容を確認した。

## 配備結果

- 稼働版：`5ae9e04af59c5ec5228c968ce11a56c9d49fa6f2`。
- イメージ：`sha256:ec47e8bfff9244dabcb805282544da0638ff7b5db402a6d4e49b64ec3d916d55`。
- ソース：`/mnt/main/open-hoikuict-pilot/releases/5ae9e04af59c-20260927T044914Z`。
- 更新後deployment.json SHA256：`dd933ad3e150759066b645a6e1a802bcb05749fa5a1848b8434281c012d250de`。
- 本番Linuxイメージの114テストが全件成功。復元試験、既存バックアップ10件の互換性も成功。
- 本番DBコピーと更新後の読み取り専用検証で6クラス・36条件の表示、0〜5歳の主任印欄、
  フォント埋め込みPDF・Excel出力を確認。検証による帳票の新規保存は0件。
- 本番HTMLから取り出した次のURLを、そのまま公開HTTPSで取得し、配備資材とバイト一致した。
  - JS：`/static/js/monthly-library.js?v=8603cbec9665dc6a`
  - CSS：`/static/css/monthly-library.css?v=52fa46b4aab83eb0`
- 取得したJSに「園長印」「主任印」の隣接表示があり、年齢によって主任印を省く古い条件がないことを確認。
  通常の画面再読み込みで新しいURLを使う。利用者の認証済みブラウザーを直接操作しての確認ではない。
- 公開healthzは正常。未認証の月案ページはログインへ遷移。アプリ・公開トンネル・両workerは正常。
- 文例検索とOllama `qwen3:8b` の2候補生成が成功。AIには架空の条件だけを送り、個人データは送っていない。
- 既存データ、添付13ファイル、Compose、日次02:00のバックアップ設定を保持。
- 退避先：`/mnt/main/open-hoikuict-pilot/backups/before-monthly-cache27-20260927T044914Z`。
- ZFS：`main/open-hoikuict-pilot/runtime@before-monthly-cache27-20260927T044914Z`。
- 証跡：`.local-dev/truenas-monthly-cache-20260927/bundle/verified-completion.json`、
  `completed-status.json`、`live-after.json`、`public-health-after.json`。

## 原因と前回の確認不足

- 通常の `/static/js/monthly-library.js` がCloudflareから `cf-cache-status: HIT`、
  `Cache-Control: max-age=14400`（4時間）で返り、0歳・2歳の主任印がない古いコードだった。
- 前回は `?deployment=cd036c3` を独自に追加した確認用URLを取得し、最新コードと一致したため、
  利用者の画面でも更新済みと判断した。画面のHTMLが実際に指定するURLとの照合が欠けていた。
- サーバー上の更新やPDF・Excelの主任印欄は反映済みだったが、通常画面へ反映されていない状態を見逃した。
- 診断証跡：`.local-dev/truenas-monthly-cache-20260927/cache-diagnosis.json`。
  Cookie等の機密ヘッダーは記録せず、キャッシュ情報とコードのSHA256だけを保存する。

## 修正

- 月案のJS・CSSの読み込みURLに、実ファイルのSHA256先頭16桁を `?v=` として付ける。
  内容が変わるとURLも変わり、古い配信キャッシュを再利用しない。
- 編集画面・保存済み文書で共有する `_sheet.html` に適用する。
  テンプレート共通関数 `static_asset_url` が静的ファイルから版番号を算出する。
- 内容更新が同じプロセスでも反映されるよう、手動の版番号や起動時だけのキャッシュは使わない。
- 出力レイアウト、本文、保存、権限、依存ライブラリ、DB、Composeは変更しない。
- 配備後の検証では本番画面を読み取り専用で生成し、HTML内のJS・CSSのURLだけを取り出す。
  公開HTTPSからそのURLをそのまま取得し、配備資材と照合する。確認用クエリは追加しない。

## 版・検証

- 基準版：`cd036c3dbbec4030afc09251c333ceb48405369a`。
- 基準イメージ：`sha256:baa165e85edd71827848f3eac6f25b3f747c95c02e4ae5c21d80b3245f1c54b2`。
- 基準deployment.json SHA256：`0f0557f67bc420bfa9d3a5b725f77065c55e29b99d2d9ed7548d995285f1d8e8`。
- 更新コミット：`5ae9e04af59c5ec5228c968ce11a56c9d49fa6f2`。
- ブランチ：`codex/monthly-asset-cache-20260927-production`。
- 本番用作業コピー：`.local-dev/truenas-monthly-export-20260927/source` を継続使用。
- 変更は `template_utils.py`、月案の `_sheet.html`、`test_monthly_export.py` の3ファイル。
- 新しい回帰テストで、編集可・閲覧専用の月案画面と保存済み文書が参照する実URLの取得・内容一致、
  ファイル内容が変わるとレンダリングされるURLも変わることを確認した。
- ローカルの114テストが成功。うち既存2件は一時ディレクトリの親がまだ存在せず初回セットアップで失敗し、
  親を作成後に当該2件のみ再実行して成功。初回と再実行のXMLを両方保持する。
- 実機へコードと配備ツール約8.5MBを転送。25ファイルのハッシュと配備手順10テストが成功。
  本番秘密設定・実データ・文例コーパスは転送していない。

## 実行

ユーザーによる管理者認証で実行済み。再実行は不要。

```sh
sudo python3 /home/truenas_admin/monthly-cache-20260927-5ae9e04/start-systemd.py
```

systemd：`hoikuict-monthly-cache-20260927-5ae9e04`。
開始済みの場合は再実行せず、同ディレクトリの `status.json` を確認する。
本番停止前にLinuxで114テスト、復元試験、本番DBコピーでの読み取り専用確認、
全様式のPDF・Excel、文例検索・Ollama、既存バックアップ互換性を検証した。
合格後に退避コピーを作って短時間の公開停止を伴う更新を行い、既存データと設定の不変を確認した。
