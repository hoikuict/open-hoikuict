# TrueNAS・Dockge・Cloudflare サーバー運用試験仕様書 改訂版

> 文書版: 2.0  
> 作成日・実装確認日: 2026年9月5日  
> 確認対象コミット: `c759415960d4eae04401cd28c2e3f967868279e4`  
> 状態: 改訂案。構成例を含む。TrueNAS実機での受け入れ確認は未実施。  
> 対象: TrueNAS上のDocker、Dockge、Cloudflare Tunnel / Accessを使う段階A〜Cの運用試験

## 1. 文書の位置付け

この文書は、既存の[実運用試験構成仕様](pilot-deployment-spec.md)を上書きせず、現在の実装との照合結果を反映した新しい版である。[旧手順書](truenas-dockge-cloudflare-pilot-runbook.md)に分散していた構成例、起動、バックアップ、復元の条件も整理する。

この版を採用する試験では、旧文書と食い違う構成・手順について本書を適用する。[バックアップ・復元仕様](backup-restore-spec.md)の保護対象、保持、暗号化、検査、復元基準、および[リリース前チェックリスト](release-checklist.md)の未完了条件は引き続き適用する。本書の作成だけで、実装完了・実機試験合格・実データ利用承認とは扱わない。

### 1.1 主な修正

| 再確認で判明した点 | この版の扱い |
| --- | --- |
| 配布Composeは本番認証・SMTP等が不足し、ホストへ8000番を公開している | 付録Aにproduction必須設定を含む、ホストポート非公開の構成例を収録する |
| `CLOUDFLARED_IMAGE`と実際の`latest`起動が一致しない | 起動imageとバックアップ記録の両方に同じdigest指定を使用する |
| 添付永続化・バックアップ補助を「未整備」と記載していた | 実装済み機能と、TrueNAS側の未設定・未検証事項を分ける |
| 停止バックアップと稼働中workerの位置付けが不明瞭 | 正式な取得は停止方式。稼働中workerは並行操作を含む検証完了まで補助用途とする |
| 復元試験の「メール送信なし」の設定が不足している | productionを維持し、SMTPの接続先変更と通信遮断を組み合わせる |
| 初期管理者について古い外部認証前提が残っている | 現行のローカル認証CLIと有効化コードによる手順に統一する |
| 「現在は未コミット変更がある」という固定的な記述 | 展開時に対象SHAと作業ツリーを確認する条件へ変更する |

## 2. 目的・試験段階

日常業務、個別認証、権限、データ永続化、更新、バックアップ、障害時の代替運用を段階的に検証する。

| 段階 | 利用データ・対象者 | 公開条件・完了条件 |
| --- | --- | --- |
| A: 技術試験 | 架空データ、管理者と職員2〜5名 | Access個別許可＋アプリ認証。起動、権限、永続化、バックアップ、隔離復元を確認 |
| B: 業務試験 | 架空データ、1クラス相当の職員 | 同じ公開制御。2週間以上の業務シナリオと紙・電話への切替を確認 |
| C: 限定実データ試験 | 承認対象の職員・保護者、必要最小限の実データ | 第12章の全条件、移行リハーサル、個人情報取扱承認が必要 |
| D: 全面本番 | 全対象者・実データ | 本書の対象外。別途移行判断を行う |

段階A・Bに実在する園児・家庭・職員の業務データを投入しない。段階Cは[ベータ開始時の本番データ移行仕様](beta-production-data-migration-spec.md)の実装・検証を前提とする。

## 3. 実装と導入準備の現状

| 項目 | 確認対象コミットでの状態 | サーバー側で必要な作業 |
| --- | --- | --- |
| production設定検査 | `security_config.py`に実装済み。不足設定で起動を拒否する | 第6章の設定とファイル権限を確認する |
| 職員・保護者のローカル認証 | 実装あり | HTTPS経由でログイン、招待、再設定、権限差を実機確認する |
| 初期管理者CLI | `scripts.auth_user bootstrap-admin`が実装済み | 対象DBに対して実行し、本人がパスワードを設定する |
| 通常起動時の業務デモデータ非投入 | `initialize_application()`と既存テストで確認 | 移行後の家庭・園児リンク不変検査は別途実施する |
| DB・添付の永続化設定 | 配布Composeに`/data`と`/app/storage`のmountがある | TrueNASの専用runtimeへbind mountし、UID/GID・再作成後の保持を確認する |
| バックアップ作成・検証 | `scripts.backup_runtime create / verify`が実装済み | 実際のDB・添付量で検査と復元を実施する |
| 管理画面とworker | 即時依頼、履歴、毎日・毎週scheduleが実装済み | 第9章の利用条件を満たす。画面の成功だけで運用全体の合格としない |
| TrueNASのsnapshot・複製・監視 | リポジトリの実装だけでは構成されない | TrueNAS・複製先で設定し、成功証跡を残す |
| 復元後の全セッション・トークン失効CLI | 専用CLIは未実装 | 段階C前に実装・検証する |
| 移行パッケージの一括移行 | 計画仕様あり。受け入れ完了は未確認 | 新規DBへの一括取込、再実行、再起動不変検査を完了する |

