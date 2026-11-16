# 年間指導計画 本番配備（2026-09-28）

## 状態

**本番配備と独立した完了確認が完了。** 完了日時: 2026-09-28 17:10:32 JST。

ユーザーの「本番に実装しよう」という依頼を受けて配備した。管理者認証はユーザーが手元のターミナルで行い、その後の更新結果を確認した。
更新ジョブは既に完了している。`start-systemd.py` は再実行しない。

## 利用する画面

- 年案: https://hikarinomori.hoikuict.net/plans/annual-library
- 今回の取り込み元: R8年度どんぐり・1歳児の既存帳票。
- 本文59欄と配置を持つ46文章を反映。推定した開始目安45件は未確認として表示する。
- 原文と原位置を保持し、本文・開始目安の編集、確認、保存、再表示、改訂、前年からの引き継ぎに対応。
- 取り込み元を選び、年度・クラスを確認した後に利用者が保存する。本番に試験文書は作成していない。
- 今回は検証済みの1歳児様式が対象。他年齢の専用様式への対応は含まない。

## 配備した版

- 更新前: `2ff239ad8ed175ab7fc1ac067a038429af8ec43f`
- 更新後: `7076cd4e09fda4d70f79923e56f5af1a6d7ea697`
- イメージ: `sha256:4f65baf4ae0d0f7b0caccee43c79976da8e1ed7859e668b0dee8e9ee0ca69831`
- 稼働ソース: `/mnt/main/open-hoikuict-pilot/releases/7076cd4e09fd-20260928T080430Z`
- Compose SHA256（変更なし）: `f3cddda31ac5c20b7b7633fa6427e3cce28e21de02d0cb87c7d3d6812a611817`
- deployment.json SHA256: `73d7dbfda3cee5a96decc81b9537a92116b18a0c9748e486e4196b19ccd67d48`
- 配備ブランチ: `codex/annual-library-20260928-production`
- 配備用ソース: `C:/python/hoiku-plan-docs/tmp/annual-production/source`
- サーバー配備一式: `/home/truenas_admin/annual-library-20260928-7076cd4`
- 完了済み systemd unit: `hoikuict-annual-library-20260928-7076cd4`

本番の直前の版に年案差分22ファイルだけを適用した。開発版の他の変更は含めていない。
本番のバックアップ形式1を維持し、年案の2列と一意インデックスを追加した。過去のバックアップは復元用コピー上でのみ追加移行する。
既存の本番チェックアウトは読み取りだけで使用し、新コミットは上記の配備用ソースに保存した。

## 検証結果

- ローカルと本番Linuxイメージの双方で255テスト成功。失敗・スキップなし。
- 切り替え・ロールバック・追加移行の配備テスト10件成功（ローカルと転送先）。
- ネットワークを切ったコンテナーで復元の成功・失敗演習を確認。
- 実データ59欄の保存・再表示、46件の位置保持、編集、前年からの引き継ぎを独立DBで確認。
- 実DBのコピーで起動・追加移行を確認。既存バックアップ10件の復元互換性を確認。
- 本番の年案画面を読み取り専用トランザクションで確認。原文・原位置・取り込み元SHA256を照合。試験文書の書き込みは0件。
- 月案の共同編集、個人・集団様式、PDF・Excel出力、主任印、文例検索、園内Ollamaを確認。AI確認には架空データのみ使用。
- 連絡帳の一覧・返信移動、職員ポータルの対象範囲、既存の台帳・園児記録・退園処理・保護者関連機能を確認。
- アプリ・トンネル・バックアップ・復元ワーカーは正常。既存レコードと添付13件を保持。
- バックアップ予定を保持: {"enabled": true, "frequency": "daily", "run_time": "02:00", "weekday": 0}。
- 公開URLのヘルスチェック成功。年案の未認証アクセスは職員ログインへ誘導。
- 本番が出力した年案・月案・連絡帳のCSS/JavaScriptのURLをそのまま取得し、配備ソースと完全一致を確認。

## バックアップと取り込み元

- 更新前バックアップ: `/mnt/main/open-hoikuict-pilot/backups/before-annual-library28-20260928T080430Z`
- 更新前ZFSスナップショット: `main/open-hoikuict-pilot/runtime@before-annual-library28-20260928T080430Z`
- 取り込み元JSON SHA256: `adf102a1d8442835bbcd35acb0f2a8b87f223aa86d0ba361ff3e1e6ed322c45e`

取り込み元JSONはGitのソースアーカイブに含めず、専用の非公開転送ファイルとして配備一式と新しいイメージに保持した。
園名は本番の設定から取得し、イメージ内の `/app/data/annual-library-sources.json` へ登録した。
原文・表示位置・出典は保存済み文書のJSONにも含まれるため、通常の文書バックアップ・復元の対象になる。
本番の環境設定、Compose、文例データ、添付、予定は維持した。

## 確認記録

ローカル: `C:/python/hoiku-plan-docs/tmp/annual-production/`

- `production-tests.xml`: ローカル255テスト。
- `transfer-verification.txt`: 転送後31ファイルの照合と配備テスト。
- `bundle/completed-status.json`: サーバーの完了結果。
- `bundle/live-after.json`: 独立して読んだ本番の版・イメージ・配備記録。
- `bundle/verified-completion.json`: 配備結果と稼働版の照合。
- `bundle/public-health-after.json`: 公開URLと配信資産の照合。

同じ記録を `C:/python/open-hoikuict/docs/deployment-annual-library-2026-09-28.md` に保存する。
