# TrueNAS・Dockge・Cloudflare 実運用試験手順書

> 対象仕様: [実運用試験構成仕様](pilot-deployment-spec.md)  
> バックアップ: [バックアップ・復元仕様](backup-restore-spec.md)  
> 対象段階: 架空データによる段階A・B  
> 注意: `<pool>`、`<hostname>`、`<approved-sha>`等は実環境の値へ置き換える。秘密値を作業記録へ貼り付けない。

## 1. 結論と開始条件

専用ブランチを使う。ただし、現在の未コミット変更を先に整理し、デプロイ対象をcommit/tagで固定してから開始する。TrueNAS上の稼働物は「いま手元にあるファイル」ではなく、記録済みGit SHAから再現できる状態にする。

最初の試験は架空データ、管理者と少人数職員、Cloudflare Accessありで行う。実名、住所、電話番号、健康情報、口座情報は入力しない。

## 2. 役割と記録

開始前に次を記入する。

| 項目 | 記入欄 |
| --- | --- |
| 試験責任者 |  |
| TrueNAS/Docker担当 |  |
| Cloudflare担当 |  |
| 業務確認担当 |  |
| 緊急連絡先 |  |
| 試験期間 |  |
| pilot hostname |  |
| Git SHA / tag |  |
| app image ID |  |
| cloudflared image digest |  |
| backup先 |  |
| 復旧目標時間（RTO） |  |
| 許容データ損失（RPO） |  |

## 3. Gitの準備

### 3.1 開発PC

現在の変更を確認し、機能変更の意図とテスト結果を整理する。

```powershell
git status --short
git diff --stat
```

未コミット変更がすべて整理された後、試験作業用ブランチを作る。

```powershell
git switch -c codex/pilot-truenas-dockge
```

Compose、運用文書、必要な補助スクリプトをレビューし、承認後にcommit SHAを記録する。試験へ出すcommitには、少なくとも全自動テストの結果を紐付ける。

### 3.2 TrueNASへ展開する版

TrueNASでは承認済みSHAをcheckoutし、値を記録する。

```bash
git fetch --tags --prune
git checkout --detach <approved-sha>
git rev-parse HEAD
git status --short
```

`git status --short`が空でない状態をデプロイしない。更新も同じ手順で新しいSHAへ切り替える。

## 4. TrueNASの準備

### 4.1 事前確認

- [ ] TrueNAS、Docker、Dockgeのversionを記録した
- [ ] poolが正常で、scrub/SMART異常がない
- [ ] NTPとtimezoneが正しい
- [ ] UPSまたは停電時停止方針がある
- [ ] DockgeとTrueNAS管理画面がLAN/VPN等の管理経路だけから到達できる
- [ ] 既存Docker network、LAN、VPNのCIDRを調べた

例の`172.30.50.0/24`が重複する場合は別CIDRへ変更する。

```bash
docker network ls
docker network inspect <existing-network>
```

### 4.2 dataset

TrueNAS UIのDatasetsから、少なくとも次を作成する。

```text
/mnt/<pool>/apps/open-hoikuict-pilot/runtime
/mnt/<pool>/apps/open-hoikuict-pilot/secrets
/mnt/<pool>/apps/dockge/stacks/open-hoikuict-pilot
/mnt/<backup-pool>/backup/open-hoikuict-pilot/sets
```

runtime dataset内に`data`と`storage`directoryを作る。アプリ用datasetはTrueNASのApps presetを出発点にし、実際のcontainer UID/GIDで両directoryの書込試験を行う。runtimeと`secrets`をSMB/NFS共有しない。`secrets`は管理者以外が読めない権限にする。

Dockgeはstack directory内の`compose.yaml`を管理する。Dockge containerから見えるstack pathとhost pathは同じpathになるようmountされていることを確認する。

## 5. stack directory

推奨配置は次のとおり。

```text
open-hoikuict-pilot/
├── compose.yaml
├── .env                    # Git管理外
├── source/                 # 承認済みSHAのcheckout
└── secrets/
    ├── tunnel-token        # Git管理外
    └── password-blocklist.txt
```

DBと添付はstack directory内へ置かず、前節のruntime datasetをabsolute pathでmountする。

## 6. 秘密情報と環境設定

### 6.1 ランダム値