確認時、認証・起動・バックアップ関連の既存テスト5ファイル、45件が成功した。対象は`test_security_controls.py`、`test_application_startup.py`、`test_backup_runtime.py`、`test_backup_jobs.py`、`test_backup_schedule.py`であり、全機能・Linuxコンテナ・SMTP実送信・TrueNAS復元を保証する結果ではない。

## 4. 論理構成・通信境界

```text
利用端末 -- HTTPS --> Cloudflare Access
                         |
                  Cloudflare Tunnel
                         |
                  cloudflared container
                         |
                  専用networkのHTTP
                         |
                    app:8000
                    /data + /app/storage
                         |
                TrueNAS runtime dataset

管理用backup container -- networkなし --> runtime + 別poolのbackup保存先
検証用backup-worker    -- networkなし --> runtime + 同じbackup保存先
```

- ルーターからTrueNASへ80・443・8000番を転送しない。公開用appとcloudflaredにComposeの`ports`を設定しない。
- 公開用の専用Docker networkに参加するのはappとcloudflaredだけとする。バックアップサービスにDocker socketをmountしない。
- `FORWARDED_ALLOW_IPS`は専用networkのCIDRに限定する。`*`や全アドレス範囲を指定しない。例の`172.30.50.0/24`はLAN・VPN・他のDocker networkと重複しない場合だけ使う。
- DockgeとTrueNAS管理画面はLAN/VPN等の管理経路に限定し、試験用hostnameに載せない。
- Accessは追加の入口制御とする。職員・保護者はアプリのローカルアカウントでも認証する。Accessの利用者情報をアプリの初期管理者へ外部認証IDとして登録する手順は設けない。
- Access applicationと個別許可policyを公開routeより先に作る。許可外identityの拒否、MFA、session有効期間、Tunnel側のAccess token検証を確認する。
- アプリは承認済みSMTPへ、cloudflaredはCloudflareへ外向き通信できるようにする。必要な宛先・ポートを実環境で記録する。
- HTML、認証済み画面、個人情報を含むresponseをCloudflareでcacheしない。保護者がAccessを利用できない場合の公開方針変更は段階Cの判断事項とする。

利用端末からCloudflareはHTTPS、cloudflaredからCloudflareはTunnelの暗号化通信、cloudflaredからappは専用network内のHTTPとする。Tunnel区間全体を一律に「HTTPS」とは記載しない。

## 5. TrueNAS・保存領域・配置

TrueNAS、Docker、Compose、Dockgeのversion、pool状態、NTP/timezone、UPSまたは停電時停止方針を開始前に記録する。CPU・メモリ・同時利用者数・添付総量の実測基準は未確定であるため、段階A・Bで測定し、段階Cの利用規模と容量を確定する。

| host上のパス例 | 内容 | 条件 |
| --- | --- | --- |
| `/mnt/<pool>/apps/dockge/stacks/open-hoikuict-pilot` | 展開用Compose、`source/`の承認済みcheckout | Dockge内外で同じabsolute pathとして扱う |
| `/mnt/<pool>/apps/open-hoikuict-pilot/runtime` | `data/`、`storage/` | 専用dataset。一般利用者へのSMB/NFS共有は禁止 |
| `/mnt/<pool>/apps/open-hoikuict-pilot/secrets` | `.env`、Tunnel token、password blocklist | Git外。限定権限、暗号化・別保管方針を定める |
| `/mnt/<backup-pool>/backup/open-hoikuict-pilot/sets` | 検証済み可搬バックアップ | runtimeと別pool。さらに別装置・別障害領域へ複製 |

```text
runtime/
├── data/
│   ├── hoikuict.db          # WAL/SHMがある場合も同じdirectoryに保存
│   ├── facility.sqlite     # WAL/SHMがある場合も同じdirectoryに保存
│   ├── backup-control/     # worker依頼、履歴、schedule
│   └── data_transfer_previews/
└── storage/
    ├── notice_attachments/
    └── message_attachments/
```

`runtime/data`を`/data`、`runtime/storage`を`/app/storage`へbind mountする。DBと添付を同じruntime datasetのsnapshotで保全する。SQLiteをSMB/NFS上のDBファイルとして運用しない。

アプリimageの非rootユーザー`appuser`の実UID/GIDを調べ、runtimeとbackup出力先への書込みを確認する。Dockerfile内の所有権設定だけではhostのbind mount権限は設定されない。UID/GIDは数値を推測して固定せず、承認imageの実値を記録する。

