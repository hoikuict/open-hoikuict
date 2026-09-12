# バックアップ・復元仕様

> 文書版: 1.0  
> 基準日: 2026年8月31日  
> 状態: 現行運用契約（backup helper・管理画面・日次/週次worker schedule実装済み、TrueNAS snapshot schedule・replication未実装）  
> 対象: TrueNAS・Dockge上で稼働するopen-hoikuictの実運用試験環境

## 1. 目的

誤操作、アプリ更新失敗、SQLite破損、TrueNAS pool障害、管理者アカウント侵害等が起きた場合に、園児・家庭・認証・業務記録・添付ファイルを、承認した復旧時点へ一貫して戻せるようにする。

バックアップは取得しただけでは完了としない。整合性検査、別系統への複製、監視、定期的な復元試験までを1つの管理対象とする。

## 2. 適用範囲

本仕様は次に適用する。

- 架空データによる技術・業務試験
- 限定実データ試験
- TrueNAS上のSQLiteと添付ファイル
- 更新前、データ移行前、設定変更前の手動バックアップ
- 障害、誤更新、災害からの復元

本仕様の保持期間は技術的な復旧用バックアップの基準であり、法令、自治体、法人規程に基づく文書保存年限を代替しない。長期保存が必要な記録は別の記録保存・アーカイブ仕様で管理する。

## 3. 用語

| 用語 | 意味 |
| --- | --- |
| runtime dataset | 稼働中DBと添付ファイルを同じ復旧時点で保護するTrueNAS dataset |
| snapshot | TrueNAS/ZFS上の読取専用の時点コピー。同一pool内だけでは独立したバックアップと数えない |
| backup set | DB、添付、manifest、hash、検査結果をまとめた可搬性のある一式 |
| local replica | sourceとは別poolへ複製したsnapshotまたはbackup set |
| off-site copy | source TrueNASとは別の装置・障害領域に置く暗号化済みコピー |
| RPO | 障害時に失うことを許容する最大データ期間 |
| RTO | 障害発生から業務を復旧させるまでの目標時間 |
| application-consistent | DBと添付を含む書込みを停止・調停し、アプリのデータ関係が壊れない復旧点 |
| crash-consistent | 突然停止と同等の時点。SQLiteの回復は期待できるが、アプリ全体の整合を別途検査する必要がある |

## 4. 保護対象

### 4.1 必須対象

runtime datasetを次の形に統一する。`<pool>`は実環境のpool名に置き換える。

```text
/mnt/<pool>/apps/open-hoikuict-pilot/runtime/
├── data/
│   ├── hoikuict.db
│   ├── hoikuict.db-wal       # 稼働中に存在する場合がある
│   ├── hoikuict.db-shm       # 稼働中に存在する場合がある
│   ├── facility.sqlite
│   └── data_transfer_previews/
└── storage/
    ├── notice_attachments/
    └── message_attachments/
```

| 対象 | 重要度 | 理由 |
| --- | --- | --- |
| `data/hoikuict.db` | 必須 | 業務データ、認証、session、監査、計画文書の正本 |
| 稼働中の`hoikuict.db-wal` / `-shm` | snapshotでは必須 | WAL modeのDBを時点ごと復元するため、DBと同じdatasetで保全する |
| `data/facility.sqlite` | 必須 | 施設固有の文例データ。アプリから更新される |
| `storage/notice_attachments` | 必須 | お知らせ添付。DBの`notice_attachments`行と対になる |
| `storage/message_attachments` | 必須 | 職員ルーム添付。DBの`message_attachments`行と対になる |

`hoikuict.db`、WAL、SHMを別datasetや別mountへ分離しない。添付はDB行と同じ復旧時点が必要なため、DBと同じruntime dataset内に置く。

### 4.2 backup setから除外できる対象

| 対象 | 方針 |
| --- | --- |
| `data_transfer_previews` | 24時間以内の一時fileで再生成可能なため、可搬backup setから除外可。ZFS snapshotに含まれることは許容 |
| source code | Git SHA/tagから復元する。backup setにはGit SHAだけを記録 |
| container image | registryまたは同じSHAから再buildする。image ID/digestだけを記録 |
| bundled corpus / seed | 承認したimageから復元する。runtimeで更新される`facility.sqlite`とは区別する |
| cache、一時file、`__pycache__` | 除外 |

### 4.3 秘密情報