用途ごとに別々の値を生成する。出力をshell history、チケット、チャットへ貼らず、承認済みpassword managerにも保管する。

```bash
openssl rand -base64 48
openssl rand -base64 48
```

1つ目を`HOIKUICT_SECRET_KEY`、2つ目を`HOIKUICT_LOGIN_THROTTLE_HMAC_KEY`にする。kioskを使う場合は3つ目を別途生成する。

### 6.2 `.env`

次を雛形にする。実値の`.env`はGitへ登録しない。

```dotenv
COMPOSE_PROJECT_NAME=open-hoikuict-pilot
APP_RUNTIME_PATH=/mnt/<pool>/apps/open-hoikuict-pilot/runtime
BACKUP_SET_PATH=/mnt/<backup-pool>/backup/open-hoikuict-pilot/sets
BACKUP_GIT_SHA=<approved-checkout-full-sha>
BACKUP_APP_IMAGE=open-hoikuict:pilot
BACKUP_COMPOSE_SHA256=<sha256-of-deployed-compose.yaml>
CLOUDFLARED_IMAGE=cloudflare/cloudflared@sha256:<approved-digest>
PILOT_NETWORK_CIDR=172.30.50.0/24
PILOT_HOSTNAME=pilot-hoiku.example.jp

HOIKU_NURSERY_REF=<facility-name>
HOIKUICT_SECRET_KEY=<random-value-1>
HOIKUICT_LOGIN_THROTTLE_HMAC_KEY=<random-value-2>

HOIKUICT_SMTP_HOST=<smtp-host>
HOIKUICT_SMTP_PORT=587
HOIKUICT_SMTP_STARTTLS=1
HOIKUICT_SMTP_USERNAME=<smtp-user>
HOIKUICT_SMTP_PASSWORD=<smtp-password>
HOIKUICT_PARENT_MAIL_FROM=<approved-from-address>
```

`.env`と`secrets`の権限を確認する。Cloudflare公式imageは現在UID/GID `65532:65532`の非root userで動くため、token fileもそのuserだけが読めるようにする。imageをdigest固定する際に実行UIDを再確認する。

```bash
chmod 600 .env
chown 65532:65532 secrets/tunnel-token
chmod 400 secrets/tunnel-token
chmod 644 secrets/password-blocklist.txt
```

password blocklistは施設で承認した十分なリストを用意する。単に空fileを作ってproduction validationだけを通過させてはならない。

## 7. Compose雛形

次は試験用の基準形である。`source`に承認済みcheckoutを置く。Cloudflare imageは初回技術試験では公式`latest`を取得できるが、段階C前に検証済みdigestへ固定する。