stack直下の`.env`はsecrets datasetの`.env`を指すsymlinkとして配置できる。その場合、Dockgeとhostの両方から同じリンク先を読めるmountと権限を設定する。CLIを使う場合は`docker compose --env-file <secretsの.envへのabsolute-path>`でも指定できる。秘密値をshellへ`source`したり、`docker compose config`の展開値を記録したりしない。

`source/`には承認済みcheckoutを置く。DB、添付、秘密値、別の作業ツリーをbuild contextへ含めない。現在の`.dockerignore`だけであらゆるローカルデータが除外されると仮定せず、専用checkoutの内容を確認する。

## 6. アプリ設定とイメージ管理

### 6.1 production必須設定

| 設定 | 採用値・条件 |
| --- | --- |
| `HOIKUICT_ENV` | `production` |
| `HOIKUICT_ENABLE_MOCK_AUTH` / `HOIKUICT_ENABLE_MOCK_ROLE_OVERRIDE` | `0` |
| `HOIKUICT_STAFF_AUTH_MODE` / `HOIKUICT_PARENT_AUTH_MODE` | 両方`local_password` |
| `HOIKUICT_SECRET_KEY` | 32文字以上の固定ランダム値 |
| `HOIKUICT_LOGIN_THROTTLE_HMAC_KEY` | 32バイト以上、secretとは別の固定ランダム値 |
| `HOIKUICT_COOKIE_SECURE` / `HOIKUICT_CSRF_ENFORCE` | 両方`1` |
| `HOIKUICT_ALLOWED_ORIGINS` | `https://<pilot-hostname>`のみ |
| `FORWARDED_ALLOW_IPS` | 第4章で決めた専用networkのCIDR |
| `HOIKUICT_KIOSK_ACCESS_MODE` | 初期値`disabled` |
| `HOIKUICT_PUSH_TRANSPORT` | `disabled`。現行productionはwebpush/captureを許可しない |
| `HOIKUICT_PARENT_MAIL_TRANSPORT` | `smtp` |
| `HOIKUICT_PARENT_REGISTRATION_BASE_URL` | `https://<pilot-hostname>` |
| `HOIKUICT_SMTP_HOST` / `HOIKUICT_SMTP_PORT` | 接続確認済みSMTPとport。例は587 |
| `HOIKUICT_SMTP_STARTTLS` | `1`。接続先のSTARTTLS・証明書検証を確認する |
| `HOIKUICT_SMTP_USERNAME` / `HOIKUICT_SMTP_PASSWORD` | SMTP側が要求する場合に設定 |
| `HOIKUICT_PARENT_MAIL_FROM` | 使用を承認された送信元 |
| `HOIKUICT_PASSWORD_BLOCKLIST_PATH` | 読取専用mountした、空ではない承認済みリスト |
| `HOIKUICT_DATABASE_URL` | `sqlite:////data/hoikuict.db` |
| `HOIKU_FACILITY_BUNREI_DB_PATH` | `/data/facility.sqlite` |
| `HOIKU_NURSERY_REF` | 対象施設の識別値 |
| `HOIKUICT_PREVIEW_DIR` / `HOIKUICT_BACKUP_CONTROL_DIR` | `/data/data_transfer_previews` / `/data/backup-control` |

Composeの変数展開に使う`.env`は、自動的にすべての値をcontainerへ渡すファイルではない。付録Aの`environment`に明示した設定が実際に渡ることを確認する。設定検査の成功に加え、blocklistを実行ユーザーで読み取れること、SMTP接続・送信、公開origin・転送ヘッダーを実機確認する。

kioskを使う場合だけ`token`へ変更し、用途の異なる固定ランダム値を`HOIKUICT_KIOSK_TOKEN`としてappの`environment`に追加する。端末登録・失効を検証する。秘密値は再起動のたびに生成せず、用途別のローテーション手順とrecovery kitを用意する。

### 6.2 リリースと記録

