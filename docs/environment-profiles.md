# ローカル環境の設定

機能コードは共通とし、認証方式・DB・保存先・ポート・公開条件を環境設定で分けます。「β」は用途の名前で、`HOIKUICT_ENV=beta` という設定値はありません。使用できる値は `development`、`test`、`production` です。

| 環境 | 用途 | 認証・配送 | DBの例 |
| --- | --- | --- | --- |
| ローカルモック | 架空データで画面を確認 | モック認証、通知capture | `hoikuict-dev.db` |
| ローカル認証β | 登録・承認・パスワードを確認 | 職員・保護者local_password、メールcapture | `hoikuict-beta-auth.db` |
| 公開デモ | 外部向けの架空データ環境 | 公開先固有の設定と制限 | デモ専用DB |
| TrueNASの限定運用試験 | HTTPS・SMTP・永続化・復元を確認 | production、local_password、SMTP | 専用runtime内のDB |

ローカルβも架空データ用です。実データを扱う試験は[TrueNAS導入](truenas-beginner-installation-guide.md)と[運用試験条件](pilot-deployment-spec-v2.md)に沿って別途準備します。

## モック環境

[開発手順](development.md)の `.env.example` を使います。既定のDBは `hoikuict.db` なので、別のファイルを使う場合は `HOIKUICT_DATABASE_URL` を明示します。すでに保存済みのDBにデモシードを実行しないでください。

## ローカル認証βの初回準備

1. [開発手順](development.md)で `venv` と依存ライブラリを用意します。
2. 初回だけ `.env.beta.example` を `.env.beta.local` へコピーします。
3. 次の2つの鍵のプレースホルダーを、それぞれ生成した固定値へ置き換えます。
4. DB・ポート・メール設定を確認します。

```powershell
Copy-Item .env.beta.example .env.beta.local
.\venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

この生成コマンドを鍵ごとに実行し、出力は自分の設定ファイルへ保存します。起動のたびに再生成しません。

| 設定 | ローカルβで使う値・意味 |
| --- | --- |
| `HOIKUICT_ENV` | `development` |
| `HOIKUICT_ENABLE_MOCK_AUTH` | `0` |
| `HOIKUICT_STAFF_AUTH_MODE` / `HOIKUICT_PARENT_AUTH_MODE` | 両方 `local_password` |
| `HOIKUICT_LOGIN_THROTTLE_HMAC_KEY` | 32バイト以上の固定の秘密値 |
| `HOIKUICT_SECRET_KEY` | 32文字以上の固定の秘密値 |
| `HOIKUICT_DATABASE_URL` | `sqlite:///./hoikuict-beta-auth.db` |
| `HOIKUICT_CSRF_ENFORCE` / `HOIKUICT_COOKIE_SECURE` | ローカルHTTPでは `1` / `0` |
| `HOIKUICT_KIOSK_ACCESS_MODE` / `HOIKUICT_PUSH_TRANSPORT` | 最初は `disabled` / `disabled` |
| `HOIKUICT_PARENT_MAIL_TRANSPORT` | `capture`（実メールを送信しない） |
| `HOIKUICT_PARENT_REGISTRATION_BASE_URL` | `http://127.0.0.1:8001` |

## 初期管理者を作る {#bootstrap}

新しい空のβ用DBに、最初の管理者を作成します。CLIは `main.py` のdotenv読込を通らないため、**CLIをimportする前にβ用設定を読み込みます**。

```powershell
.\venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('.env.beta.local', override=True); from scripts.auth_user import main; raise SystemExit(main(['bootstrap-admin']))"
```

画面の質問へ表示名・メール・ログインID・作成理由・実行者・承認者を入力します。表示された有効化コードを本人が `/staff/activate` へ入力してパスワードを設定します。

職員がすでに存在するDBでは追加の初期管理者は作れません。既存職員を有効化する場合だけ、上の `bootstrap-admin` を `activate-staff` に変えます。稼働DBを初期化して回避しないでください。

## 起動・再起動

モック用の環境変数が残っていない新しいPowerShellで実行します。

```powershell
.\scripts\start_beta.ps1
```

既定URLは `http://127.0.0.1:8001/` です。開発中の自動再読込は `-Reload`、ポート変更は `-Port 8002` を指定します。ポートを変えた場合は登録用URLも合わせます。

このスクリプトは **`venv\Scripts\python.exe`** と **`.env.beta.local`** を使います。`.venv` の名前では見つかりません。別名の仮想環境やmacOS / Linuxでは、そのPythonから直接起動できます。

```bash
python -m uvicorn main:app --env-file .env.beta.local --host 127.0.0.1 --port 8001
```

Uvicornのenv-fileより、既存のプロセス環境変数が優先されます。意図しないモック画面やDBが開く場合は、シェルの設定を確認します。

起動スクリプトはシードや管理者の再作成を行いません。アプリの起動処理は必要なテーブル・スキーマを作成し、既存データの整合処理を行います。保存先が同じならアカウント・資格情報・業務データを継続利用します。

## プロキシと保存先

リバースプロキシを使う場合だけ `FORWARDED_ALLOW_IPS` を送信元IP/CIDRへ限定して設定します。直接アクセスのローカルβでは設定不要です。本番は[セキュリティ設定](security.md)に従います。

DBの切り替えだけでは添付や施設文例DBの保存先は分かれません。同じPCで環境を併用する場合は[コード構成・データ保存](architecture.md#storage)も確認してください。DB、WAL、鍵、`.env*.local` はGitで移送せず、コードと設定例だけを共有します。