```yaml
services:
  app:
    build:
      context: ./source
      dockerfile: Dockerfile
    image: open-hoikuict:pilot
    pull_policy: build
    restart: unless-stopped
    environment:
      TZ: Asia/Tokyo
      HOIKUICT_ENV: production
      HOIKUICT_DATABASE_URL: sqlite:////data/hoikuict.db
      HOIKU_FACILITY_BUNREI_DB_PATH: /data/facility.sqlite
      HOIKU_NURSERY_REF: ${HOIKU_NURSERY_REF:?required}
      HOIKUICT_ENABLE_MOCK_AUTH: "0"
      HOIKUICT_STAFF_AUTH_MODE: local_password
      HOIKUICT_PARENT_AUTH_MODE: local_password
      HOIKUICT_SECRET_KEY: ${HOIKUICT_SECRET_KEY:?required}
      HOIKUICT_LOGIN_THROTTLE_HMAC_KEY: ${HOIKUICT_LOGIN_THROTTLE_HMAC_KEY:?required}
      HOIKUICT_COOKIE_SECURE: "1"
      HOIKUICT_CSRF_ENFORCE: "1"
      HOIKUICT_ALLOWED_ORIGINS: https://${PILOT_HOSTNAME:?required}
      FORWARDED_ALLOW_IPS: ${PILOT_NETWORK_CIDR:?required}
      HOIKUICT_KIOSK_ACCESS_MODE: disabled
      HOIKUICT_PUSH_TRANSPORT: disabled
      HOIKUICT_PARENT_MAIL_TRANSPORT: smtp
      HOIKUICT_PARENT_REGISTRATION_BASE_URL: https://${PILOT_HOSTNAME:?required}
      HOIKUICT_SMTP_HOST: ${HOIKUICT_SMTP_HOST:?required}
      HOIKUICT_SMTP_PORT: ${HOIKUICT_SMTP_PORT:?required}
      HOIKUICT_SMTP_STARTTLS: "1"
      HOIKUICT_SMTP_USERNAME: ${HOIKUICT_SMTP_USERNAME:-}
      HOIKUICT_SMTP_PASSWORD: ${HOIKUICT_SMTP_PASSWORD:-}
      HOIKUICT_PARENT_MAIL_FROM: ${HOIKUICT_PARENT_MAIL_FROM:?required}
      HOIKUICT_PASSWORD_BLOCKLIST_PATH: /run/secrets/password-blocklist.txt
      HOIKUICT_PREVIEW_DIR: /data/data_transfer_previews
      HOIKUICT_BACKUP_CONTROL_DIR: /data/backup-control
    volumes:
      - ${APP_RUNTIME_PATH:?required}/data:/data
      - ${APP_RUNTIME_PATH:?required}/storage:/app/storage
      - ./secrets/password-blocklist.txt:/run/secrets/password-blocklist.txt:ro
    expose:
      - "8000"
    networks:
      - pilot_network
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).read()"]
      interval: 30s
      timeout: 5s
      retries: 3

  cloudflared:
    image: cloudflare/cloudflared:latest
    user: "65532:65532"
    restart: unless-stopped
    command: tunnel run --token-file /run/secrets/tunnel-token
    volumes:
      - ./secrets/tunnel-token:/run/secrets/tunnel-token:ro
    networks:
      - pilot_network
    depends_on:
      app:
        condition: service_healthy

  backup:
    build:
      context: ./source
      dockerfile: Dockerfile
    image: open-hoikuict:pilot
    pull_policy: build
    profiles: [operations]
    restart: "no"
    network_mode: none
    environment:
      TZ: Asia/Tokyo
      HOIKUICT_DATABASE_URL: sqlite:////data/hoikuict.db
      HOIKU_FACILITY_BUNREI_DB_PATH: /data/facility.sqlite
      HOIKUICT_STORAGE_ROOT: /app/storage
    volumes:
      - ${APP_RUNTIME_PATH:?required}/data:/data
      - ${APP_RUNTIME_PATH:?required}/storage:/app/storage
      - ${BACKUP_SET_PATH:?required}:/backup
    entrypoint: ["python", "-m", "scripts.backup_runtime"]
    command: ["--help"]

  backup-worker:
    build:
      context: ./source
      dockerfile: Dockerfile
    image: open-hoikuict:pilot
    pull_policy: build
    restart: unless-stopped
    network_mode: none
    read_only: true
    tmpfs: [/tmp]
    environment:
      TZ: Asia/Tokyo
      HOIKUICT_ENV: production
      HOIKUICT_DATABASE_URL: sqlite:////data/hoikuict.db
      HOIKU_FACILITY_BUNREI_DB_PATH: /data/facility.sqlite
      HOIKU_NURSERY_REF: ${HOIKU_NURSERY_REF:?required}
      HOIKUICT_STORAGE_ROOT: /app/storage
      HOIKUICT_BACKUP_CONTROL_DIR: /data/backup-control
      HOIKUICT_BACKUP_OUTPUT_ROOT: /backup
      HOIKUICT_BACKUP_GIT_SHA: ${BACKUP_GIT_SHA:?required}
      HOIKUICT_BACKUP_APP_IMAGE: ${BACKUP_APP_IMAGE:?required}
      HOIKUICT_BACKUP_COMPOSE_SHA256: ${BACKUP_COMPOSE_SHA256:?required}
      HOIKUICT_BACKUP_CLOUDFLARED_IMAGE: ${CLOUDFLARED_IMAGE:?required}
    volumes:
      - ${APP_RUNTIME_PATH:?required}/data:/data
      - ${APP_RUNTIME_PATH:?required}/storage:/app/storage
      - ${BACKUP_SET_PATH:?required}:/backup
    entrypoint: ["python", "-m", "scripts.backup_worker"]

networks:
  pilot_network:
    ipam:
      config:
        - subnet: ${PILOT_NETWORK_CIDR:?required}
```

