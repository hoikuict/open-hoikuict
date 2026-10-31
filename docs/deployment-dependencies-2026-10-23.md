# 依存関係の実機更新

2026-10-23 15:50:51 JSTに反映完了。別のSSH接続と公開URLによる完了確認済み。更新プログラムを再実行しない。

ユーザーの「依存関係については実機に反映してください」という依頼により、稼働していた10月12日の本番イメージに依存関係の更新を重ねた。

## 更新内容

| パッケージ | 更新前 | 更新後 |
| --- | --- | --- |
| Pillow | 12.3.0 | 13.0.0 |
| Starlette | 0.52.1 | 1.3.1 |
| python-multipart | 0.0.20 | 0.0.32 |
| python-dotenv | 1.1.1 | 1.2.4 |
| pip | 25.0.1 | 26.2 |
| aiohttp | 3.14.3 | 3.14.4 |
| certifi | 2026.7.22 | 2026.10.19 |
| multidict | 6.9.0 | 6.9.1 |

実機の監査で間接依存3件にも修正済みの問題が検出されたため、修正版を追加した。FastAPIは既存の0.135.1を維持し、依存条件・`pip check`・本番ソースの回帰テストで互換性を確認した。

`requirements.txt` に直接依存の固定版と間接依存の修正済み下限を記録し、Dockerfileでpipの版も固定した。実機はハッシュを固定したLinux用wheelを使い、通信なしで8パッケージだけを更新した。インストール済み76パッケージの全版が監査済み一覧と一致し、既知の脆弱性は0件。

## 検証と保持

- イメージの `/app` 全ファイルを照合し、変更は `requirements.txt` と `Dockerfile` の2ファイルだけ。既存の画面・業務コードを保持した。コンテナーの起動条件も照合した。
- 本番ソースを使う通信なし・読取専用コンテナーで、架空データの全テストを実行。1,231件成功、2件失敗、スキップ・収集エラー0。別に282サブテスト成功。
- 失敗2件は旧イメージと新イメージで再実行し、失敗箇所・理由の一致を確認。今回の更新による新規失敗は0。配備の構成保持ガード7件も成功。
- 停止中に業務DB・施設DB・添付・設定・配備記録・バックアップ予定を保存。再起動前後で業務レコード、添付13件、バックアップ予定の保持を確認した。
- 年案の担任抽出を実機6クラスで確認し、保存済み年案3件を保持。月案・週案の36のクラス・年齢の組合せを表示確認した。
- 日案例820件、週案例533件、既存の読取専用マウントを保持。日案の文例検索・印刷・振り返りの画面も確認した。
- アプリはhealthy、バックアップ・復元ワーカーとcloudflaredは稼働。公開 `/healthz`、職員・保護者のログイン遷移、公開JS/CSS5ファイルの一致を確認した。
- 配備後の確認で業務データを書き込まず、メール・Pushの試験送信も行っていない。

既存テストの失敗は次の2件。依存関係の更新とは別にテスト条件の整合が必要。

1. `test_child_records.py::ChildRecordFeatureTests::test_progress_record_entry_shows_logs_and_creates_versioned_document`：固定された8月の記録を、現在の10〜12月の入力期間に期待している。
2. `test_returned_documents.py::test_plan_return_appears_on_home_until_confirmed[monthly_plan]`：対象月の担当クラス割当がないため、現行の権限検証で403になる。

## 配備記録

- アプリコミット：`5aabf64b559b10318b015e628e9109bcfb076631`
- 基準コミット：`06ed6c9f2402c5250216795d779c35beeedd0020`
- ブランチ：`codex/dependency-security-20261023`
- 新イメージ：`sha256:257c5acd9482104259340380b2894818660015cb87a489c12bd2f96120516966`
- 旧イメージ：`sha256:d77562dd66ef1bb48611bb6919e64f64d00251eccbd0d720812d83ca7a97a92f`
- Compose SHA-256：`f284d6dd0d961c4e0dab392536731410d163a99b68b72527245f42a07807758a`（内容を保持）
- バックアップ：`/mnt/main/open-hoikuict-pilot/backups/before-dependencies-20261023-5aabf64`
- リリース：`/mnt/main/open-hoikuict-pilot/releases/dependencies-20261023-5aabf64b559b`
- サーバー作業先：`/home/truenas_admin/dependencies-20261023-5aabf64`
- ローカル作業先：`.local-dev/dependency-rollout-20261023`
- 本番用ソースコピー：`.local-dev/dependency-rollout-20261023/source`
- 集約検証記録：`verification-dependencies-production-2026-10-23.json`

切戻しは旧イメージ・設定へ戻す方式で、業務DBを巻き戻さない。今回は切戻しを実行していない。Windows導入キットのCaddy修正、写真読込コードの追加制限、CI・Dependabotは今回の実機反映対象に含めていない。