次は通常のデータbackup setへ同梱しない。

- `.env`
- `HOIKUICT_SECRET_KEY`
- `HOIKUICT_LOGIN_THROTTLE_HMAC_KEY`
- SMTP password
- Cloudflare Tunnel token
- kiosk token
- 将来のcredential encryption key
- TrueNAS dataset/replicationの復号鍵

復旧に必要な秘密値は、暗号化した別のrecovery kitとしてpassword managerおよび承認済みのオフライン保管先へ保存する。backup setと復号鍵を同じ場所だけに置かない。Tunnel tokenやSMTP passwordは、復旧時にrotateできるものとして手順を用意する。

## 5. 保存構成

最低でも次の3系統を持つ。

| copy | 場所 | 役割 |
| --- | --- | --- |
| 1 | 稼働runtime dataset | 現行データ |
| 2 | 別poolのlocal replicaまたは暗号化backup dataset | 誤削除、更新失敗、source pool以外の局所障害 |
| 3 | 別装置・別障害領域の暗号化off-site copy | TrueNAS本体、pool、設置場所、管理者侵害の影響分離 |

同一pool内のsnapshotはcopy 1の履歴であり、copy 2には数えない。同一TrueNASの別poolはcopy 2にはできるが、筐体故障、盗難、災害には耐えないためcopy 3を省略しない。

## 6. RPO・RTO

| 障害 | RPO | RTO | 復旧元 |
| --- | --- | --- | --- |
| container停止・再作成 | 0分を目標 | 30分 | 同じruntime dataset |
| 誤更新・誤削除・アプリ更新失敗 | 15分以内 | 2時間以内 | 15分snapshotまたは更新前snapshot |
| source dataset破損 | 24時間以内 | 4時間以内 | 検証済みlocal replica / backup set |
| TrueNAS本体・source pool喪失 | 24時間以内 | 24時間以内 | off-site copy |
| 管理者侵害・ransomware想定 | 24時間以内 | 24時間以内 | sourceから削除不能な別credential/別装置のcopy |

RPO/RTOを超える見込みが出た時点で、[運用責任と本番導入前チェック](operations.md)に定める紙・電話等の代替運用へ切り替える。実績値は毎回の復元試験で更新する。

## 7. 取得方式

### 7.1 15分snapshot

- runtime dataset全体を15分ごとにsnapshotする。
- 稼働中のためcrash-consistentとして扱う。
- `hoikuict.db`だけをsnapshotから取り出して稼働環境へ上書きしない。runtime dataset全体を隔離先へclone/restoreして検査する。
- SQLite WALはDBの永続状態の一部であるため、snapshotではDB、WAL、SHMを同じ時点で保持する。

### 7.2 日次application-consistent backup

毎日02:10 JSTを標準開始時刻とする。園の運用時間に合わない場合は、利用者がいない時間へ変更し、時刻を運用台帳へ記録する。

添付fileとDB行をまとめて固定するアプリ全体のbackup lockは現在未実装である。このため実装されるまでは、次の停止方式を正とする。

1. backup開始を記録する。
2. `app`を停止し、書込みprocessが終了したことを確認する。
3. runtime datasetの`application-consistent` snapshotを作る。
4. appを起動し、health、login、主要画面を確認する。
5. snapshotから外部公開しない書込み可能cloneを作る。
6. clone上の`hoikuict.db`と`facility.sqlite`をSQLite APIで開き、backup set用の独立DBを作成する。
7. 添付directoryを同じcloneからbackup setへコピーする。
8. manifestとSHA-256 hashを作成する。
9. 第9節の自動検査を行う。
10. 全検査合格後に`COMPLETE` markerを最後に作る。
11. backup setを別poolとoff-siteへ複製し、copy後のhashを確認する。
12. 成功したbackup IDと複製先を記録し、作業用cloneを削除する。

appの停止時間はsnapshot作成と再起動確認を含め10分以内とする。cloneからのbackup set作成・検査・複製はapp再開後に継続できる。停止が10分を超えた場合は失敗ではなく運用警告とし、原因と実績を記録する。

将来、停止なしのbackupへ移行する場合は次をすべて満たす。

- `sqlite3.Connection.backup()`等のSQLite Online Backup APIを使う。
- DB backup中の`SQLITE_BUSY`をtimeout・再試行できる。
- お知らせ・職員ルームの添付作成、削除、DB commitを同じbackup lockで調停する。
- backup開始後のDBと添付が同じ論理時点になることを並行書込みtestで確認する。
- 稼働中の`.db`単体file copyを使用しない。

