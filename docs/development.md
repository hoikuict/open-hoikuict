# 開発者向けセットアップ

## 必要なもの

- Python 3.11 以上
- Git
- ローカル開発用のブラウザ

## セットアップ

```bash
git clone https://github.com/hoikuict/open-hoikuict.git
cd open-hoikuict
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
uvicorn main:app --reload
```

Windows PowerShell の場合:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env
uvicorn main:app --reload
```

起動後、ブラウザで <http://127.0.0.1:8000/> を開きます。

## テスト

```bash
ruff check .
python -m pytest -q --ignore=gen_bunnrei
```

## データベース

デフォルトではローカルの SQLite ファイル `hoikuict.db` を使います。開発中にデータを作り直したい場合は、事前にバックアップしたうえで削除してください。

```bash
cp hoikuict.db hoikuict.db.bak
rm hoikuict.db
uvicorn main:app --reload
```

## 100人規模デモデータ

```bash
python -m scripts.seed_demo_100 --wipe-all
uvicorn main:app --reload
```

`--wipe-all` は対応テーブルの既存データを削除します。本番DBや実在データが入ったDBでは絶対に使わないでください。

公開デモ用の seed では、カレンダー予定を実行月の前後2か月、登降園データと保護者連絡を実行日の3か月前から当日まで自動生成します。アプリ起動時の自動 seed は行いません。新しいローカルDBへデモデータが必要な場合は、アプリ起動前に上記コマンドを明示的に実行してください。

## 開発時の注意

- 実在する個人情報をコミットしない
- スクリーンショットに実在情報を含めない
- 権限、監査ログ、エラー時の戻りやすさを確認する
- 保護者画面で他家庭の情報が見えないことを常に確認する

## 開発用セキュリティ設定

ローカルHTTPでモック認証とキオスクを使う場合は、起動前に次を設定します。本番では使用しません。

```powershell
$env:HOIKUICT_ENV = "development"
$env:HOIKUICT_ENABLE_MOCK_AUTH = "1"
$env:HOIKUICT_KIOSK_ACCESS_MODE = "open"
$env:HOIKUICT_CSRF_ENFORCE = "0"
```

### 職員ローカル認証を試す

モックの代わりにArgon2idの職員認証を使う場合は、開発用DBを用意して次を設定します。

```powershell
$env:HOIKUICT_ENABLE_MOCK_AUTH = "0"
$env:HOIKUICT_STAFF_AUTH_MODE = "local_password"
$env:HOIKUICT_LOGIN_THROTTLE_HMAC_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:HOIKUICT_COOKIE_SECURE = "0"
python -m scripts.auth_user bootstrap-admin
uvicorn main:app --reload
```

CLIはパスワードを受け取りません。一度だけ表示される6文字・30分有効の有効化コードを管理者本人が `/staff/activate` へ入力し、表示されたログインIDを確認・必要に応じて修正してから、8文字以上のパスワードを設定します。productionではHTTPS、CSRF、32バイト以上のHMAC鍵、施設承認済みのローカルパスワード禁止リストを必ず設定してください。

既に職員やデモ管理者が存在するDBでは、`bootstrap-admin`は追加管理者を作らず停止します。その場合は既存職員を選択して有効化コードを発行します。

```powershell
python -m scripts.auth_user activate-staff
```

ローカル認証で管理者ログイン後は、`/staff/users` の「認証管理」から初期設定コードとパスワード再設定コードを発行できます。管理者は本人の新しいパスワードを設定・閲覧せず、一回限りのコードだけを本人へ渡します。

## 開発上の時刻規約

- 園の業務日付は `time_utils.local_today()` を使う。
- 既存DBの登降園時刻は `time_utils.local_naive_now()` を使う。
- `created_at` / `updated_at` 等の監査時刻は `time_utils.utc_now()` を使う。
- `date.today()` / naiveな `datetime.now()` を業務コードで直接使わない。
