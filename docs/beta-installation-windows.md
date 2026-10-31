# β版の導入：Windows 11

Windows 11（x64）へ、新しいローカルβ環境を作ります。最初に[対象・設定・確認項目](beta-installation.md)を確認してください。使用するのはPython 3.12、SQLite、PowerShellです。

**到達点：このPCのブラウザーから、パスワード認証でログインし、架空データを保存・再表示できること。** 園内の別端末からの利用には[追加の構築](beta-installation.md#facility-use)が必要です。

## 1. 準備する

- Windowsを更新し、ソフトウェアを導入できるユーザーでサインインします。
- インストール用のインターネット接続、ブラウザー、退避用の空き容量を用意します。容量・性能の正式な最小要件は未測定です。
- スタートメニューから「PowerShell」を開きます。以下は通常権限のPowerShellで行います。

[Git for Windows公式ページ](https://git-scm.com/install/windows)からx64版をインストールします。Pythonが未導入なら、[Python公式のWindows導入方法](https://docs.python.org/3/using/windows.html)に従ってPython Install Managerを入れます。

インストール後はPowerShellを開き直します。既に `py -3.12 --version` が成功する場合、Pythonの追加導入は不要です。未導入ならInstall Managerから次を実行します。

```powershell
pymanager install 3.12
```

次の両方が成功することを確認します。

```powershell
git --version
py -3.12 --version
```

Pythonは `Python 3.12.x` と表示されれば次へ進めます。`pymanager` は旧Python Launcherの `py` と衝突しにくい管理コマンドです。見つからない場合はInstall Managerの導入とPowerShellの開き直しを確認します。

## 2. β専用フォルダーへ取得する

ユーザーフォルダー直下の `hoikuict-beta` を使用します。同名フォルダーが既にある場合は初回導入を続行せず、既存の試用環境か確認します。OneDrive等の同期フォルダーは選びません。

```powershell
Set-Location $env:USERPROFILE
if (Test-Path -LiteralPath .\hoikuict-beta) { throw 'hoikuict-beta already exists' }
git clone https://github.com/hoikuict/open-hoikuict.git hoikuict-beta
```

cloneが成功したら、基準コミットへ切り替えます。

```powershell
Set-Location .\hoikuict-beta
git checkout --detach 7cafb09cad1f1eee972883f2c3fac14673873b35
git rev-parse HEAD
```

最後の表示が指定した40桁と一致することを確認し、[導入記録](beta-installation.md)へ転記します。`detached HEAD` は版を固定した状態を示す案内で、ここでは正常です。この手順書の作成基準であり、正式βタグではありません。

以降はこのフォルダー内で実行します。新しくPowerShellを開いた場合は、まず次を実行します。

```powershell
Set-Location (Join-Path $env:USERPROFILE 'hoikuict-beta')
```

## 3. Python環境を作る

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m pip check
```

各コマンドのエラーがないことを確認します。最後に `No broken requirements found.` と表示されます。試用の実行に `requirements-dev.txt` は不要です。

この手順は仮想環境のPythonを直接指定するので、`Activate.ps1` やPowerShellの実行ポリシー変更は不要です。

## 4. β設定と秘密鍵を作る

まず、別環境の設定がPowerShellに残っていないか、**変数名だけ**を確認します。

```powershell
Get-ChildItem Env: |
    Where-Object { $_.Name -match '^(HOIKUICT_|HOIKU_|FORWARDED_ALLOW_IPS$)' } |
    Select-Object -ExpandProperty Name
```

何も表示されなければ続行します。表示された場合は環境設定の担当者とその用途を確認し、β用のシェルへ他環境の値が継承されない状態にします。設定ファイルよりプロセスの環境変数が優先されます。

次のブロックを、`@'` から最後の行までまとめて実行します。秘密鍵を画面に表示せず、UTF-8の `.env.beta.local` へ保存します。既存ファイルは上書きしません。

```powershell
@'
from pathlib import Path
import secrets

source = Path('.env.beta.example').read_text(encoding='utf-8')
keys = {
    'HOIKUICT_SECRET_KEY': secrets.token_urlsafe(32),
    'HOIKUICT_LOGIN_THROTTLE_HMAC_KEY': secrets.token_urlsafe(32),
}
lines = []
for line in source.splitlines():
    name = line.partition('=')[0]
    lines.append(name + '=' + keys[name] if name in keys else line)
with Path('.env.beta.local').open('x', encoding='utf-8') as output:
    output.write('\n'.join(lines) + '\n')
print('Created .env.beta.local')
'@ | .\venv\Scripts\python.exe -
```

`Created .env.beta.local` が表示されたら、初回だけ次の設定検査を実行します。

```powershell
.\venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('.env.beta.local', override=True); from security_config import validate_runtime_security; validate_runtime_security(); print('Settings OK')"
```

`Settings OK` を確認します。初期値と保存先は[共通の設定表](beta-installation.md#configuration)を参照します。`.env.beta.local` は秘密情報です。チャットやIssueに内容を貼らず、起動のたびに再作成しません。

## 5. 初期管理者を作る

空のβ専用DBに対して、初回だけ実行します。

```powershell
.\venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('.env.beta.local', override=True); from scripts.auth_user import main; raise SystemExit(main(['bootstrap-admin']))"
```

[入力する6項目の例](beta-installation.md#administrator)に沿って回答し、内容を確認して `yes` と入力します。CLIを読み込む前にβ設定を読み込むことが必要なので、上のコマンドを省略せず使います。

「初期管理者を作成しました」と有効化コードが表示されたら、30分以内に次の章へ進みます。コードは一度だけ表示されます。

## 6. 起動してログインする

```powershell
.\venv\Scripts\python.exe -m uvicorn main:app --env-file .env.beta.local --host 127.0.0.1 --port 8001
```

`Application startup complete.` が表示されたら、PowerShellを開いたままブラウザーで操作します。

1. [起動確認](http://127.0.0.1:8001/healthz)で `{"status":"ok"}` を確認します。
2. [職員の有効化](http://127.0.0.1:8001/staff/activate)で有効化コードを入力します。続く画面で対象職員・ログインIDを確認し、自分で決めた8文字以上のパスワードを確認欄にも入力して設定します。
3. [職員ログイン](http://127.0.0.1:8001/staff/login)で、同じログインID・パスワードを使います。
4. [初回の動作確認表](beta-installation.md#acceptance)に沿って、架空データの登録・再表示を確認します。

アクセス先は `127.0.0.1:8001` に揃えます。PC名や `localhost` と混ぜて操作しません。`--reload` は付けません。

## 7. 停止・翌日の起動

停止するときは、アプリを起動したPowerShellで `Ctrl+C` を押します。`Application shutdown complete.` が表示され、入力待ちに戻るまで待ちます。

次回はPowerShellを開き、以下だけを実行します。

```powershell
Set-Location (Join-Path $env:USERPROFILE 'hoikuict-beta')
.\venv\Scripts\python.exe -m uvicorn main:app --env-file .env.beta.local --host 127.0.0.1 --port 8001
```

管理者や設定を再作成する必要はありません。Windowsの再起動後は手動で起動します。PCがスリープすると利用できなくなります。

既存の `scripts/start_beta.ps1` も同じ `venv`・設定ファイルを使います。上の直接起動なら、そのスクリプトの実行可否に依存しません。

## 8. 停止して退避する {#backup}

この標準構成の架空データを保存する方法です。第7章で停止し、同じフォルダーを使うCLI等も終了してから実行します。保存先を変更している場合は[共通の退避条件](beta-installation.md#maintenance)を先に確認します。

```powershell
$betaRoot = Join-Path $env:USERPROFILE 'hoikuict-beta'
$betaBackupRoot = Join-Path $env:USERPROFILE 'hoikuict-beta-backups'
New-Item -ItemType Directory -Force -Path $betaBackupRoot | Out-Null
$betaBackupPath = Join-Path $betaBackupRoot (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
if (Test-Path -LiteralPath $betaBackupPath) { throw 'Backup destination already exists' }
Copy-Item -LiteralPath $betaRoot -Destination $betaBackupPath -Recurse -Force -ErrorAction Stop
Get-Item -Force -LiteralPath (Join-Path $betaBackupPath '.env.beta.local'), (Join-Path $betaBackupPath 'hoikuict-beta-auth.db')
```

最後に退避先の設定ファイルとDBが表示されること、エクスプローラーで `data`・`storage` 内の使用済みファイルも含まれることを確認します。日時・導入コミットを記録します。フォルダー全体なので、仮想環境も含めた容量が必要です。

同じディスク上の退避だけではPC故障に備えられません。必要な世代は、アクセスを管理した別媒体にもコピーします。稼働中の `.db` だけをコピーする方法には置き換えません。

### 復旧を試す

1. アプリと、このDBへ書き込む処理をすべて停止します。
2. エクスプローラーで現在の `hoikuict-beta` を、重複しない `hoikuict-beta-before-restore-日時` 等へ名前変更して残します。
3. 退避した日時フォルダーをユーザーフォルダー直下へ**コピー**し、コピー側を `hoikuict-beta` に名前変更します。直下に `main.py` と `.env.beta.local` がある階層へ戻します。
4. 元と同じPC・同じパスで第7章の起動コマンドを実行します。仮想環境を再利用できない場合は、復旧した側の `venv` を別名に退避し、第3章で作り直します。
5. 退避時のログイン、架空データ、添付を確認して結果を記録します。初期管理者・秘密鍵は再作成しません。

これは停止したローカル試用環境を戻す手順です。別PCへの移行や稼働施設の復旧は[バックアップ検証手順](backup-verification-guide.md)に従います。

## 9. つまずいたとき

| 症状 | 確認・対処 |
| --- | --- |
| `git` / `py` が見つからない | 導入後にPowerShellを開き直し、第1章の版確認をする |
| Pythonが3.12でない | `py -3.12` を指定して `venv` を作ったか確認する |
| `No module named ...` | 第3章のインストールが成功したか確認し、`venv\Scripts\python.exe` を使う |
| `.env.beta.local` が既にある | 作り直さず、既存設定と第4章の検査結果を確認する |
| `productionセキュリティ設定が不正` | 第2章のフォルダーと `--env-file`、継承された環境変数を確認する |
| 職員を選ぶモック画面になる | 第4章の環境変数と、起動コマンド・ポートを確認する |
| `WinError 10048` / ポート使用中 | 以前起動したβが残っていないか確認して停止する。別のアプリを無断終了しない |
| ブラウザーが接続できない | 起動完了ログ、`http`、`127.0.0.1`、`8001`、PCのスリープを確認する |
| ログインが維持されない・CSRFエラー | URLを統一し、ローカル設定のCookie Secureが `0` か確認。再ログインしてフォームを開き直す |
| 有効化コードが期限切れ | アプリを停止し、下の再発行コマンドを使う |
| 招待・復旧メールが届かない | 初期の `capture` は実メールを送らない。[SMTP等の追加準備](beta-installation.md#facility-use)を確認する |
| バックアップ画面の依頼が進まない | この構成ではworkerを起動していない。第8章の停止退避を使う |

既存職員の有効化コードの再発行は、対象を確認して次を使います。

```powershell
.\venv\Scripts\python.exe -c "from dotenv import load_dotenv; load_dotenv('.env.beta.local', override=True); from scripts.auth_user import main; raise SystemExit(main(['activate-staff']))"
```

その後、第6章の起動・有効化へ戻ります。DBを削除して解決しないでください。更新は[共通の更新手順](beta-installation.md#maintenance)を使います。