### 7.3 更新・移行前backup

次の前には、日次時刻を待たずapplication-consistent backupを取得する。

- app imageまたはGit SHAの更新
- DB schemaを変更するコードの起動
- 一括import、データ移行、家庭統合等の大量更新
- 認証方式、secret、storage mountの変更
- TrueNAS、Docker、Dockgeのmajor update

backupの検査が不合格、またはoff-site/local replicaの少なくとも一方へ複製できない場合、変更を開始しない。

## 8. backup set形式

directory名はUTCで一意にする。

```text
open-hoikuict_20260831T171000Z_<git-sha-12>/
├── db/
│   ├── hoikuict.db
│   └── facility.sqlite
├── storage/
│   ├── notice_attachments/
│   └── message_attachments/
├── manifest.json
├── verification.json
├── SHA256SUMS
└── COMPLETE
```

Online Backup APIまたは停止後のSQLite接続で作った`db/hoikuict.db`は単独で開ける成果物とし、`-wal`と`-shm`を可搬backup setへ個別に同梱しない。ZFS snapshotはruntime dataset全体を保持するため、この制約の対象外とする。

### 8.1 manifest必須項目

- 仕様版
- backup ID
- 開始・終了時刻（UTCとAsia/Tokyo）
- 環境名、施設識別子。ただし園児・保護者等の個人情報を含めない
- Git SHA / tag
- app image IDまたはdigest
- cloudflared image digest
- Compose fileのSHA-256
- source DB pathとSQLite version
- 各fileの相対path、byte数、SHA-256
- 主要tableの件数
- 添付DB行数、添付file数、総byte数
- backup方式（停止 / online API）
- 実施者または自動job ID
- retention class

manifest、log、directory名に氏名、住所、メールアドレス、健康情報を入れない。

## 9. 自動検査

backup setを成功扱いする前に次をすべて行う。

| 検査 | 合格条件 |
| --- | --- |
| 完了marker | すべてのcopy・検査後に`COMPLETE`が作成されている |
| hash | 全fileのSHA-256が`SHA256SUMS`と一致 |
| SQLite integrity | `PRAGMA integrity_check`が`ok`のみを返す |
| 外部キー | main DBの`PRAGMA foreign_key_check`が0行 |
| schema | 必須table・columnが承認済みGit SHAの期待と一致 |
| 主要件数 | 前回値との差が設定閾値内。大幅減少は承認がない限り失敗 |
| 添付参照 | DBが参照する全添付fileが存在し、記録sizeと実sizeが一致 |
| orphan添付 | DB参照のないfileは警告として列挙し、自動削除しない |
| 秘密情報 | manifestや通常logへsecret値が出ていない |
| copy | local/off-siteのcopy後hashがsource backup setと一致 |

`PRAGMA integrity_check`は外部キー違反を検出しないため、`PRAGMA foreign_key_check`を別に実行する。

1項目でも不合格ならdirectoryへ`COMPLETE`を作らず、前回の正常backupを削除せず、運用責任者へ通知する。

## 10. 保持期間

| 種別 | 頻度 | source保持 | local/off-site保持 |
| --- | --- | --- | --- |
| rolling snapshot | 15分ごと | 48時間 | 原則複製しない |
| daily application-consistent | 毎日 | 35日 | 35日 |
| monthly | 月末または毎月最終正常日次 | 13か月 | 13か月 |
| change backup | 更新・移行前 | 次の正常更新と復元試験完了まで。最低35日 | 同左 |

保持期限を過ぎたcopyは、次を確認してから自動削除できる。

- より新しい正常backupが存在する。
- 直近のoff-site複製が成功している。
- 復元試験期限を超過していない。
- hold、事故調査、法令・法人規程による保全指示がない。

保持設定を変更する場合は、既存snapshotの命名schemaと自動削除対象が一致することをTrueNASで確認する。容量不足を理由に未確認のsnapshotやbackupを手動一括削除しない。

## 11. 暗号化・アクセス制御

