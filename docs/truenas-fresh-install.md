# TrueNASへ初期状態で導入する

作成日: 2026-09-06。対象はベータ公開に向けた実機検証の開始。
実機情報・接続先の確認前に用意した手順であり、実機試験の合格記録ではない。

## 今回の初期状態

園児・家庭・保護者・職員・クラス・業務記録が空の状態から、初期管理者を1人作成して始める。
開発PCのDB、添付、`.env`、`.env.beta.local`は移さない。通常起動は業務デモデータを投入しない。
保育計画で使う配布済み文例DBは含むため、すべてのSQLiteファイルが0件という意味ではない。
園固有の変更を加える前の基準環境として、設定・イメージ・検証結果を残す。

構成は既存の[運用試験仕様の改訂版](pilot-deployment-spec-v2.md)に合わせた
TrueNAS / Dockge / Cloudflare Tunnel・Access / SMTPを基準とする。
接続経路が異なる場合は、実機の構成を確認してHTTPSとプロキシ設定を合わせる。
最初は架空の業務データで確認する。

## 導入前に埋める値

| 項目 | 記録欄 |
| --- | --- |
| TrueNASの種類・バージョン、管理IP | 未確認 |
| Docker / Compose / Dockgeのバージョン、stack保存先 | 未確認 |
| runtime用プール、バックアップ先 | 未確認 |
| 検証用HTTPSホスト名、Tunnel・Accessの準備状況 | 未確認 |
| SMTP接続先、送信元、受信用テストメール | 未確認 |
| 展開するGit SHA、アプリimage ID | 未確定 |