- 環境ごとに機能コードを複製せず、共通コードの承認済みSHAを展開する。作業ブランチが必要な場合は`codex/`配下に作成する。
- 展開時に`git rev-parse HEAD`と`git status --short`を確認する。未コミットの変更を含むcheckoutを配布しない。
- アプリを承認SHAから一度buildし、`open-hoikuict:<full-sha>`等の専用tagを付ける。同じtagを別buildに付け替えない。image IDを記録し、切戻し用の旧imageも保管する。
- 付録Aはbuild済みimageを使用する。app・backup・backup-workerのimageを揃え、Compose起動時の意図しない再buildを避ける。
- ベースimageや依存パッケージはSHAだけでは完全固定されないため、再build結果が以前と同一とは扱わない。復旧では保管済みimageを優先し、再buildした場合は再検証する。
- cloudflaredはこの改訂版では段階Aから承認済みdigestを使用する。`--token-file`を使うためversionは2025.4.0以降とし、非rootの実行UID/GIDとtoken読取権限を確認する。[Cloudflare公式のrun parameters](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/#token-file)
- デプロイ記録に実施者・日時、Git full SHA、app image ID、cloudflared digest、実際のComposeファイルのSHA-256を残す。バックアップのmanifestにも同じ値を渡す。

## 7. 初回構築・認証

1. dataset、権限、管理経路、専用CIDR、SMTP、hostname、Access policyを用意する。token fileはGit外に保存し、cloudflaredだけに必要な読取権限を与える。
2. stackの`source/`へ承認済みSHAを展開する。付録Aを展開用の新しい`compose.yaml`として保存し、付録Bを参考にGit外の`.env`を作る。リポジトリの既存Composeをそのまま使用しない。
3. `source/`からapp imageをbuildし、実際のimage IDを`.env`の`BACKUP_APP_IMAGE`へ設定する。Composeハッシュを`BACKUP_COMPOSE_SHA256`へ設定する。これらは秘密値ではないが、架空値のまま正式バックアップを取得しない。
4. stack directoryで`docker compose config --quiet`を実行する。設定値の全文を出力せずに構文を確認する。
5. 初回のruntime snapshotを取得する。`docker compose up -d app`でappだけを起動し、production検査とhealthを確認する。
6. `docker compose exec app python -m scripts.auth_user bootstrap-admin`で初期管理者を作る。CLIは表示名、メール、ログインID、作成理由、実行者、承認者を入力し、一回限りの有効化コードを表示する。
7. Access制御を確認済みのTunnelを起動し、管理者が`/staff/activate`で本人のパスワードを設定する。有効化コードは履歴・作業記録へ保存しない。失効・期限切れ時は既存CLIの`activate-staff`で対象者を確認して再発行する。
8. 管理者のログアウト・再ログイン、権限設定、主要画面を確認してから他の試験利用者を招待する。デモseedコマンドを通常のentrypointや初回起動手順に組み込まない。
9. 添付を含む架空データを用意し、restart、container再作成、同じ版の再展開後に保持されることを確認する。
10. 第9章のバックアップと第10章の隔離復元に成功し、段階Aの受け入れ結果を記録する。

旧資料に残る「初期管理者を外部認証識別子へ対応付ける」条件は、本構成ではローカル資格情報の作成・監査・有効化の確認に読み替える。移行の整合性検査や承認記録自体は省略しない。

## 8. 監視・ログ・容量

`/healthz`はプロセスの稼働確認であり、DB読書き・ログイン・SMTPの正常性を検査しない。appのDocker health、restart回数、公開URL、ログイン、代表データ読書きを別々に確認する。cloudflaredは接続状態・ログまたは別途設定するmetricsで監視し、healthcheck未定義のcontainerをDocker上で`healthy`になるものとして待たない。

| 対象 | 最低限の確認・通知条件 |
| --- | --- |
| app / Tunnel | 毎日と異常時。起動失敗、再起動増加、connector切断 |
| 公開URL・認証 | 毎日。Access許可・拒否、アプリログイン、主要画面 |
| snapshot | 15分周期。30分以上作成されていなければ警告 |
| 日次バックアップ | 予定終了から2時間以内に成功しなければ重大通知 |
| off-site複製 | 最終成功から26時間超で重大通知 |
| 整合性 | hash・DB・外部キー・添付検査の不合格を重大通知 |
| 容量 | pool使用率80%で警告、90%で重大通知・新規大量importや更新を停止 |
| 復元試験 | 月次復元が35日以上未実施で重大通知 |
| 認証監査 | 毎日。ログイン失敗、権限変更、退職者・試験離脱者の停止 |

ログの閲覧者、保存期間、ローテーションを決める。パスワード、session/action code、Tunnel token、個人情報を通常ログに残さず、Cloudflareのquery string記録・debugログも点検する。バックアップ開始前には出力先に直近の正常setの2倍以上の空き容量があることを確認する。

## 9. バックアップ運用

### 9.1 正式な取得方式

段階A〜Cの正式な日次・更新前バックアップは、appとその他のruntime書込み処理を停止した状態を基準にする。管理画面のworkerはSQLiteに`BEGIN IMMEDIATE`の書込みlockを取得するが、ファイル操作全体を同じアプリ共通lockで調停する実装ではない。既存テストの成功だけで、稼働中のDB・添付の同時点性を保証したものと扱わない。

| 方式 | 用途・採用条件 |
| --- | --- |
| 稼働中の15分snapshot | 短い間隔の復旧候補。crash-consistentとして扱い、復元時にDB・添付整合を検査する |
| app停止中のruntime全体snapshot | 正式なapplication-consistent復旧点。段階Aから実施する |
| 停止中runtimeまたはその書込み可能cloneから`backup create --quiesced` | 正式な可搬set。既存SQLite Backup API・manifest・hash・検査を利用する |
| 管理画面の即時依頼・workerの毎日/毎週schedule | 段階A・Bで補助機能として検証可能。正式な停止バックアップと複製を併用する |

停止なしの方式を正式採用するには、添付作成・削除・失敗時cleanup・DB commitを含む並行操作、大容量時のlock待ち、処理中断・再起動を検証し、欠損しない復元結果を記録する。必要な共通lock等を実装してから、運用方式の変更を記録する。

### 9.2 停止方式の手順

1. 停止を案内し、workerの実行中jobが完了したことを確認する。検証用workerが稼働している場合は停止し、他のCLI更新処理も止める。
2. appを停止し、container終了を確認する。runtime全体のsnapshotを取得する。
3. 可搬setの作成は、appを止めたまま元runtimeから行うか、snapshotの書込み可能cloneを専用backupサービスへmountして行う。cloneを使う場合はsnapshot取得後にappを再開できる。
4. 次の既存CLIで作成し、表示されたbackup directoryを`verify`で再検査する。`--quiesced`は停止・cloneの事実を確認したうえで指定する。
5. 成功setを別poolとoff-siteへ複製し、複製先でもhashと検査結果を確認する。
6. 停止方式でまだ再開していなければappを起動し、ログインと代表画面を確認する。失敗した場合も、整合性と稼働元を確認して再開判断を記録する。

以下は元runtimeを使うCLIの形である。`<...>`は実測・記録値へ置き換える。snapshot cloneを使う際は、元runtimeを参照しない専用Composeで実行する。

```bash
docker compose run --rm --no-deps backup create \
  --output-root /backup \
  --git-sha <approved-full-sha> \
  --app-image sha256:<actual-app-image-id> \
  --compose-sha256 <actual-compose-sha256> \
  --cloudflared-image cloudflare/cloudflared@sha256:<approved-digest> \
  --quiesced

docker compose run --rm --no-deps backup verify /backup/<backup-directory> --json
```

`COMPLETE`、manifest、SHA-256、DB integrity/外部キー、添付の存在・size等の検査に合格したsetだけを正常とする。schema・業務上の主要件数・保護者分離は、アプリと隔離復元による追加確認も必要である。途中失敗の`.partial`やwarningを見落として成功扱いしない。`COMPLETE`は別系統への複製や復元試験の完了を示すmarkerではない。

### 9.3 保存・復旧目標

| 障害 | RPO | RTO |
| --- | --- | --- |
| container停止・再作成 | 0分を目標 | 30分 |
| 誤更新・誤削除・更新失敗 | 15分以内 | 2時間以内 |
| source dataset破損 | 24時間以内 | 4時間以内 |
| TrueNAS・pool喪失、管理者侵害 | 24時間以内 | 24時間以内 |

15分snapshotの保持は48時間、日次の正常copyは35日、月次は13か月、更新前copyは最低35日かつ次の正常更新と復元確認まで保持する。15分のRPOは、該当snapshotの整合検査に合格して復元できることを前提とする。目標を満たせない場合は復元試験の結果から取得方式・頻度を見直す。

稼働runtime、別pool、別装置・別障害領域の暗号化off-siteの3系統を確保する。同一poolのsnapshotを独立copyに数えない。秘密値・復号鍵は通常setへ同梱せず、暗号化したrecovery kitとして別保管する。通常のapp/Dockge資格情報だけでoff-siteを削除できないようにする。

新しい正常copy、off-site複製、復元試験期限、保全指示を確認してから世代削除する。workerのscheduleは可搬setの作成のみであり、snapshot・複製・世代削除・通知を自動化する機能ではない。段階C前に正式な停止方式の日次処理とそれらの運用を設定する。

### 9.4 管理画面の検証

付録Aではworkerを`backup-ui-trial` profileに置き、通常起動の対象から外す。段階A・Bで検証するときに`docker compose --profile backup-ui-trial up -d backup-worker`で起動する。`/settings/backups`で稼働状態、依頼、成功/失敗、検証結果、実保存先の同じbackup IDを確認する。

初期scheduleは無効・毎日02:00 JSTである。毎日/毎週の指定と同一日のcatch-upは実装済みだが、過去日・過去週は持ち越さない。検証終了時はscheduleを無効化してworkerを停止する。後日同じruntimeでworkerを起動すると保存済みscheduleが使われるため、再開前にも設定を確認する。

## 10. 隔離復元とメール誤送信の防止

### 10.1 復元環境の具体条件

復元は稼働datasetの直接rollbackから始めず、別名のstackと隔離datasetで行う。公開用Composeの追加overrideだけで済ませず、cloudflaredとbackup-workerを含まない独立した復元用Composeを作る。runtime、backup-control、秘密値の参照先が稼働系と分離されていることを確認する。

`HOIKUICT_PARENT_MAIL_TRANSPORT=disabled`や`capture`へ変えると、現行productionの設定検査で起動が拒否される。次の設定と通信制御で、productionを維持したまま外部メール送信を遮断する。

| 復元環境の項目 | 値・構成 |
| --- | --- |
| `HOIKUICT_ENV` | `production` |
| staff/parent認証、Secure Cookie、CSRF、blocklist | 第6章の条件を維持する |
| `HOIKUICT_PARENT_MAIL_TRANSPORT` | `smtp`を維持する |
| `HOIKUICT_SMTP_HOST` / `HOIKUICT_SMTP_PORT` | `127.0.0.1` / `9`。復元app内にこのportのlistenerがないことを事前確認する |
| `HOIKUICT_SMTP_STARTTLS` | `1` |
| `HOIKUICT_SMTP_USERNAME` / `HOIKUICT_SMTP_PASSWORD` | 空。稼働系のSMTP資格情報をmount・注入しない |
| `HOIKUICT_PARENT_MAIL_FROM` | `restore-test@example.invalid` |
| `HOIKUICT_PARENT_REGISTRATION_BASE_URL` / `HOIKUICT_ALLOWED_ORIGINS` | 管理経路だけで解決する復元用HTTPS origin。例は`https://restore-hoiku.example.invalid` |
| `FORWARDED_ALLOW_IPS` | 復元環境のHTTPS reverse proxy専用CIDR |
| `HOIKUICT_PUSH_TRANSPORT` / kiosk | `disabled` |
| DBと添付 | 同じbackup IDから復元した隔離datasetのみ |
| network | appと管理用HTTPS reverse proxyだけの`internal: true`の専用bridge。別の外向きnetworkを接続しない |
| ブラウザーの接続 | reverse proxyのHTTPSを管理用IPにだけbindし、host firewallで許可管理端末/VPNのみに制限。appのportは公開しない |

管理端末へ復元用hostnameの名前解決と信頼できるTLS証明書を設定する。reverse proxyは`Host`、`X-Forwarded-Proto`、`X-Forwarded-For`を適切に渡し、Secure Cookie・CSRFを無効化せずにログインを試験する。実際のIP、CIDR、証明書・秘密鍵のmount、proxy imageのdigestは実機準備時に記録する。

復元appから外部SMTPへの到達ができないこと、実際のSMTP設定が上記のループバックを指していること、Cloudflare routeがないことを確認してから起動する。内部networkの指定だけを過信せず、hostの経路・firewallと組み合わせて遮断を確認する。最初のファイル・DB検査だけを行う補助containerは`network_mode: none`で実行できる。

この方式は配送処理そのものを停止する実装ではなく、配送先へ接続させない構成である。復元appの起動後、保留中メールの配送失敗・再試行等で隔離DBが変化する可能性がある。送信エラーは想定内として記録し、試験前の復元copyを保持する。試験で変化したDBをそのまま稼働系へ切り替えない。起動検査はSMTPへの接続成功を要求しないが、復元先での実機確認は必要である。

### 10.2 復元・切替の順序

1. 障害時刻、最後の正常時点、復旧候補のbackup ID、許容損失を記録する。現行runtimeを変更前snapshotで保全する。
2. `COMPLETE`・hash・manifestを検査し、同じIDのDBと添付を隔離datasetへ復元する。snapshotからはruntime全体を復元し、稼働中DB本体だけを抜き出して上書きしない。
3. 対応するGit SHAと保管済みimageを用意し、第10.1節の通信遮断を確認する。
4. DB integrity、外部キー、期待schema、主要件数、添付、管理者ログイン、保護者の家庭分離を確認する。RPO/RTOの実績を記録する。
5. 切替用datasetは検査済みの同じbackupから改めて準備する。復元された古い職員・保護者session、初期有効化・再設定・招待等のtokenを専用CLIで全失効する。
6. 全失効CLIは確認対象コミットで未実装である。段階Cの運用を開始する前に実装し、失効済みtokenの拒否と再ログインを検証する。secretの変更だけでDB上のすべての認証記録が失効すると仮定せず、DB手編集で代用しない。
7. 復旧時点へ戻った送信待ちメール・招待が切替後に再配送されないよう、切替前の保留キュー点検・取消方法を確定して検証する。この整理を復元試験中の接続失敗だけに任せない。
8. appを停止してruntimeを切り替え、対応するimageで起動する。health、件数、認証、権限を再確認してからTunnelを再接続する。
9. 利用者へ復旧時点と再入力対象を案内する。検証dataset・証跡の保持と削除を記録する。

月1回以上の標準復元、3か月ごとのoff-site災害復旧・復号鍵確認、およびschema変更前の切戻し試験を実施する。

## 11. 更新・障害・撤去

更新は新SHAの自動テストと架空データ試験、停止時間・DB変更・戻し方の確認、正式バックアップと複製の確認後に行う。新imageへの切替時はappと使用中のworkerの版を揃え、manifestへ渡すSHA・image ID・Composeハッシュを更新する。schema変更後に古いimageだけへ戻さず、旧imageと更新直前のDB・添付を対で戻す。

| 事象 | 初動・代替運用 |
| --- | --- |
| app停止 | restart回数と直前ログを保全し、紙の登降園簿・電話へ切替 |
| Tunnel / Cloudflare障害 | 公開portを臨時追加せず、承認済み園内経路または紙・電話を使用 |
| pool・hardware異常 | 書込みを止め、pool状態を確認。隔離復元で調査 |
| 誤更新・誤削除 | 対象・操作者・時刻を記録し、追加更新を止める |
| 漏えい・資格情報侵害の疑い | 必要範囲のAccess・アカウントを停止し、ログ保全と責任者への連絡 |
| 秘密値漏えい | 用途ごとにrotateし、connector・sessionへの影響を確認 |

終了時はAccess/Tunnel route、stackを停止し、監査記録を保全する。runtime、snapshot、複製先、検証copy、recovery kitの保持・削除期限を決め、Tunnel token等を失効する。stackの削除だけでDBやバックアップが削除されたとは扱わない。

## 12. 受け入れ条件と残作業

### 12.1 段階A開始

- [ ] 対象full SHA、app image ID、cloudflared digest、Composeハッシュを記録した
- [ ] 付録Aを展開用構成へ反映し、production設定検査と実行ユーザーの権限確認に成功した
- [ ] ホストの8000番が閉じ、管理画面が非公開で、許可外identityをAccessが拒否する
- [ ] 初期管理者の有効化・ログアウト・再ログイン、Secure Cookie・CSRFを確認した
- [ ] 異なる外部端末のclient IPが誤って集約されず、ログインthrottleが機能する
- [ ] DB・添付がrestartとcontainer再作成後に保持される
- [ ] runtime snapshot、別系統への複製、停止バックアップ、メール遮断した隔離復元に成功した
- [ ] 架空データのみの利用、紙・電話への切替、試験責任者・緊急連絡先を参加者と確認した

### 12.2 段階C開始

1項目でも未完了なら実データ投入を開始しない。

- [ ] 段階A・Bを完了し、2週間以上の架空データ業務試験の重大問題を解消した
- [ ] リリース前チェックリストの該当項目を満たした
- [ ] 空DBへの移行パッケージの事前検証、一括確定、再実行、再起動後の家庭・園児リンク不変検査に成功した
- [ ] 初期管理者・職員のローカル認証、業務権限、直接URLを含む他家庭・未紐付け園児の拒否を確認した
- [ ] 実機でSMTP、保護者招待、password resetを確認した
- [ ] 正式な日次取得、別pool/off-site複製、保持・世代削除、失敗通知を構成した
- [ ] 全セッション・token失効CLIと復元後の保留メール処理を実装・検証した
- [ ] 対応imageとDB・添付の切戻し、月次復元、off-siteとrecovery kitからの復旧に成功し、実RPO/RTOを記録した
- [ ] CPU・メモリ・利用者数・添付量の測定から、利用規模・空き容量・停止時間を確定した
- [ ] 個人情報の利用目的・保存期間・削除・漏えい時連絡、保護者説明、公開方針を確認した
- [ ] サポート時間、更新・停止・切戻し判断者、Cloudflare/TrueNAS障害時の責任範囲を決めた

## 付録A. 改訂した公開試験用Compose例

これは本書に収録した展開用の例であり、リポジトリの`deploy/dockge/compose.yaml`を変更したものではない。build済みapp imageと必要なファイルを用意してから、新しいstackの`compose.yaml`として保存する。`pull_policy: never`はapp imageがhostにあることを前提とする。

```yaml
services:
  app:
    image: ${APP_IMAGE:?required}
    pull_policy: never
    restart: unless-stopped
    environment:
      TZ: Asia/Tokyo
      HOIKUICT_ENV: production
      HOIKUICT_DATABASE_URL: sqlite:////data/hoikuict.db
      HOIKU_FACILITY_BUNREI_DB_PATH: /data/facility.sqlite
      HOIKU_NURSERY_REF: ${HOIKU_NURSERY_REF:?required}
      HOIKUICT_ENABLE_MOCK_AUTH: "0"
      HOIKUICT_ENABLE_MOCK_ROLE_OVERRIDE: "0"
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
      - ${APP_SECRETS_PATH:?required}/password-blocklist.txt:/run/secrets/password-blocklist.txt:ro
    expose: ["8000"]
    networks: [pilot_network]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).read()"]
      interval: 30s
      timeout: 5s
      retries: 3

  cloudflared:
    image: ${CLOUDFLARED_IMAGE:?required}
    user: "65532:65532"
    restart: unless-stopped
    command: tunnel run --token-file /run/secrets/tunnel-token
    volumes:
      - ${APP_SECRETS_PATH:?required}/tunnel-token:/run/secrets/tunnel-token:ro
    networks: [pilot_network]
    depends_on:
      app:
        condition: service_healthy

  backup:
    image: ${APP_IMAGE:?required}
    pull_policy: never
    profiles: [operations]
    restart: "no"
    network_mode: none
    environment:
      TZ: Asia/Tokyo
      HOIKUICT_ENV: production
      HOIKUICT_DATABASE_URL: sqlite:////data/hoikuict.db
      HOIKU_FACILITY_BUNREI_DB_PATH: /data/facility.sqlite
      HOIKU_NURSERY_REF: ${HOIKU_NURSERY_REF:?required}
      HOIKUICT_STORAGE_ROOT: /app/storage
    volumes:
      - ${APP_RUNTIME_PATH:?required}/data:/data
      - ${APP_RUNTIME_PATH:?required}/storage:/app/storage
      - ${BACKUP_SET_PATH:?required}:/backup
    entrypoint: ["python", "-m", "scripts.backup_runtime"]
    command: ["--help"]

  backup-worker:
    image: ${APP_IMAGE:?required}
    pull_policy: never
    profiles: [backup-ui-trial]
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

cloudflaredの`65532:65532`は旧手順の値を明示したものであり、承認digestの実行userと一致することを確認する。tokenはそのuserが読める必要がある。secret用directoryの探索権限、blocklistのappuserによる読取りも別々に確認する。

## 付録B. 展開用`.env`の例

すべての`<...>`を実環境の値へ置き換える。秘密値をGit・チャット・ログに記録しない。`APP_IMAGE`はbuild済みtag、`BACKUP_APP_IMAGE`はそのimageの実際のIDを指定し、役割を分ける。

```dotenv
COMPOSE_PROJECT_NAME=open-hoikuict-pilot
APP_IMAGE=open-hoikuict:<approved-full-sha>
APP_RUNTIME_PATH=/mnt/<pool>/apps/open-hoikuict-pilot/runtime
APP_SECRETS_PATH=/mnt/<pool>/apps/open-hoikuict-pilot/secrets
BACKUP_SET_PATH=/mnt/<backup-pool>/backup/open-hoikuict-pilot/sets
BACKUP_GIT_SHA=<approved-full-sha>
BACKUP_APP_IMAGE=sha256:<actual-app-image-id>
BACKUP_COMPOSE_SHA256=<actual-compose-sha256>
CLOUDFLARED_IMAGE=cloudflare/cloudflared@sha256:<approved-digest>
PILOT_NETWORK_CIDR=172.30.50.0/24
PILOT_HOSTNAME=pilot-hoiku.example.jp
HOIKU_NURSERY_REF=<facility-reference>
HOIKUICT_SECRET_KEY=<random-fixed-value-1>
HOIKUICT_LOGIN_THROTTLE_HMAC_KEY=<random-fixed-value-2>
HOIKUICT_SMTP_HOST=<approved-smtp-host>
HOIKUICT_SMTP_PORT=587
HOIKUICT_SMTP_USERNAME=<smtp-user-if-required>
HOIKUICT_SMTP_PASSWORD=<smtp-password-if-required>
HOIKUICT_PARENT_MAIL_FROM=<approved-from-address>
```

値に`$`等を含める場合はComposeの`.env`の引用・展開規則に従って保存し、意図した値が渡ることを秘密値を表示せずに検証する。`.env`に書かれたdigestを記録へ転記するだけでなく、起動したcloudflaredが同じimageを使っていることを確認する。

## 付録C. 検証範囲と関連資料

2026年9月5日に、この文書から構成例を抽出し、次を確認した。既存文書・配布Compose・アプリコードは変更していない。

| 検証 | 結果・範囲 |
| --- | --- |
| Compose構文 | 全profileを対象に`docker compose config --quiet`が成功。架空設定を使用し、containerは起動していない |
| production必須設定 | 公開試験用と復元用の両方について、架空設定・一時blocklistを使った`validate_runtime_security()`が成功 |
| 構成間の対応 | `.env`の変数、app/backupのimage共有、cloudflaredの起動・記録値の共有、network・mountの境界を照合済み |
| 文書 | コードブロックの対応、文書内の相対リンク13件の参照先を確認済み |

値の検査に使う架空設定やblocklistは実運用には使用しない。実際のimage取得・build、container起動、権限、Tunnel、SMTP、負荷、snapshot・複製・復元は第12章で確認する。

- [旧構成仕様](pilot-deployment-spec.md)
- [旧試験手順書](truenas-dockge-cloudflare-pilot-runbook.md)
- [バックアップ・復元仕様](backup-restore-spec.md)
- [本番データ移行仕様](beta-production-data-migration-spec.md)
- [ローカル認証仕様](local-authentication-spec.md)・[保護者認証仕様](parent-local-authentication-spec.md)
- [環境分離方針](environment-profiles.md)
- [リリース前チェックリスト](release-checklist.md)
- [Cloudflare Tunnel run parameters](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/)
- [Docker build context / dockerignore](https://docs.docker.com/build/concepts/context/)