専用networkに参加するserviceは`app`と`cloudflared`だけにする。host portを公開しなくても、appからSMTP、cloudflaredからCloudflareへの外向き通信は可能である。TrueNASのfirewallで外向き通信を制限する場合は、Cloudflareと承認済みSMTPへの必要通信を許可する。

ComposeをDockgeへ保存する前に、展開結果へ秘密値が意図せず表示されない環境で構文を確認する。

```bash
docker compose config --quiet
```

## 8. Cloudflareの準備

### 8.1 Accessを先に作る

Cloudflare Zero Trustで次を行う。画面名は現行Cloudflare UIに従う。

1. `Access controls` > `Applications`からself-hosted applicationを作る。
2. public hostnameへ`https://<pilot-hostname>`を指定する。
3. Allow policyは試験参加者の個別メールまたは承認済みIdP groupだけにする。
4. deny-by-defaultを確認する。
5. MFAと短いsession durationを設定する。
6. 許可外アカウントで拒否される試験を予定表へ入れる。

### 8.2 Tunnel

1. Cloudflare Zero Trustでremotely-managed Tunnelを作成する。
2. Docker connector用tokenを取得し、TrueNASの`secrets/tunnel-token`へ改行や引用符を加えず保存する。
3. published application routeに`<pilot-hostname>`を登録する。
4. service URLを`http://app:8000`にする。
5. `Protect with Access`を有効にする。
6. DNS recordがTunnelを指し、他のA/AAAA recordがoriginを直接指していないことを確認する。

ルーターのport forwardingは追加しない。

## 9. 初回起動

### 9.1 デプロイ前backup

空のdata datasetでも、設定変更前snapshotを1つ取得する。以後は更新前に必ずsnapshot名と時刻を記録する。

### 9.2 Dockge

1. Dockgeで`Scan Stacks Folder`を実行する。
2. `open-hoikuict-pilot`を開く。
3. Composeの`ports`に8000番がないことを目視確認する。
4. Deploy/Startを実行する。
5. appとcloudflaredのログを確認する。

CLIで確認できる場合は次も実行する。

```bash
docker compose ps
docker compose logs --tail=200 app
docker compose logs --tail=200 cloudflared
docker compose exec app python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/healthz').read().decode())"
```

`productionセキュリティ設定が不正`で停止した場合、エラーに挙がった設定を修正する。`HOIKUICT_ENV=development`へ下げて回避しない。

### 9.3 初期管理者

Dockgeのapp terminalまたはinteractive shellで、初回だけ次を実行する。

```bash
python -m scripts.auth_user bootstrap-admin
```

実施日時、実行者、作成理由、作成したlogin IDを監査記録へ残す。passwordやaction codeそのものは記録しない。画面の案内に従って初期設定を完了し、ログアウト・再ログインを確認する。

## 10. 初回検証

### 10.1 ネットワーク

- [ ] LANから`http://<truenas-ip>:8000`へ到達できない
- [ ] ルーターに80/443/8000の転送がない
- [ ] 許可外Cloudflare identityはAccessで拒否される
- [ ] 許可済みidentityだけがアプリloginへ進める
- [ ] Tunnel停止中は公開URLから到達できない
- [ ] Tunnel停止中もDB fileは変化・消失しない
- [ ] Dockge/TrueNAS UIはpilot hostnameから到達できない

### 10.2 認証・権限

- [ ] mock loginやrole切替が表示されない
- [ ] 職員login、logout、idle timeoutを確認した
- [ ] 管理者、編集者、閲覧専用の更新可否が期待どおり
- [ ] 保護者は紐付けた園児だけを閲覧できる
- [ ] 他家庭・未紐付け園児のURL直接指定が拒否される
- [ ] login失敗を繰り返すとthrottleされる
- [ ] 異なる外部端末が同一client IPとして誤集約されない
- [ ] cookieにSecure属性が付く
- [ ] CSRF違反requestが拒否される

### 10.3 データ永続化

架空データを数件入力し、件数と識別用の架空名称を記録する。

1. appをrestartする。
2. 同じデータが残ることを確認する。
3. stackをdown/upする。
4. 同じデータが残ることを確認する。
5. imageを同じSHAからrebuildする。
6. 同じデータが残ることを確認する。

