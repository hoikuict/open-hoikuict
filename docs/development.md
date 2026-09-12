# 開発環境とテスト

CIとDockerは **Python 3.12** を使います。Gitとブラウザーを用意し、リポジトリ直下でコマンドを実行します。ここではWindowsの起動スクリプトに合わせて仮想環境名を `venv` に統一します。

## Windows PowerShell

```powershell
git clone https://github.com/hoikuict/open-hoikuict.git
Set-Location open-hoikuict
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env
$env:HOIKUICT_DATABASE_URL = "sqlite:///./hoikuict-dev.db"
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

`.env` のコピーは初回だけ行い、設定済みのファイルを上書きしないでください。仮想環境の有効化が実行ポリシーでできない場合は、各 `python` コマンドを `.\venv\Scripts\python.exe` で実行できます。

## macOS / Linux

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

新しいシェルで起動するときも、同じ仮想環境とDB設定を使います。継続して使う開発用DBの設定は `.env` に保存できます。

## 起動と初期データ

ブラウザーで `http://127.0.0.1:8000/` を開きます。`.env.example` はdevelopment、モック認証、開発用のキオスクと通知captureを設定します。`main.py` はproduction以外でdotenvを読み込み、既存のプロセス環境変数を優先します。

通常起動ではテーブル作成・スキーマ更新と既存データの整合処理を行い、職員・園児などの業務デモデータを自動投入しません。空DBにはモックで選択する職員もいません。

画面確認に架空データが必要な場合は、アプリを止め、上で指定した **専用の開発用DB** で次を実行します。シードCLIを実行するシェルでもDBの環境変数を設定しておきます。

```bash
python -m scripts.seed_demo_100 --wipe-all
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

!!! warning "デモ投入は既存データを削除する操作"
    `--wipe-all` は対象テーブルの既存データを削除します。認証版β・稼働中のDBを指定しないでください。データの範囲と生成期間は[デモデータ](demo-data.md)を参照します。

認証そのものを試す場合は[ローカルβの設定](environment-profiles.md)へ進みます。

## テストと静的検査

CIと同じ環境指定で実行します。

```powershell
$env:HOIKUICT_ENV = "development"
$env:HOIKUICT_ENABLE_MOCK_AUTH = "1"
$env:HOIKUICT_KIOSK_ACCESS_MODE = "open"
python -m ruff check .
python -m pytest -q --ignore=gen_bunnrei
```

macOS / Linuxでは次を使います。

```bash
export HOIKUICT_ENV=development
export HOIKUICT_ENABLE_MOCK_AUTH=1
export HOIKUICT_KIOSK_ACCESS_MODE=open
python -m ruff check .
python -m pytest -q --ignore=gen_bunnrei
```

ローカルβ用に設定した認証モードなどが残る場合は、新しいシェルで実行します。`pyproject.toml` がテスト探索範囲とRuffの検査規則を定め、`.github/workflows/ci.yml` がCIの実行条件です。変更した機能は関連テストで確認し、リリース時は全体の確認結果を記録します。

## データを作り直すとき

既存DBを削除する前に、新しいファイル名へ `HOIKUICT_DATABASE_URL` を切り替えると、元の検証状態を残して空DBを確認できます。業務DB以外に施設文例DB・添付もあるため、全環境を分ける場合は[保存先一覧](architecture.md#storage)を参照してください。

SQLiteの稼働中DBはWALを使います。単純なDBファイルのコピーをバックアップ手順にせず、[バックアップ・復元仕様](backup-restore-spec.md)に従います。

## 実装時に守る境界

- 保護者の園児アクセスは明示的なリンクを確認し、家庭への所属だけで許可しない。
- 新しいフォームではCSRF、閲覧専用ユーザー、直接URLアクセスを確認する。
- 業務日付は `time_utils.local_today()`、既存の登降園時刻は `local_naive_now()`、監査時刻は `utc_now()` を使う。
- データ・認証・添付の保存先を変える場合はバックアップ対象も更新する。
- URL・機能・運用条件を変えたら、同じ変更でドキュメントも更新する。

MkDocsのプレビュー・リンク検査は[ドキュメントの更新](documentation.md)を参照してください。