- runtime、local backup、off-site destinationは暗号化datasetまたは同等の保存時暗号化を使用する。
- remote replicationはSSH等の暗号化された経路を使用する。
- backup復号鍵はsource TrueNASだけに依存せず、承認済みの別保管先へ置く。
- backup操作権限と復号鍵管理権限を可能な範囲で分離する。
- backup datasetをSMB/NFSで一般利用者へ共有しない。
- app containerへbackup destinationの削除権限を与えない。
- off-site copyはsource側の通常app/Dockge credentialだけでは削除できない構成にする。
- backup downloadや復元操作を監査記録へ残す。

backupにはpassword hash、session hash、監査、健康情報、家庭情報が含まれるため、本番DBと同等以上に保護する。

## 12. 容量管理と監視

次を異常として通知する。

| 条件 | severity |
| --- | --- |
| 15分snapshotが30分以上作成されていない | warning |
| 日次backupが予定終了から2時間以内に成功しない | critical |
| off-site replicationの最終成功から26時間超 | critical |
| integrity / foreign key / hash / 添付検査の不合格 | critical |
| runtimeまたはbackup pool使用率80%以上 | warning |
| 90%以上 | critical。新規大量import・更新を停止 |
| 月次復元試験が35日以上未実施 | critical |
| recovery keyの検査が4か月以上未実施 | warning |

backup開始前に、destinationへ直近backup setの2倍以上の空き容量があることを確認する。実容量の増加傾向を月次で見直す。

## 13. 復元方式

### 13.1 原則

- 最初から稼働datasetへrollbackしない。
- backup/snapshotを隔離datasetへcloneまたはrestoreし、検査後に切り替える。
- DBと添付を同じbackup IDから復元する。
- DB table単位の手作業復元や、新旧DBの直接mergeを標準手順にしない。
- schema変更を含む場合、DBとGit SHA / imageを対で戻す。
- 障害調査用に、壊れた現行datasetも変更前snapshotとして保全する。

### 13.2 復元手順

1. incident ID、障害時刻、最後の正常操作時刻を記録する。
2. 期待する復旧時点と想定データ損失を業務責任者が承認する。
3. 対象backupの`COMPLETE`、hash、manifest、検査結果を確認する。
4. 隔離datasetへDBと添付を同じbackup IDから復元する。
5. manifest記載のGit SHA / imageを用意する。
6. Cloudflare Tunnelを接続せず、外部mail送信を遮断した検証stackへmountする。
7. `integrity_check`、`foreign_key_check`、schema、主要件数、添付参照を再検査する。
8. アプリを起動し、health、管理者login、代表画面、保護者分離を確認する。
9. 復元された古いsession、action code、password reset token、招待tokenを全失効する。
10. TrueNASで壊れた現行runtimeの保全snapshotを取る。
11. appを停止し、検証済みruntimeへmountを切り替える。
12. 同じGit SHA / imageで起動し、再度smoke testする。
13. Cloudflare Tunnelを再接続する。
14. 利用者へ復旧時点、失われた可能性のある期間、再入力対象を通知する。
15. 実RPO/RTO、判断者、実施者、結果を記録する。

全session/token失効用の安全なCLIが未実装の場合、限定実データ試験へ進まない。DBを直接手編集して代用しない。

### 13.3 添付だけの復元

DB行が残り、対応fileだけが欠損している場合は、同じまたはそれ以前の正常backupからhash・sizeを確認して個別fileを復元できる。DB行を復活させる必要がある場合は個別復元を行わず、隔離環境でDB全体の復元または承認済みデータ修復を行う。

## 14. 復元試験

| 試験 | 頻度 | 内容 |
| --- | --- | --- |
| 標準復元 | 毎月 | 直近日次backupを隔離datasetへ復元し、全自動検査とsmoke test |
| update rollback | schema変更またはmajor update前 | 旧Git SHAと更新前DBを対で戻す |
| 災害復旧 | 3か月ごと | source TrueNASを使わずoff-site copyとrecovery kitから復元 |
| 添付整合 | 毎月 | DB参照、file存在、size、hashの照合 |
| recovery key | 3か月ごと | 隔離環境で復号・unlockできることを確認 |

試験は実際のproduction datasetを直接rollbackせず、外部公開なしの隔離環境で行う。実データを使う復元試験環境もproduction相当のアクセス制御・暗号化・削除手順を適用する。

### 14.1 合格証跡