TrueNASのDockerベースのAppsを前提にする。COREや古いKubernetesベースのSCALEではこの手順を直接実行しない。
標準AppsにもCompose YAMLによる導入機能があるが、本手順は`.env`を使えるDockge / Compose CLI向け。
標準Appsへそのまま貼り付けず、そちらを使う場合はホスト上のimage、変数、ファイルパスを別途合わせる。
公式資料: [Custom Apps](https://apps.truenas.com/managing-apps/installing-custom-apps/)、
[App Storage](https://apps.truenas.com/getting-started/app-storage/)。

## 1. ソースと保存先を分離する

以下の`<...>`は実環境の値へ置き換える。以降のコマンドはTrueNASのLinuxシェルで実行する。

TrueNASのDatasets画面で専用の新規datasetを用意する。
既存のデモや稼働環境のdirectoryを再利用せず、新しい名前を選ぶ。
runtime配下のdataとstorageは同じdataset内のdirectoryとし、一緒にsnapshotを取得できるようにする。

```text
/mnt/<pool>/apps/dockge/stacks/open-hoikuict-pilot/
  compose.yaml
  .env
  source/                  # 展開する版だけのcheckout
/mnt/<pool>/apps/open-hoikuict-pilot/runtime/
  data/                    # 新規・空
  storage/                 # 新規・空
/mnt/<pool>/apps/open-hoikuict-pilot/secrets/
  tunnel-token
  password-blocklist.txt
/mnt/<backup-pool>/backup/open-hoikuict-pilot/sets/
```

runtimeはローカルZFS上に置き、DBをSMB/NFS経由で使用しない。
Dockgeのstack pathはホストとcontainer内で同じabsolute pathにする。

展開する版をcommitで固定してから、専用checkoutを作る。
開発PCに未コミット変更がある場合、その変更は`git clone`では転送されない。
認証変更などを含める版と含めない版を混同せず、必要な変更を整理してからSHAを決める。

```bash
cd /mnt/<pool>/apps/dockge/stacks/open-hoikuict-pilot
git clone https://github.com/hoikuict/open-hoikuict.git source
git -C source checkout --detach <deploy-full-sha>
git -C source status --short
```

最後の出力が空で、必要なファイルがそのSHAに含まれることを確認する。
この新手順・Compose・`.dockerignore`も展開する版に含める。
初回の空stackで次を実行する。`-n`で既存設定の上書きを避ける。

```bash
cp -n source/deploy/truenas/compose.yaml compose.yaml
cp -n source/deploy/truenas/.env.example .env
chmod 600 .env
docker build -t open-hoikuict:<deploy-full-sha> ./source
docker image inspect open-hoikuict:<deploy-full-sha> --format '{{.Id}}'
docker run --rm --network none --entrypoint id open-hoikuict:<deploy-full-sha>
sha256sum compose.yaml
```

実測したUID/GIDにruntime/data、runtime/storage、backup出力先の書込み権限を与える。
secretsのblocklistはappの実行userから読める必要がある。ホスト全体の権限を変更しない。
初回起動前のdata・storageが空であることをTrueNAS側で確認する。

## 2. 設定を完成させる

[Compose](../deploy/truenas/compose.yaml)と[環境変数雛形](../deploy/truenas/.env.example)を使う。
`.env`のすべての`<...>`を置き換える。リポジトリ直下のローカル用設定は使わない。

- `APP_IMAGE`: 直前にbuildした`open-hoikuict:<deploy-full-sha>`。
- `BACKUP_GIT_SHA` / `BACKUP_APP_IMAGE` / `BACKUP_COMPOSE_SHA256`: ソースSHA / image ID / ComposeのSHA-256実測値。
- `APP_RUNTIME_PATH` / `APP_SECRETS_PATH` / `BACKUP_SET_PATH`: 新規に用意したabsolute path。
- `PILOT_HOSTNAME`: スキームやパスを含めない検証用ホスト名。
- `PILOT_NETWORK_CIDR`: LAN・VPN・他のDocker networkと重複しない専用CIDR。
- `HOIKU_NURSERY_REF`: 検証施設の識別名。
- `HOIKUICT_SECRET_KEY`と`HOIKUICT_LOGIN_THROTTLE_HMAC_KEY`: 用途別の固定ランダム値。各32バイト以上を推奨し、再起動時に変更しない。
- SMTPの接続先・587等のポート・認証情報・送信元: STARTTLSを使える設定。管理者再設定メールも共用する。
- `CLOUDFLARED_IMAGE`: 実際に取得・確認した`cloudflare/cloudflared@sha256:...`。

秘密値はpassword manager等で生成・保管する。`.env`で`$`などを含む値はComposeの引用規則に従う。
実値をチャットや作業ログに貼らない。

`password-blocklist.txt`は空でない禁止パスワード一覧を用意する。
Tunnel tokenを`secrets/tunnel-token`に保存する。
cloudflaredの実行UID/GIDがComposeの`65532:65532`と一致することと、tokenの読取り権限を確認する。

Accessの個別許可を設定してから、Tunnelの検証ホスト名を`http://app:8000`へ接続する。
詳細は[既存手順のCloudflare準備](truenas-dockge-cloudflare-pilot-runbook.md#8-cloudflareの準備)を参照する。

```bash
docker compose --profile '*' config --quiet
docker compose run --rm --no-deps --entrypoint python app -c 'from security_config import validate_runtime_security; validate_runtime_security(); print("production settings: OK")'
docker compose run --rm --no-deps --entrypoint python app -c 'from pathlib import Path; import tempfile; roots = [Path("/data"), Path("/app/storage")]; assert all(p.is_dir() and not any(p.iterdir()) for p in roots), "runtime must be empty before first startup"; [tempfile.TemporaryFile(dir=p).close() for p in roots]; assert Path("/run/secrets/password-blocklist.txt").read_text(encoding="utf-8").strip(), "blocklist must not be empty"; print("fresh runtime and permissions: OK")'
```

空領域の確認は初回起動前だけ実行する。2回目以降はDBが存在するため失敗するのが正常。
production設定の確認でエラーが出たら該当設定を直す。

## 3. 起動し、空DBを確認する

```bash
docker compose up -d app
docker compose ps
docker compose logs --tail=100 app
docker compose exec -T app python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=3).read().decode())'
```

healthcheckが正常になってから、初期管理者の作成前に次を実行する。
主DBを読取り専用で開き、業務データの混入がないことを確認する。データは削除しない。

```bash
docker compose exec -T app python - <<'PY'
import sqlite3
with sqlite3.connect("file:/data/hoikuict.db?mode=ro", uri=True) as db:
    tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    assert {"users", "children", "families", "classrooms", "parent_accounts"} <= set(tables), "application schema missing"
    populated = {}
    for name in tables:
        quoted = '"' + name.replace('"', '""') + '"'
        count = db.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        if count:
            populated[name] = count
    assert not populated, f"database is not fresh: {populated}"
    print(f"fresh business database: OK ({len(tables)} tables)")
PY
```

続けてTunnelを起動し、検証URLがAccessで保護されていることを確認する。

```bash
docker compose up -d cloudflared
docker compose exec app python -m scripts.auth_user bootstrap-admin
```

表示名・連絡先メール・ログインID・作成理由・実行者・承認者を入力し、内容を確認して作成する。
表示された有効化コードを使い、`https://<PILOT_HOSTNAME>/staff/activate`でパスワードを設定する。
コードは一度だけ表示されるため、有効時間内に本人が操作する。
ログアウト・再ログイン後、園児・家庭・クラスが空、職員が初期管理者1人であることを確認する。

## 4. 最初の実機検証

以下を順に確認し、日時・結果・不具合を記録する。

| 順番 | 確認内容 | 結果 |
| --- | --- | --- |
| 1 | 空領域、初回起動、主DBの全tableが0件 | 未実施 |
| 2 | Accessの許可・拒否、初期管理者の有効化・ログイン | 未実施 |
| 3 | 架空のクラス1件、職員1人、家庭1件、園児1人を画面で作成 | 未実施 |
| 4 | 保護者の招待・有効化、日次連絡、職員側の確認 | 未実施 |
| 5 | お知らせと添付を登録し、対象保護者から閲覧 | 未実施 |
| 6 | app再起動、container再作成後も認証・記録・添付が保持される | 未実施 |
| 7 | 停止snapshot・可搬backupを作成し、別runtimeに隔離復元 | 未実施 |

再起動は`docker compose restart app`、同じimageでの再作成は
`docker compose up -d --force-recreate app`を使う。
検証中にデモseedや`--wipe-all`は実行しない。

backup CLIは同梱している。停止・snapshot・backup・隔離復元の手順は
[改訂仕様の第9〜10章](pilot-deployment-spec-v2.md)を使う。
`backup-worker`は`backup-ui-trial` profileで明示的に起動する検証用補助機能。
初回はappとcloudflaredだけを常駐させる。

## ローカル事前検証と実機の区別

2026-09-06、開発PCの現在の作業ツリー（未コミットの認証変更を含む）で次を確認した。

| 検証 | 結果 |
| --- | --- |
| 全profileのCompose config、変数対応、ホストポート非公開、backupのnetwork分離 | 成功。架空の設定値を使用 |
| Composeから取り出したproduction設定による隔離DBの2回初期化 | 104テーブルすべて0件。SQLite整合性・外部キー・WAL確認成功 |
| HTTPSを指定したTestClient | health、未認証時のログイン誘導、ログイン・有効化画面の応答を確認 |
| 起動・セキュリティ・職員認証・保護者認証・職員再設定・backupの既存6テストファイル | 88件成功 |

開発PCのDocker daemonは起動しておらず、Linuxイメージのbuild・起動は未実施。
TrueNASのLinuxコンテナ起動、bind mount権限、HTTPS/Tunnel、SMTP実送信、snapshot・復元は
実機で確認し終えた項目だけを上表へ記録する。
