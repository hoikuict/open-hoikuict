# 月案帳票・文例検索・Ollamaの本番反映

後続更新：2026-09-27 13:14 JSTに印刷・Excel出力を追加した。
13:36 JSTに主任印欄を追加し、13:54 JSTに画面へ古いJSが届く配信キャッシュの不具合を修正した。
最新の稼働版は `5ae9e04`。[最新の配備記録](deployment-monthly-asset-cache-2026-09-27.md) を参照。
以下は11:08時点の配備履歴。

2026-09-27。ユーザーが本番 `/plans/monthly-plans/new` に変更がないと指摘したため、
実機内の隔離検証と本番反映を区別し、本番用の配備手順を準備した。

## 現在の状態

**2026-09-27 11:08:25 JSTに本番反映が完了。**
11:08:51 JSTに稼働メタデータを独立照合し、11:09:03 JSTに公開HTTPSを確認した。
ユーザーによる修正版の管理者コマンド実行後、処理開始から完了まで確認済み。
以下は実行済みコマンドの記録であり、再実行は不要。

```sh
sudo python3 /home/truenas_admin/monthly-deploy-20260927-579e683/start-systemd.py
```

本番の新しい月案画面：<https://hikarinomori.hoikuict.net/plans/monthly-library>。
従来の `/plans/monthly-plans/new` 上部の「原本の帳票で入力・文例検索」からも開ける。
未ログイン時は職員ログインへ遷移し、ログイン後の戻り先が新しい月案画面であることを確認した。

過去に実行した `monthly-library-verify-20260927/start_container.py` は架空データ用の
検証コンテナの起動であり、今回の本番反映とは別。

## 完了結果

- 稼働commit：`579e683c77000ad2238be2cdd3fc3df7513bf8b6`。
- 稼働イメージ：`sha256:de594c07a5f75c6512a42932ad9578e2a78436f0457196de956827f22e4e2d52`。
- 本番ソース：`/mnt/main/open-hoikuict-pilot/releases/579e683c7700-20260927T020316Z`。
- deployment.json SHA256：`92cc5a31cec887ff9ed56904bfe5db4a09bc956a1705fada5af9bb43f12c799d`。
- Compose SHA256：`f3cddda31ac5c20b7b7633fa6427e3cce28e21de02d0cb87c7d3d6812a611817`。
- 実機の100テストと復元演習が成功。既存バックアップ10件の互換性検査も成功。
- 本番DBコピーで移行を確認し、切り替え後は6クラス・36条件の月案画面を読み取り専用で確認。
- 本番アプリと同じDockerネットワークから原文候補50件、食育40件の検索と、
  `qwen3:8b` による実生成2件・署名検証が成功。AIには架空の年齢・月・欄条件だけを送信。
- 本番の文例・AI設定が有効であること、既存機能・記録・添付13ファイルを保持したことを確認。
- アプリ・gateway・backup-worker・restore-workerが正常。毎日02:00 JSTのバックアップ設定を保持。
- 公開 `/healthz` が正常応答。月案CSS/JSと既存出欠CSSが配備アーカイブとバイト単位で一致。
- ブラウザーでも従来画面の新しい入口と職員ログインへの遷移を確認。実データの試験登録は0件。

退避先：`/mnt/main/open-hoikuict-pilot/backups/before-monthly27-20260927T020316Z`。
スナップショット：`main/open-hoikuict-pilot/runtime@before-monthly27-20260927T020316Z`。
証跡は `.local-dev/truenas-monthly-deploy-20260927-r2/bundle/` の `completed-status.json`、
`live-after.json`、`verified-completion.json`、`public-health-after.json`。
画面確認画像は同作業フォルダーの `monthly-production-entry.png`。

## 固定した本番基準と更新内容

- 配備前の本番commit：`51ddae0ad1ff641310fdd4edb22f369385d0f45b`。
- 配備前のイメージ：`sha256:e5d1ab380bc69383803655b02f348ad921a039f5b654eca29a38fd886b060dcb`。
- 配備前のdeployment.json SHA256：`73ea5d5cd18a750271eb53f8680771ccc4b44596cc4195af421635b8dfcdfb15`。
- 配備前のCompose SHA256：`a15583b8d1edf8b23827986068b6e95af2eba17992ef91c6ab212cf128a2db3b`。
- 配備commit：`579e683c77000ad2238be2cdd3fc3df7513bf8b6`。
- ブランチ：`codex/monthly-library-20260927-production`。
- 既存の本番用作業コピー `.local-dev/truenas-notice-order-20260927/source` を再利用。
- 配備ファイル：`.local-dev/truenas-monthly-deploy-20260927-r2/bundle`。
- 実機専用フォルダー：`/home/truenas_admin/monthly-deploy-20260927-579e683`。
- systemdサービス：`hoikuict-monthly-20260927-579e683`。

本番基準に、実機検証済みの月案関連23ファイルと復元互換処理・回帰テストの計25ファイルを反映する。
既存の保護者お知らせ順、出欠画面、記録、バックアップ・復元などのコードを保持する。
Dockerイメージは現在の本番イメージを継承し、ネットワークを使わずコードだけを更新する。
Pythonと依存パッケージを同時更新しない。