- backup IDと復元元
- 試験開始・終了時刻
- 実施者、確認者
- Git SHA / image digest
- 全検査結果
- 代表画面の確認結果。個人情報を含むscreenshotは証跡に添付しない
- 実RPO/RTO
- 問題、是正期限、担当者
- 試験用clone/datasetの削除日時

## 15. 役割

| 役割 | 責任 |
| --- | --- |
| 運用責任者 | RPO/RTO、保持、復旧時点、Go/No-Goの承認 |
| backup管理者 | snapshot、replication、暗号化、容量、job監視 |
| app管理者 | backup helper、DB/添付検査、対応Git SHAの提示 |
| 業務確認者 | 主要件数、代表画面、失われた期間と再入力の確認 |
| security責任者 | backup access、鍵、事故時保全、廃棄承認 |

backup作成者と月次復元の確認者は、可能な範囲で別の人にする。

## 16. 廃棄

- retention満了または試験終了時は、source snapshot、local replica、off-site copy、検証clone、download済みcopyを一覧化する。
- ZFS snapshotが残っている間は元fileを削除してもデータが残ることを前提にする。
- 暗号化copyはcopy削除に加えて、必要に応じて専用復号鍵の破棄を行う。
- hold、事故調査、法的保全があるcopyを削除しない。
- 対象、backup ID、場所、削除日時、実施者、承認者を記録する。

## 17. 実装前の阻害事項

### 実装済み

- `scripts/backup_runtime.py create`: SQLite Online Backup API、DB・添付copy、manifest、SHA-256、整合性検査、`COMPLETE` marker
- `scripts/backup_runtime.py verify`: 保存後・復元前のhash、DB、外部キー、添付再検査
- `scripts/backup_worker.py`: 管理画面の依頼をnetworkなしで処理し、SQLite書込みlock中にDBと添付を取得
- `/settings/backups`: 管理者限定の即時backup、worker状態、履歴、検証結果表示。削除・download・復元機能は持たない
- `/settings/backups`の定期実行設定: JST基準の毎日または毎週、実行時刻、曜日、有効・無効をruntimeへ保存
- `scripts/backup_worker.py`のscheduler: 同一日中は予定時刻後の起動時にcatch-upし、過去日・過去週は持ち越さず、job履歴の予定枠と照合して二重実行を防止
- `test_backup_runtime.py`と`test_backup_jobs.py`: WAL、添付、欠損、改ざん、path traversal、権限、二重実行、worker結合の自動test
- `deploy/dockge/compose.yaml`のoperations profile `backup` service: networkなしでruntimeとbackup destinationだけをmount
- `deploy/dockge/compose.yaml`の`backup-worker` service: appにbackup保存先をmountせず、専用serviceだけへ書込み権限を付与

### 段階A開始前

- [ ] `storage/notice_attachments`と`storage/message_attachments`をruntime datasetへ永続mountする
- [ ] runtime dataset全体の15分snapshotを設定する
- [ ] app停止中の手動application-consistent snapshot手順を実施する
- [ ] 別poolまたは別装置へ少なくとも1つ複製する
- [ ] 隔離datasetへの復元を1回成功させる

### 限定実データ試験前

- [x] SQLite backup、manifest、hash、DB/添付検査を行うbackup helperを実装する
- [ ] TrueNAS snapshot clone、backup helper、複製、世代削除を日次jobとしてorchestrationする
- [ ] job失敗、replication遅延、容量、復元期限のalertを実装する
- [ ] 暗号化off-site copyを設定する
- [ ] session/action token一括失効CLIを実装する
- [ ] 月次標準復元と四半期災害復旧の担当・日程を登録する
- [ ] recovery kitを別保管し、source TrueNASなしで復号試験する

## 18. 参考資料

- [SQLite Online Backup API](https://sqlite.org/backup.html)
- [Python sqlite3 Connection.backup](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup)
- [SQLite WAL](https://sqlite.org/wal.html)
- [SQLite PRAGMA integrity_check / foreign_key_check](https://sqlite.org/pragma.html#pragma_integrity_check)
- [TrueNAS Periodic Snapshot Tasks](https://www.truenas.com/docs/scale/26/dataprotection/periodicsnapshottasks/addingperiodicsnapshottasks/)
- [TrueNAS Replication Tasks](https://www.truenas.com/docs/scale/26/dataprotection/replication/)
- [TrueNAS Encrypted Replication](https://www.truenas.com/docs/scale/26/dataprotection/replication/advancedreplication/replicationwithencryption/)