デモseedの`python -m scripts.seed_demo_100 --wipe-all`は、pilot stackで絶対に実行しない。

### 10.4 SMTP

- [ ] 承認済みtest mailboxへ招待が届く
- [ ] linkのoriginがpilot hostnameと一致する
- [ ] linkやcodeが期限切れ・再利用時に拒否される
- [ ] 本文やmail logに不要な個人情報がない
- [ ] password resetの開始から完了まで確認した

## 11. backupと復元試験

RPO/RTO、対象、保持、暗号化、検査、復元判定は[バックアップ・復元仕様](backup-restore-spec.md)を正とする。

### 11.1 段階Aの安全な基準手順

初回は確実性を優先し、短時間停止してsnapshotを取る。

1. 利用者へ停止を通知する。
2. appを停止する。
3. containerが停止したことを確認する。
4. TrueNASで`runtime` datasetのapplication-consistent snapshotを作る。
5. 別poolまたは別装置へsnapshotを複製する。
6. appを起動し、loginと主要画面を確認する。

停止中に`.db`だけを手動コピーしない。

backup helperを直接実行する場合は、appを停止した状態またはapplication-consistent snapshotの書込み可能cloneをruntime volumeへmountした状態で行う。次はapp停止方式の例である。

```bash
git_sha=$(git -C source rev-parse HEAD)
app_image=$(docker image inspect open-hoikuict:pilot --format '{{.Id}}')
compose_sha=$(sha256sum compose.yaml | awk '{print $1}')

docker compose stop app
docker compose run --rm --no-deps backup create \
  --output-root /backup \
  --git-sha "$git_sha" \
  --app-image "$app_image" \
  --compose-sha256 "$compose_sha" \
  --quiesced
docker compose up -d app
```

成功時は`/backup/open-hoikuict_<UTC>_<SHA>/`が作成される。表示されたdirectoryを再検査する。

```bash
docker compose run --rm --no-deps backup verify \
  /backup/<backup-directory> --json
```

途中失敗した`.partial` directoryには`COMPLETE`がなく、正常backupとして複製・世代削除の基準にしない。appを再開した後、失敗理由を確認する。

### 11.2 管理画面からの手動backup

`backup-worker`が起動すると、管理者のside menuに`バックアップ管理`が表示される。

1. `/settings/backups`を開き、workerが`稼働中`であることを確認する。
2. `今すぐバックアップ`を押し、確認dialogを承認する。
3. 状態が`待機中`、`実行中`、`成功`へ変わることを確認する。
4. 成功行のbackup ID、検証file数、warningを確認する。
5. TrueNAS側で同じbackup IDのdirectoryに`COMPLETE`があることを確認する。

管理画面は依頼と結果表示だけを行う。app containerは`/backup`をmountせず、networkなしの専用workerだけがbackup setを書き込む。workerはSQLiteの書込みlockを取得してDBと添付をcopyするため、実行中の更新requestは短時間待機する場合がある。管理画面からbackupの削除・download・復元はできない。

Git SHA、app image、Compose SHA-256はdeployまたは更新のたびに`.env`へ反映する。画面に未設定warningが出るbackupは限定実データ試験の正式copyとして採用しない。

#### 定期実行

同じ画面の`定期実行設定`で、次を指定できる。

- 有効・無効
- 毎日または毎週
- JSTの実行時刻
- 毎週の場合の実行曜日

設定はruntimeの`data/backup-control/schedule.json`へ保存される。workerは予定枠をjob履歴へ記録し、再起動後に同じ予定枠を重複実行しない。予定時刻後にworkerを起動した場合は同一日の予定枠をcatch-upするが、過去日・過去週の分は持ち越さない。

このscheduleは可搬backup setの作成だけを自動化する。TrueNAS periodic snapshot、別pool・off-site複製、世代削除、alertは別途設定する。初期値は無効・毎日02:00であり、限定実データ試験では利用者の少ない時間帯を施設が承認してから有効化する。

### 11.3 復元試験

本番datasetを直接rollbackせず、まず隔離したclone/restore先で確認する。

1. snapshotまたは複製backupから隔離datasetへ復元する。
2. 別名の検証stackで、外部公開なし・mail送信なしで起動する。
3. DBが開けること、主要件数、代表データ、loginに必要な記録を確認する。
4. 開始から確認完了までの時間をRTO実績として記録する。
5. backup時刻から失われる可能性のある期間をRPO実績として記録する。
6. 検証stackを停止し、復元結果と問題点を記録する。