従来の `/plans/monthly-plans/new` 上部に「原本の帳票で入力・文例検索」の入口を追加する。
新しい帳票のURLは `/plans/monthly-library`。従来の月案入力と保存済み文書も保持する。
新しい帳票は職員ログインが必要。0〜2歳の個人別、3〜5歳の集団様式、明示保存、出典、
過去3か月の表示とOllamaの仕様は各実装記録を参照。

## 文例とAIの接続

ユーザーは、指定DBから文例128,008件と出典を本番実機へ転送することを明示許可した。
元の `C:/python/getsuan-rag/getsuan.sqlite` は読み取り専用で参照し、検索に必要な
`source`、`cell`、`phrase` の列だけを抽出。ID・本文・出典は全件照合し、元DBは変更していない。

- 圧縮データ：6,643,903 bytes。展開後：38,670,336 bytes。
- 展開後SHA256：`684fdf7e344202b252b4c05aa2a6562d5a021d60edaa3ddd0595cea009e2e29b`。
- 配置先：`/mnt/main/open-hoikuict-pilot/library/getsuan-20260927.sqlite`。
- アプリ内：`/monthly-library/getsuan.sqlite`、読み取り専用マウント。
- ソースID：`getsuan-20260927`。
- Ollama：実機の `http://host.docker.internal:11434`、`qwen3:8b`。

アプリに園別の `HOIKU_MONTHLY_LIBRARY_SOURCES` と `HOIKU_MONTHLY_OLLAMA_SOURCES` を追加する。
Dockerのhost-gateway名を解決し、現在のネットワーク構成を保持する。
Ollamaに送るのは年齢・月・区分・領域・欄の条件のみで、文例本文、氏名、記入本文、過去記録は送らない。
原文データはGitとソースアーカイブに含めず、配備入力として別に保管する。
再試行時は文例データを再転送せず、初回の専用フォルダーにある圧縮データをハッシュ確認して利用する。
修正版のフォルダーへ転送するのはコード・依存テストツール・配備設定のみ。

## 配備前の確認と実行時の手順

- アプリの月案・AI・既存機能77テストは、現在の本番イメージによる隔離実機検証と初回配備前検査で成功済み。
- 修正版は月案の復元11件と既存の復元12件を追加し、計100テストが本番基準のWindows作業コピーで成功。
  開発側でも新しい月案復元11テストが成功。旧バックアップ・稼働DBを変更せず隔離コピーのみを移行する。
- 配備手順10テストはWindowsと実機Linuxで成功。途中失敗時のコード復帰、既存データを
  古いコピーで置き換えないこと、許可外の設定変更拒否、文例ハッシュ不一致時の停止を含む。
- 新しい読み取り専用画面検査を架空DBで試し、前後のDB dumpが一致することを確認。
- 実データ由来の文例検索は本文をログ出力せず確認。Ollama送信条件の固定応答検査も成功。
- 実機Composeに架空の設定値を渡して比較し、月案の接続設定以外が保持されることを確認。
- 転送した配備ファイルのハッシュを照合し、本番基準を再確認してから更新を開始した。

実行した手順は、更新ロックと本番基準の照合、新イメージ構築、復元演習、100テスト。
本番DBのコピーで追加列と索引の移行を試し、既存機能・月案画面・バックアップ互換性を検査する。
文例データを読み取り専用で配置し、本番と同じDockerネットワークから、架空条件で
Ollamaの実生成と署名付き候補の検証を行う。失敗時は本番切り替え前に停止する。

すべて通った後だけ短時間の公開停止、直前DB退避、ZFSスナップショットを取り、
アプリとバックアップ・復元ワーカーを切り替える。既存データ、添付、設定、定期バックアップを
照合してから公開を再開する。本番へ試験用月案や架空園児を登録する処理はない。

変更するDBスキーマは `plan_documents.monthly_sheet`（JSON）、`monthly_sheet_key`（VARCHAR）と
その一意索引だけ。新しい月案が保存済みなら古いコードへの自動復帰を拒否し、データを保全する。

## 初回の停止結果

初回commit `be358f696e6e133f28f3f18f79a72ec3e49cd1a5` は2026-09-27 10:48 JSTに配備処理を開始。
77テスト・復元演習・本番DBコピーでの移行・既存画面・6クラス36条件の月案画面の検査が成功した。
10:50 JSTごろ、既存バックアップのデータ構造不一致で停止。文例配置と本番切り替えの前だったため、
本番のcommit・イメージ・deployment.json・Composeはすべて開始前と同じことを独立照合した。

修正は追加する2列と承認済みの一意索引の形式に限る。異なる型・既定値・NOT NULL・
一意でない索引・別の条件式・無関係の列追加・旧コードへのダウングレードは引き続き拒否する。
初回の専用フォルダー、診断結果、DBの検査用コピーは証跡として保持している。
