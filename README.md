# open-hoikuict

園児・家庭の情報、登降園、保護者との連絡、健康記録、保育計画、請求、職員の情報共有を扱う、オープンソースの保育ICTプロジェクトです。

**[デモを試す](https://demo.hoikuict.net/) · [プロジェクトサイト](https://open.hoikuict.net/) · [詳しい資料](docs/technical-guide.md) · [導入方法](docs/getting-started.md) · [機能と実装状況](docs/features.md) · [開発手順](docs/development.md)**

## 現在の状況

2026年9月13日時点で、職員・保護者のローカルパスワード認証、共通QRによる保護者登録、Web Push、端末監視、バックアップ管理まで実装が進み、TrueNASでの実機検証・更新記録があります。

機能の実装と施設での運用開始は別に確認します。公開デモ・ローカル検証には架空データを使い、実データを扱う範囲は[運用試験の受入条件](docs/pilot-deployment-spec-v2.md)に沿って施設で決めてください。

## 主な機能

- 園児・家庭・クラス・保護者管理、CSV/Excel入出力、プロフィール変更申請
- 登降園・出欠確認・専用キオスク、お迎え予定の変更、誤打刻の取消と履歴
- 保護者の日次連絡、お知らせ・アンケート、出欠確認依頼のプッシュ・任意メール通知
- 健康プロフィール・アレルギー・健診、子どもの記録、児童票
- 年案・月案・週案・日案、文例、版管理、振り返り
- 保育必要量別の延長料金、月次確認、請求転送、口座管理、全銀データ出力
- 職員ホーム、カレンダー、職員ルーム、議事録、園内記録、文書の確認依頼
- 職員・保護者認証、明示的な園児の閲覧許可、端末監視、バックアップCLI・管理画面

後続計画と制限は[機能一覧](docs/features.md)と[仕様一覧](docs/specifications.md)を参照してください。保育計画は本体の `/plans/` に統合されています。

## ローカルで試す

CIとDockerの基準はPython 3.12です。以下はmacOS / Linuxの初回セットアップです。Windows PowerShellの手順は[開発ガイド](docs/development.md)にあります。

```bash
git clone https://github.com/hoikuict/open-hoikuict.git
cd open-hoikuict
python3.12 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
export HOIKUICT_DATABASE_URL=sqlite:///./hoikuict-dev.db
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000/` を開きます。通常起動は業務デモデータを投入しません。モックでの画面確認には[専用DBへの100人規模デモ投入](docs/demo-data.md)、パスワード認証の確認には[ローカルβ設定と初期管理者作成](docs/environment-profiles.md)を使います。

公開デモの案内先は[保育ICTデモ](https://demo.hoikuict.net/)です。配備先の版により、このリポジトリの最新機能と差がある場合があります。

## 導入・運用

- [TrueNASへの導入ガイド](docs/truenas-beginner-installation-guide.md)と[初期構成の詳細](docs/truenas-fresh-install.md)
- [職員・保護者のアカウント](docs/accounts.md)、[共通QR登録](docs/parent-public-registration.md)
- [日々の業務](docs/daily-work.md)、[通知ガイド](docs/notifications.md)、[家庭・園児CSV](docs/family-guardian-csv-guide.md)
- [日常運用と障害対応](docs/operations.md)、[本番設定](docs/security.md)、[バックアップ・復元](docs/backup-restore-spec.md)
- [画面・URL一覧](docs/screen-transition-list.md)、[コード構成](docs/architecture.md)、[変更履歴](docs/history.md)

正式対応DBはSQLiteです。WAL、外部キー制約、busy timeoutとSQLite向けの組み込みスキーマ更新を使用します。非SQLiteでは外部スキーマ管理と `HOIKUICT_ALLOW_UNMANAGED_SCHEMA=1` が必要です。正式なマルチDB移行手順は提供していません。

## ドキュメントを編集する

```bash
python -m mkdocs serve --dev-addr 127.0.0.1:8008
python -m mkdocs build --strict
```

プレビューは `http://127.0.0.1:8008/` です。ページ構成・リンク検査・公開対象の扱いは[ドキュメント更新ガイド](docs/documentation.md)を参照してください。

## ライセンス・問い合わせ

[MIT License](LICENSE)。ソフトウェアは無保証で提供します。運用責任とサポート体制は施設・法人で確認してください。

不具合・改善提案は[GitHub Issues](https://github.com/hoikuict/open-hoikuict/issues)、セキュリティ問題は公開せず `openhoikuict@gmail.com` へ連絡してください。[CONTRIBUTING.md](CONTRIBUTING.md)、[SUPPORT.md](SUPPORT.md)、[SECURITY.md](SECURITY.md)も参照してください。
