# コード構成・データ保存

確認日: 2026年9月13日。起動入口はリポジトリ直下の **`main:app`** です。`routers/main.py` を本体の入口として起動しません。

## リクエストの流れ

```text
ブラウザー
  → main.py（FastAPI、CSRF、認証例外処理、ルーター登録）
    → routers/・child_records/・plan_docs/routers/
      → 各サービス、認証・権限判定
        → SQLModel / SQLite、文例DB、storage内の添付
    ← Jinja2テンプレート、部分HTML、JSON、各種出力
```

画面はJinja2とHTMX等を使うサーバー側のHTML描画です。アプリを起動するための独立したnpmビルド手順はありません。

## 変更する場所を探す

| 場所 | 主な責務 |
| --- | --- |
| `main.py` | dotenv読込、起動時の初期化、background task、ルーター統合 |
| `models.py` / `database.py` | 業務モデル、エンジン、テーブル作成、組み込みスキーマ更新 |
| `routers/` | 園児・登降園・保護者・請求・職員等のHTTP入口 |
| 直下の `*_service.py` など | 業務処理、料金計算、同期、配送、認可 |
| `auth.py` / `local_auth.py` / `parent_auth.py` / `staff_recovery.py` | 認証バックエンド、資格情報、セッション、登録・復旧 |
| `security_config.py` / `csrf.py` / `kiosk_security.py` | 起動条件、CSRF、キオスクアクセス |
| `child_records/` | 子どもの記録、児童票、記録設定 |
| `plan_docs/` | 本体の `/plans/` に統合した保育計画・文書・文例 |
| `templates/` / `assets/` | 画面・静的アセット |
| `scripts/` | 初期管理者CLI、デモ投入、バックアップ、通知構成確認 |
| `deploy/truenas/` | 現行の初期導入ComposeとWeb Push追加構成 |
| `test_*.py` / `tests/` | 自動テスト |
| `docs/` / `mkdocs.yml` | このドキュメントサイト |

`gen_bunnrei/` は文例関連の資産・処理を含みます。CIのアプリテストでは `--ignore=gen_bunnrei` を指定します。

## 起動時に行うこと

1. production以外でdotenvを読み、設定済みのプロセス環境変数を優先します。
2. セキュリティ設定と認証バックエンドを検証します。
3. 古いインポート確認データの整理、施設文例ファイルの準備、DBスキーマの作成・更新を行います。
4. 通知の保存期間処理、既存の家族・健康データの整合処理を行います。
5. 設定に応じてプッシュ・保護者メール・職員復旧メールの非同期workerを起動します。

業務デモデータや初期管理者は自動投入しません。施設文例DBは初回に配布済みファイルをコピーするため、「空DBでの起動」はすべてのSQLite資産が空という意味ではありません。

## DBと永続化先 {#storage}

| 対象 | ローカルの既定・設定 | TrueNAS基本構成 |
| --- | --- | --- |
| 業務・認証・保育計画のDB | `HOIKUICT_DATABASE_URL`、既定 `sqlite:///./hoikuict.db` | `/data/hoikuict.db` |
| 施設独自の文例DB | `HOIKU_FACILITY_BUNREI_DB_PATH`、既定 `data/facility.sqlite` | `/data/facility.sqlite` |
| 添付 | `storage/` 配下。機能ごとの保存先はバックアップ仕様を参照 | `/app/storage` を永続化 |
| インポート事前検証 | `HOIKUICT_PREVIEW_DIR` | `/data/data_transfer_previews` |
| バックアップ制御 | `HOIKUICT_BACKUP_CONTROL_DIR` | `/data/backup-control` |
| 日案文例コーパス | `HOIKU_DAILY_PLAN_EXAMPLES_DB_PATH`、読み取り専用 | 採用するコーパスを別途配置 |

`.env.example` の日案コーパスパスは隣接する `hoiku-plan-corpus` リポジトリ内の開発用成果物を指します。このリポジトリのcloneだけではそのファイルは揃いません。[コーパス契約](daily-plan-corpus-contract.md)に合う成果物を配置し、利用環境ごとに設定します。

正式対応DBは **SQLite** です。WAL、外部キー制約、busy timeoutを設定し、SQLite向けの組み込み更新を起動時に行います。PostgreSQL等には正式な移行手順を提供していません。外部スキーマ管理を使う場合は `HOIKUICT_ALLOW_UNMANAGED_SCHEMA=1` が必要で、登録メタデータと実スキーマの不一致があれば停止します。

バックアップは業務DBに加えて施設文例DB・添付・構成を対象にします。鍵の別管理、稼働中コピーの制限、復元検査は[バックアップ・復元仕様](backup-restore-spec.md)を参照してください。

## HTTPルートと認証の境界

職員・保護者のログインルートは認証モードに応じて登録されます。モックは `HOIKUICT_ENABLE_MOCK_AUTH=1` と各認証モードが条件で、productionでは禁止です。development専用の通知確認ルーターも本番へは登録しません。

キオスクは `require_kiosk_access` による独立した端末認証です。個人の職員・保護者セッションの代わりとして使用しません。

URLを確認するときは[画面一覧](screen-transition-list.md)と、`main.py`で実際に登録するルーターのprefixを合わせて確認します。
