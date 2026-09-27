# β版の導入：Ubuntu 24.04 LTS

Ubuntu 24.04 LTS（amd64）へ、新しいローカルβ環境を作ります。最初に[対象・設定・確認項目](beta-installation.md)を確認してください。使用するのはPython 3.12、SQLite、Bashです。他のLinuxディストリビューションは、この手順書の対象に含めていません。

**到達点：このPCのブラウザーから、パスワード認証でログインし、架空データを保存・再表示できること。** 園内の別端末からの利用には[追加の構築](beta-installation.md#facility-use)が必要です。

## 1. 準備する

OSを更新し、`sudo` を使える一般ユーザーでログインします。インストール用のインターネット接続、ブラウザー、退避用の空き容量を用意します。容量・性能の正式な最小要件は未測定です。

端末を開き、OSを確認します。

```bash
cat /etc/os-release
```

`Ubuntu`、`24.04` であることを確認して、必要なパッケージを入れます。

```bash
sudo apt update
sudo apt install git python3.12 python3.12-venv ca-certificates
git --version
python3.12 --version
```

Gitの版と `Python 3.12.x` が表示されれば次へ進めます。Ubuntu 24.04では[公式パッケージのpython3.12-venv](https://packages.ubuntu.com/noble/python3.12-venv)を使用できます。アプリのライブラリは[UbuntuのPython環境案内](https://documentation.ubuntu.com/ubuntu-for-developers/howto/python-setup/)に沿い、仮想環境へ入れます。

`sudo` を使うのはOSパッケージの導入です。これ以降のclone・pip・アプリ起動は一般ユーザーで行います。

## 2. β専用フォルダーへ取得する

ユーザーのホーム直下の `hoikuict-beta` を使用します。同名のフォルダーがある場合は既存の試用環境か確認し、新規導入を続行しません。ローカルディスクを使い、同期フォルダーやネットワーク共有は選びません。

```bash
cd "$HOME"
test ! -e hoikuict-beta && git clone https://github.com/hoikuict/open-hoikuict.git hoikuict-beta
```

cloneが成功した場合だけ、基準コミットへ切り替えます。同名フォルダーがあってcloneされなかった場合は、ここで止めます。

```bash
cd "$HOME/hoikuict-beta"
git checkout --detach 7cafb09cad1f1eee972883f2c3fac14673873b35
git rev-parse HEAD
```

最後の表示が指定した40桁と一致することを確認し、[導入記録](beta-installation.md)へ転記します。`detached HEAD` は版を固定した状態を示す案内で、ここでは正常です。この手順書の作成基準であり、正式βタグではありません。

以降はこのフォルダー内で実行します。端末を開き直した場合は `cd "$HOME/hoikuict-beta"` で戻ります。

## 3. Python環境を作る

```bash
python3.12 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/python -m pip install -r requirements.txt
./venv/bin/python -m pip check
```

各コマンドのエラーがないことを確認します。最後に `No broken requirements found.` と表示されます。試用の実行に `requirements-dev.txt` は不要です。

仮想環境のPythonを直接指定するので、`source venv/bin/activate` は不要です。`sudo pip` や `--break-system-packages` は使いません。

## 4. β設定と秘密鍵を作る

まず、別環境の設定が端末に残っていないか、**変数名だけ**を確認します。

```bash
./venv/bin/python -c "import os; print('\n'.join(sorted(k for k in os.environ if k.startswith(('HOIKUICT_', 'HOIKU_')) or k == 'FORWARDED_ALLOW_IPS')))"
```

何も表示されなければ続行します。表示された場合は環境設定の担当者とその用途を確認し、β用の端末へ他環境の値が継承されない状態にします。設定ファイルよりプロセスの環境変数が優先されます。

次のブロックを最後の `PY` までまとめて実行します。秘密鍵を画面に表示せず、UTF-8の `.env.beta.local` へ保存します。既存ファイルは上書きしません。

```bash
umask 077
./venv/bin/python - <<'PY'
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
PY
chmod 600 .env.beta.local
```

`Created .env.beta.local` が表示されたら、初回だけ次の設定検査を実行します。

```bash
./venv/bin/python -c "from dotenv import load_dotenv; load_dotenv('.env.beta.local', override=True); from security_config import validate_runtime_security; validate_runtime_security(); print('Settings OK')"
```

`Settings OK` を確認します。初期値と保存先は[共通の設定表](beta-installation.md#configuration)を参照します。`.env.beta.local` は秘密情報です。チャットやIssueに内容を貼らず、起動のたびに再作成しません。

## 5. 初期管理者を作る

空のβ専用DBに対して、初回だけ実行します。

```bash
./venv/bin/python -c "from dotenv import load_dotenv; load_dotenv('.env.beta.local', override=True); from scripts.auth_user import main; raise SystemExit(main(['bootstrap-admin']))"
```

[入力する6項目の例](beta-installation.md#administrator)に沿って回答し、内容を確認して `yes` と入力します。CLIを読み込む前にβ設定を読み込むことが必要なので、上のコマンドを省略せず使います。

「初期管理者を作成しました」と有効化コードが表示されたら、30分以内に次の章へ進みます。コードは一度だけ表示されます。

## 6. 起動してログインする

```bash
./venv/bin/python -m uvicorn main:app --env-file .env.beta.local --host 127.0.0.1 --port 8001
```

`Application startup complete.` が表示されたら、端末を開いたままブラウザーで操作します。

1. [起動確認](http://127.0.0.1:8001/healthz)で `{"status":"ok"}` を確認します。
2. [職員の有効化](http://127.0.0.1:8001/staff/activate)で有効化コードを入力します。続く画面で対象職員・ログインIDを確認し、自分で決めた8文字以上のパスワードを確認欄にも入力して設定します。
3. [職員ログイン](http://127.0.0.1:8001/staff/login)で、同じログインID・パスワードを使います。
4. [初回の動作確認表](beta-installation.md#acceptance)に沿って、架空データの登録・再表示を確認します。

アクセス先は `127.0.0.1:8001` に揃えます。PC名や `localhost` と混ぜて操作しません。`--reload` は付けません。

Ubuntu Serverなどブラウザーがない環境では、SSH接続できる確認用PCから次の転送を使えます。`ubuntu-user` と `ubuntu-host` を実際のSSHユーザー・接続先へ置き換え、転送を開いたまま確認用PCのブラウザーで上のURLへアクセスします。

```bash
ssh -N -L 8001:127.0.0.1:8001 ubuntu-user@ubuntu-host
```

これは担当者の確認用です。保護者・職員へ配布する施設URLの代わりにはなりません。転送元PCの8001番が使用中の場合は、その用途を確認してから解消します。

## 7. 停止・翌日の起動

停止するときは、アプリを起動した端末で `Ctrl+C` を押します。`Application shutdown complete.` が表示され、入力待ちに戻るまで待ちます。

次回は端末を開き、以下だけを実行します。

```bash
cd "$HOME/hoikuict-beta"
umask 077
./venv/bin/python -m uvicorn main:app --env-file .env.beta.local --host 127.0.0.1 --port 8001
```

管理者や設定を再作成する必要はありません。OSの再起動後は手動で起動します。SSH端末の切断やPCのスリープ中の継続利用も、この手順では構成していません。

## 8. 停止して退避する {#backup}

この標準構成の架空データを保存する方法です。第7章で停止し、同じフォルダーを使うCLI等も終了してから実行します。保存先を変更している場合は[共通の退避条件](beta-installation.md#maintenance)を先に確認します。

```bash
umask 077
mkdir -p "$HOME/hoikuict-beta-backups"
if beta_backup_path=$(mktemp -d "$HOME/hoikuict-beta-backups/$(date +%Y%m%d-%H%M%S)-XXXXXX"); then
    cp -a "$HOME/hoikuict-beta/." "$beta_backup_path/" &&
        ls -ld "$beta_backup_path/.env.beta.local" "$beta_backup_path/hoikuict-beta-auth.db"
fi
```

`mktemp` で保存先が作成でき、`cp` がエラーなく終了したことを確認します。最後に退避先の設定ファイルとDBが表示されること、ファイルマネージャー等で `data`・`storage` 内の使用済みファイルも含まれることを確認します。日時・導入コミットを記録します。フォルダー全体なので、仮想環境も含めた容量が必要です。

同じディスク上の退避だけではPC故障に備えられません。必要な世代は、アクセスを管理した別媒体にもコピーします。稼働中の `.db` だけをコピーする方法には置き換えません。

### 復旧を試す

1. アプリと、このDBへ書き込む処理をすべて停止します。
2. 現在の `$HOME/hoikuict-beta` を、重複しない `hoikuict-beta-before-restore-日時` 等へ名前変更して残します。
3. 退避した日時フォルダーをホーム直下へ**コピー**し、コピー側を `hoikuict-beta` に名前変更します。隠しファイルも含め、直下に `main.py` と `.env.beta.local` がある階層へ戻します。
4. 元と同じPC・同じパス・同じユーザーで第7章の起動コマンドを実行します。仮想環境を再利用できない場合は、復旧した側の `venv` を別名に退避し、第3章で作り直します。
5. 退避時のログイン、架空データ、添付を確認して結果を記録します。初期管理者・秘密鍵は再作成しません。

これは停止したローカル試用環境を戻す手順です。別PCへの移行や稼働施設の復旧は[バックアップ検証手順](backup-verification-guide.md)に従います。

## 9. つまずいたとき

| 症状 | 確認・対処 |
| --- | --- |
| `python3.12-venv` が見つからない | Ubuntu 24.04か確認。`apt update` のエラーを解消し、標準の `universe` が有効かOS管理者に確認する |
| `ensurepip is not available` | `python3.12-venv` の導入を確認し、作成に失敗した仮想環境を作り直す |
| `externally-managed-environment` | OSのPythonでpipを実行している。`./venv/bin/python -m pip` を使う |
| `Permission denied` | 一般ユーザーで作成したフォルダーか、所有者・書込み権限を確認。`sudo` でアプリを起動して回避しない |
| `.env.beta.local` が既にある | 作り直さず、既存設定と第4章の検査結果を確認する |
| `productionセキュリティ設定が不正` | 第2章のフォルダーと `--env-file`、継承された環境変数を確認する |
| 職員を選ぶモック画面になる | 第4章の環境変数と、起動コマンド・ポートを確認する |
| `Address already in use` | 以前起動したβやSSH転送が残っていないか確認。別のアプリを無断終了しない |
| 接続できない | 起動完了ログ、URL、ポート、PCのスリープ、Serverの場合はSSH転送を確認する |
| ログインが維持されない・CSRFエラー | URLを統一し、ローカル設定のCookie Secureが `0` か確認。再ログインしてフォームを開き直す |
| 有効化コードが期限切れ | アプリを停止し、下の再発行コマンドを使う |
| 招待・復旧メールが届かない | 初期の `capture` は実メールを送らない。[SMTP等の追加準備](beta-installation.md#facility-use)を確認する |
| バックアップ画面の依頼が進まない | この構成ではworkerを起動していない。第8章の停止退避を使う |

既存職員の有効化コードの再発行は、対象を確認して次を使います。

```bash
./venv/bin/python -c "from dotenv import load_dotenv; load_dotenv('.env.beta.local', override=True); from scripts.auth_user import main; raise SystemExit(main(['activate-staff']))"
```

その後、第6章の起動・有効化へ戻ります。DBを削除して解決しないでください。更新は[共通の更新手順](beta-installation.md#maintenance)を使います。