段階C前に、SQLite backup API、manifest、hash、DB・添付整合性検査を使用する日次backupを自動化し、失敗alertと世代削除を実装する。

## 12. 日次・週次運用

### 毎日

- [ ] app/cloudflaredがhealthyでrestart増加がない
- [ ] 公開URL、Access、アプリlogin、主要画面を確認
- [ ] TrueNAS poolとdataset使用率を確認
- [ ] 前日backupと別系統複製の成功を確認
- [ ] login失敗、権限変更、アカウント停止を確認
- [ ] 未処理の業務不整合と障害記録を確認

### 毎週

- [ ] 退職・異動・試験離脱者のAccessとアプリアカウントを停止
- [ ] container image、OS、Cloudflareの更新情報を確認
- [ ] snapshot保持数とbackup容量を確認
- [ ] 紙運用との差分、入力漏れ、職員の困りごとを振り返る

### 毎月

- [ ] 隔離復元試験を実施
- [ ] Access policy、管理者、Cloudflare tokenの所有者を棚卸し
- [ ] RTO/RPOと保存期間を見直す

## 13. 更新手順

1. 開発PCで自動テストを完了する。
2. 試験用の架空データ環境で新SHAを検証する。
3. 変更内容、DB変更有無、停止時間、戻し方をレビューする。
4. app停止または承認済みSQLite backup APIでbackupし、TrueNAS snapshotを取得する。
5. `source`を承認済みSHAへ更新する。
6. DockgeでBuild/Updateする。
7. health、login、権限、主要画面、代表件数を確認する。
8. Git SHA、image ID、snapshot、結果を記録する。

失敗時はappを停止し、旧SHAと、その更新直前DB snapshotを対で復元する。DB変更後に旧imageだけへ戻さない。

## 14. 障害対応

| 事象 | 初動 | 代替運用 |
| --- | --- | --- |
| app停止 | restart回数と直前logを保全。無制限restartを避ける | 紙の登降園簿、電話 |
| Tunnel/Cloudflare障害 | appやrouter portを臨時公開しない | 園内限定の承認済み経路または紙・電話 |
| TrueNAS/pool異常 | 書込を止め、pool状態とhardwareを確認 | 紙運用へ切替 |
| 誤更新・誤削除 | 時刻、操作者、対象を記録。追加更新を止める | snapshot/backupを隔離復元して調査 |
| 漏えい疑い | Accessとアプリアカウントを必要範囲で停止、log保全、責任者へ連絡 | 個人判断でlogやDBを削除しない |
| 秘密値漏えい | 影響範囲を確認し、Tunnel token、app secret等を用途別にrotate | rotate後に全connector/sessionを確認 |

障害時にCloudflare Tunnelを外してapp portをインターネット公開することは禁止する。

## 15. Go / No-Go判定

### 段階A開始

- [ ] 構成仕様の段階A受け入れ条件がすべて合格
- [ ] 初回検証と復元試験が合格
- [ ] 既知の制限を参加者へ説明
- [ ] 試験責任者が開始を承認

### 段階Cへの移行

1項目でも未完了ならNo-Goとする。

- [ ] 構成仕様の段階C受け入れ条件がすべて合格
- [ ] リリース前チェックリストが合格
- [ ] 2週間以上の架空データ業務試験で重大障害がない
- [ ] backupの自動化と月次復元に成功
- [ ] 個人情報取扱と保護者説明が承認済み
- [ ] データ移行を空DBでリハーサル済み
- [ ] 停止・切戻し判断者が当日対応可能

判定結果、未解決事項、承認者、日付を記録する。

## 16. 終了・撤去

1. 参加者へ終了を通知する。
2. 必要な監査記録を保全する。
3. Cloudflare Access applicationとTunnel routeを停止する。
4. Dockge stackを停止する。
5. datasetの保持・削除を個人情報保存規程に従って判断する。
6. Tunnel token等を失効する。
7. 削除したもの、残したもの、backupの期限を記録する。

実データが入ったdatasetやbackupは、単にstackを削除しただけでは消えない。TrueNAS snapshot、replication先、外部backupを含めて追跡する。
