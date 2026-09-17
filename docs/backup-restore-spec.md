# バックアップ・復元仕様

> 文書版: 1.2<br>
> 改訂日・実装確認日: 2026年9月14日<br>
> 状態: 形式2・追加検査・隔離復元CLIをローカル実装。実機反映・運用受入は別途確認。<br>
> 対象: TrueNAS・Dockge上で稼働するopen-hoikuictの実運用試験環境

## 確認状況 { #implementation-status }

本書は必要な運用と実装の基準を定める。以下の実装状況と、施設ごとの設定・受入結果を分けて読む。取得頻度・保持期間・RPO/RTOの値は目標であり、達成実績ではない。

| 項目 | 2026年9月14日時点の実装・検証 |
| --- | --- |
| 主DB・施設文例DB・storage・定期実行設定の保存 | 形式2のCLIとworkerに実装。形式1の読取りも維持 |
| hash、DB integrity、外部キー、全添付・必須schemaの検査 | 文書確認依頼のJSON参照、登録済みschema契約、主要件数の前回比較を含め実装 |
| 園児・保護者の写真、園児の性別 | 主DBへ保存。現在・申請・履歴の参照と画像読込みを検査。架空データで復元を検証 |
| 管理画面・毎日/毎週のworker schedule | 実装済み。TrueNASのworkerは試験用profileで、初期scheduleは無効 |
| 形式1の追加検査・形式2への変換 | `verify --schema-contract`と`convert-legacy`を実装。登録済み契約で検査し、元setを変更しない |
| 複製・証跡・外部監視 | `scripts.backup_operations`に複製・照合、復元試験記録、未取得・失敗等の監視と通知コマンド連携を実装。保存時暗号化・別障害系統は運用者の確認記録に依存 |
| 正式な停止方式・snapshot・世代整理 | TrueNAS/ホスト側の構成が必要。アプリworkerはこれらを実行しない。自動世代削除は未実装 |
| 復元後の全session/token失効・送信待ちキュー整理 | `prepare-restore`が新しい隔離先へ復元する際に実行。旧jobを導入せず、定期実行は無効にする |
| 実機の受入 | 更新前の主DBコピー・runtime snapshot・DBコピーの移行検証は実績あり。通常の日次取得、全種類の添付・写真・設定の一式復元、別系統複製、暗号化の適合は未確認 |

施設固有の接続先、保存先、暗号化・復号鍵の設定、検査結果はアクセスを制限した運用台帳に記録する。コードの存在や更新処理の成功から、実機のバックアップ運用が完成したと判定しない。

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
| backup set | DB、添付、運用設定、manifest、hash、検査結果をまとめた可搬性のある一式。旧形式1の運用設定の不足は第8.3節を参照 |
| local replica | sourceとは別poolへ複製したsnapshotまたはbackup set |
| off-site copy | source TrueNASとは別の装置・障害領域に置く暗号化済みコピー |
| RPO | 障害時に失うことを許容する最大データ期間 |
| RTO | 障害発生から業務を復旧させるまでの目標時間 |
| application-consistent | DBと添付を含む書込みを停止・調停し、アプリのデータ関係が壊れない復旧点 |
| crash-consistent | 突然停止と同等の時点。SQLiteの回復は期待できるが、アプリ全体の整合を別途検査する必要がある |

### 3.1 成功の段階 { #verification-stages }

| 段階 | 合格条件・記録 |
| --- | --- |
| 取得済み | 対象のDB・添付・設定を保存した。まだ復旧元として選定しない |
| 検査済み | 対象版に必要な第9.1節の検査を通過した。検査の基準版・結果・時刻を記録する |
| 別系統保存済み | 指定した複製先で第9.2節の照合を通過した。保存先ごとに結果を記録する |
| 復元試験済み | 隔離環境の起動・認証・代表画面と復旧時間を確認した。試験したbackup IDを記録する |

形式1の旧画面の「成功」は当時のローカル検査の通過を示す。形式2の`COMPLETE`は本書のローカル検査の合格を示し、管理画面では「作成完了」と4段階の結果を表示する。複製・復元試験・本改訂の追加検査の合格は別途確認する。未実行の検査は「未確認」、対象版に機能が存在しない検査は根拠付きの「該当なし」とし、合格に読み替えない。

段階の記録は同じbackup IDとmanifestのhashに紐付ける。公開済みsetのmanifestやhashを書き換えず、複製・復元試験の結果は別の運用証跡として追記・保管する。

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
│   ├── backup-control/
│   │   └── schedule.json
│   └── data_transfer_previews/
└── storage/
    ├── notice_attachments/
    ├── message_attachments/
    └── document_reviews/
```

| 対象 | 重要度 | 理由 |
| --- | --- | --- |
| `data/hoikuict.db` | 必須 | 業務データ、認証、session、監査、計画文書の正本。園児の性別、`profile_photos`の画像と写真参照、変更申請・履歴も含む |
| 稼働中の`hoikuict.db-wal` / `-shm` | snapshotでは必須 | WAL modeのDBを時点ごと復元するため、DBと同じdatasetで保全する |
| `data/facility.sqlite` | 必須 | 施設固有の文例データ。アプリから更新される |
| `storage/notice_attachments` | 必須 | お知らせ添付。DBの`notice_attachments`行と対になる |
| `storage/message_attachments` | 必須 | 職員ルーム添付。DBの`message_attachments`行と対になる |
| `storage/document_reviews` | 必須 | 文書確認依頼の添付。`document_review_requests.attachments`のJSON内のpath・sizeと対になる |
| `data/backup-control/schedule.json`の設定値 | 形式2で必須 | 定期実行を再設定するための値。第4.4節の項目だけを正規化して保存する。形式1には含まれない |

`hoikuict.db`、WAL、SHMを別datasetや別mountへ分離しない。添付はDB行と同じ復旧時点が必要なため、DBと同じruntime dataset内に置く。

写真はファイル添付ではなくDB内の画像を保存する。現在の表示写真だけでなく、変更申請や履歴から参照する過去の写真も対象とする。現在の写真を削除・差し替えしても過去の画像が残る実装に合わせ、容量見積もりと保持・廃棄の対象に含める。

### 4.2 backup setから除外できる対象

| 対象 | 方針 |
| --- | --- |
| `data_transfer_previews` | 24時間以内の一時fileで再生成可能なため、可搬backup setから除外可。ZFS snapshotに含まれることは許容 |
| source code | Git SHA/tagから復元する。backup setにはGit SHAだけを記録 |
| container image | registryまたは同じSHAから再buildする。image ID/digestだけを記録 |
| bundled corpus / seed | 承認したimageから復元する。runtimeで更新される`facility.sqlite`とは区別する |
| cache、一時file、`__pycache__` | 除外 |
| backup-controlの待機中・実行中・rejected jobとworker heartbeat | 可搬setから除外。snapshotから復元する場合も隔離し、復元先の実行制御へ再投入しない |
| backup-controlのjob履歴 | 稼働用制御としては復元しない。必要な監査履歴は別の運用証跡として保管し、backup IDとの対応を保持する |

### 4.3 秘密情報

次は通常のデータbackup setへ同梱しない。

- `.env`
- `HOIKUICT_SECRET_KEY`
- `HOIKUICT_LOGIN_THROTTLE_HMAC_KEY`
- SMTP password
- Web PushのVAPID秘密鍵
- Cloudflare Tunnel token
- kiosk token
- 将来のcredential encryption key
- TrueNAS dataset/replicationの復号鍵

復旧に必要な秘密値は、暗号化した別のrecovery kitとしてpassword managerおよび承認済みのオフライン保管先へ保存する。backup setと復号鍵を同じ場所だけに置かない。Tunnel tokenやSMTP passwordは、復旧時にrotateできるものとして手順を用意する。

recovery kitには対応する設定版・Compose・必要な鍵やblocklistの再準備方法を記録する。通常setのmanifestにはkitの識別子だけを入れ、秘密値や復号鍵を含めない。更新用に退避する`env.before`等も同じ保護対象とし、平文の設定退避を暗号化済みrecovery kitの代わりにしない。

### 4.4 定期実行設定の保存・復元 { #schedule-recovery }

形式2では`settings/backup-schedule.json`を保存する。保存する項目は`schema_version`、`enabled`、`frequency`、`run_time`、`weekday`、`timezone`に限定し、`schema_version`は整数の`1`、`timezone`は`Asia/Tokyo`とする。有効・無効は真偽値、頻度は`daily`または`weekly`、時刻は24時間表記の`HH:MM`、曜日は月曜を0とする0〜6で検査する。元ファイルがない場合は、無効・毎日02:00・曜日0の既定値を保存し、manifestの`settings_source`を`default`、存在する場合は`stored`と記録する。不正な既存設定を既定値で置き換えて成功扱いにしない。

元の有効状態はset内で保持するが、復元先へ導入する設定は必ず無効にする。保存先・時刻・保持・通知先を担当者が確認してから、稼働系で明示的に再開する。設定の更新者名や古いjob・heartbeatはこのファイルへ含めない。`create`が正規化して保存し、`prepare-restore`が無効な設定として導入する。

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

workerのSQLite書込みlockは実装済みだが、添付の作成・削除・失敗時cleanupとDB commit、定期実行設定をまとめて固定するアプリ共通lockは未実装である。正式な日次・更新前の取得には次の停止方式を使う。以下は形式2の取得手順である。実行例は[バックアップ検証手順](backup-verification-guide.md)を参照する。形式1を使う場合の不足への対応は第8.3節に従う。

1. backup開始を記録する。
2. 実行中のbackup jobの終了を確認してworkerを停止する。`app`とその他のruntime書込み処理も停止し、終了を確認する。
3. runtime datasetの`application-consistent` snapshotを作る。
4. appを起動し、health、login、主要画面を確認する。
5. snapshotから外部公開しない書込み可能cloneを作る。
6. clone上の`hoikuict.db`と`facility.sqlite`をSQLite APIで開き、backup set用の独立DBを作成する。
7. 全添付directoryと第4.4節の設定値を、同じcloneからbackup setへ保存する。
8. DB・添付・設定と復元元の検査を行い、manifestと`verification.json`を作成する。
9. SHA-256 hashを作成し、第9.1節の一覧・hashを含む最終検査を行う。形式1の不足は第8.3節の追加検査で補う。
10. ローカル検査合格後に`COMPLETE` markerを最後に作り、setを公開する。形式1を使う場合は追加検査の証跡を別途保存する。
11. backup setを別poolとoff-siteへ複製し、第9.2節の検査を行う。
12. backup IDごとの取得・検査・複製の結果を記録する。必要な証跡を保全してから作業用cloneを削除する。

appの停止時間はsnapshot作成と再起動確認を含め10分以内とする。cloneからのbackup set作成・検査・複製はapp再開後に継続できる。停止が10分を超えた場合は失敗ではなく運用警告とし、原因と実績を記録する。

将来、停止なしのbackupへ移行する場合は次をすべて満たす。

- `sqlite3.Connection.backup()`等のSQLite Online Backup APIを使う。
- DB backup中の`SQLITE_BUSY`をtimeout・再試行できる。
- 全種類の添付作成・削除・失敗時cleanup・DB commitと設定変更を同じbackup lockで調停する。
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

更新用ヘルパーの主DBコピー・runtime snapshot・設定退避を、通常の可搬setとは別の更新復旧用保存物として記録する。この方式でも施設文例DB・全添付・設定の同時点性、秘密情報の保護、別系統への複製、対応する旧版での復旧確認が必要である。更新処理の成功だけで日次取得・複製・復元試験の完了と扱わない。

### 7.4 管理画面とworkerの定期実行 { #worker-schedule }

現行のTrueNAS用workerは`backup-ui-trial` profileに属し、段階A・Bの補助機能として検証する。通常起動では動かない。初期scheduleは無効・毎日02:00 JSTであり、正式な停止方式の日次取得の標準02:10とは別の設定である。

当日分は予定時刻後に起動した場合に1回実行する。過去日・過去週は持ち越さない。同じ予定枠の履歴があれば、失敗でも自動再登録しない。現行workerに失敗時の自動再試行はなく、運用担当者が原因を確認してから再実行を依頼する。

正式運用では初回失敗を通知し、再実行したjobを元の失敗job・予定枠と対応付ける。未完了のsetを上書きせず、新しいbackup IDを使用する。workerが起動せずjobが作られない場合や、予定日を過ぎた場合も第12節の未取得通知の対象とする。再実行元job・予定枠の連携を実装済み。外部通知はホスト側で`backup_operations monitor`と通知コマンドを設定する。worker自身はnetworkなしで動かす。

画面と運用台帳には第3.1節の段階を表示・記録する。現在の画面の「成功」を、複製・復元試験まで完了した表示に読み替えない。検証用workerの停止時はscheduleを無効にし、再開前に保存済み設定を確認する。

## 8. backup set形式

文書版1.2とbackup setの`format_version`は別に管理する。作成CLIは形式2を出力し、検証CLIは形式1・2を読み取る。directory名はUTC（マイクロ秒）・Git SHA先頭12桁・ランダム8桁で一意にし、衝突時は既存setを上書きしない。

```text
open-hoikuict_20260831T171000Z_<git-sha-12>/
├── db/
│   ├── hoikuict.db
│   └── facility.sqlite
├── storage/
│   ├── notice_attachments/
│   ├── message_attachments/
│   └── document_reviews/
├── settings/
│   └── backup-schedule.json
├── manifest.json
├── verification.json
├── SHA256SUMS
└── COMPLETE
```

Online Backup APIまたは停止後のSQLite接続で作った`db/hoikuict.db`は単独で開ける成果物とし、`-wal`と`-shm`を可搬backup setへ個別に同梱しない。ZFS snapshotはruntime dataset全体を保持するため、この制約の対象外とする。

### 8.1 manifest必須項目（形式2）

- `format_version: 2`、検査基準版、対象Git SHAに対応するschema検査契約の識別子・hash
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
- 第4.4節の`settings_source`と、対応するrecovery kitの識別子
- 件数比較の基準となる前回setのbackup ID・検査済みmanifestのhash・しきい値設定の識別子。初回はその事実と確認記録の識別子

manifest、log、directory名に氏名、住所、メールアドレス、健康情報を入れない。

Git SHA・image・Compose・schema検査契約を特定できないsetは、形式2では検査済みとしない。形式2のworkerはゼロ埋めGit SHA・Compose hash、未固定image、recovery kit記録の不足を失敗として扱う。実施者は個人名の代わりに運用記録の識別子で対応付ける。

### 8.2 不変性と公開

DB・storage・settingsをpayloadとして`manifest.files`に列挙し、各path・size・hashを実体と照合する。`SHA256SUMS`は全payloadと`manifest.json`・`verification.json`を対象にし、自身と最後に作る`COMPLETE`は対象外とする。これらの管理file以外の未登録file、hash対象の欠落、重複path、絶対path、親directoryへの逸脱、symbolic linkは失敗にする。

作成中は非公開の`.partial`に保存し、第9.1節の全必須検査の通過後に`COMPLETE`を作成・公開する。作成側が再検査で失敗した場合はmarkerを残さない。公開後の検証は読取りで行い、不合格のsetを修正して成功に見せず、失敗の証跡を残す。複製・復元試験・保持判断の証跡は元setの外で管理し、同じsetに後からfileを足してhashを変えない。

### 8.3 旧形式1との互換性 { #legacy-format }

形式1の読取りを維持する。形式1に設定fileや追加検査結果がないことを隠して形式2相当の合格にせず、不足項目を明示する。未知の形式は処理を中止し、形式1として推測して開かない。

既存の形式1を復旧候補に使う場合は元setを変更せず、その対象アプリ版の必須schema、全添付・写真参照、設定の再準備、対応image・recovery kitを隔離環境で追加検査し、外部証跡へ記録する。写真機能導入前の版などは、その版の検査契約に基づき「該当なし」とできる。別保存の設定がない場合は無効なscheduleから再設定し、設定の継続性を確認できないことも記録する。

形式2への変換を行う場合は、隔離した復元元から新しいbackup IDで作成し、変換元のID・manifest hashを記録する。元setの上書き、`format_version`だけの書換え、旧版コードへ形式2を渡す運用は行わない。`verify --schema-contract`で追加検査し、`convert-legacy`で新しい形式2へ変換する。登録済み契約は`profile-photos-20260914`と`before-profile-photos-20260914`。契約のない古い版は、対応するソースから契約を追加・検証するまで追加検査を合格にしない。変換先の設定は既定の無効状態とし、設定の継続性が未確認であることを記録する。

## 9. 自動検査

以下は形式2と正式運用の合格条件である。形式1を基本検査だけで読み取った場合は「検査済み」にせず、不足項目を返す。

### 9.1 ローカル検査 { #local-verification }

| 検査 | 合格条件 |
| --- | --- |
| 形式・完了marker | 対応形式であり、backup IDがdirectory・manifest・markerで一致。作成時は以下の検査後にmarkerを作る |
| hash・一覧 | 全payloadのpath・size・hashがmanifestと実体で一致し、全対象fileのSHA-256が`SHA256SUMS`と一致 |
| SQLite integrity | `PRAGMA integrity_check`が`ok`のみを返す |
| 外部キー | main DBの`PRAGMA foreign_key_check`が0行 |
| schema | 主DBと施設文例DBの必須table・columnが対応アプリ版の検査契約に一致。空のSQLiteを有効なアプリDBとして受け付けない |
| 主要件数 | 全tableの件数がmanifestと一致。主要業務table・施設文例tableは前回との差が設定しきい値内。大幅減少は理由・承認の記録がない限り失敗 |
| 全添付参照 | お知らせ・職員ルーム・文書確認依頼が参照する全fileが存在し、記録sizeと実sizeが一致。不正なpathや添付一覧JSONは失敗 |
| 写真 | 現在の園児・家族、変更申請、履歴の写真IDに対応する画像が存在して読める。所有対象の関係を含めて検査する |
| 定期実行設定 | 第4.4節の設定fileとmanifest記録が揃い、許可した項目・型・値・timezoneである |
| 復元元の特定 | 対応Git SHA・image・Compose・schema検査契約・recovery kitを識別できる |
| orphan添付 | DB参照のないfileは警告として列挙し、自動削除しない |
| 秘密情報 | manifestや通常logへsecret値が出ていない |

`PRAGMA integrity_check`は外部キー違反を検出しないため、`PRAGMA foreign_key_check`を別に実行する。

写真の履歴は画像に記録された所有園児・所有家族を基準にし、家族の変更等によって過去の写真を誤って欠損扱いしない。従来の履歴JSONには当時の家族IDがないため、過去の保護者写真は所有家族の存在と画像の種類を検査し、現在の家族との一致は要求しない。この検査基準を結果に記録する。写真未登録や、必要なschemaが揃った利用開始前の0件DBは有効である。参照されない画像・添付は警告として残し、自動削除しない。

主要件数の既定しきい値は20%減。`BUSINESS_COUNT_TABLES`の台帳・記録・添付・写真・計画と施設文例を対象とし、期限切れsession等の通常整理は大幅減少判定に含めない。`--count-change-ref`で承認済み削減の記録IDを指定できる。

初回で前回setがない場合は、初回であること・件数・確認者の運用記録を基準として残す。以後の比較を常に初回扱いで省略しない。schema検査や基準値の取得ができない場合は未確認とし、検査済みの判定を出さない。

ローカルの必須項目に不合格・未確認があれば、新しいsetへ`COMPLETE`を作らず、前回の正常backupを削除せず、運用責任者へ通知する。orphanのように本書が警告と定めた項目は、件数と対応判断を記録する。

### 9.2 複製・復元試験の検査 { #replica-verification }

複製先ごとに保存先の識別子、元setのmanifest hash、全fileのhash、検査日時、暗号化とアクセス制御の確認結果を記録する。指定した保存先のすべてを確認してから必要な複製が揃ったと判定する。

複製に失敗しても検査済みの元setと前回正常copyを保持し、「検査済み・複製失敗」と通知する。元の`COMPLETE`を消したり、元setを未取得扱いに戻したりしない。復元試験の合格は第13・14節に従って別途記録する。

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

実機の保存先ごとに暗号化方式・鍵の所在・復号試験結果を運用台帳へ記録する。ZFS暗号化が無効の場合は同等の保存時暗号化を別途確認できるまで、適合を未確認とする。SSHによる転送時暗号化やファイル権限だけで、保存時暗号化の条件を満たしたと判定しない。鍵の値や内部接続先は公開の仕様書へ記録しない。

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

写真の過去版・全添付・失敗した`.partial`の増加も容量計測に含める。前回setがない場合は今回のDB・添付・設定の見積量を基準に空き容量を確認する。

ホスト側の監視は、worker自体の停止やjob未作成も検出できるようにする。通知先・確認担当・再実行結果を記録し、通知機構の試験は許可した運用担当者向けの宛先で行う。`backup_operations monitor`が検査済みsetの経過時間、直近の作成失敗、停止worker、必要な複製先の証跡、保存先容量、復元試験期限を検査する。`--notify-command-file`は異常時だけ結果JSONを通知コマンドの標準入力へ渡す。TrueNASのsnapshot監視、runtime容量・暗号化・鍵期限の監視と監視コマンドの定期起動はホスト側で設定する。

## 13. 復元方式

### 13.1 原則

- 最初から稼働datasetへrollbackしない。
- backup/snapshotを隔離datasetへcloneまたはrestoreし、検査後に切り替える。
- DB・全添付・設定を同じbackup IDから復元する。形式1の不足は第8.3節の追加検査と記録で補う。
- DB table単位の手作業復元や、新旧DBの直接mergeを標準手順にしない。
- schema変更を含む場合、DBとGit SHA / imageを対で戻す。
- 障害調査用に、壊れた現行datasetも変更前snapshotとして保全する。

### 13.2 復元手順

1. incident ID、障害時刻、最後の正常操作時刻を記録する。
2. 期待する復旧時点と想定データ損失を業務責任者が承認する。
3. 対象backupの形式、`COMPLETE`、hash、manifest、追加検査・複製の証跡を確認する。
4. `prepare-restore`で新しい隔離datasetへDB・全添付・設定を同じbackup IDから復元する。認証・待機配送を失効し、scheduleを無効にする。古いjobとheartbeatは導入しない。
5. manifest記載のGit SHA / imageと対応するrecovery kitを用意する。
6. 稼働系と別名の検証stackへmountする。Cloudflare Tunnelとbackup-workerを含めず、実メール・Push等の外向き通信を遮断する。具体的なproduction設定・HTTPS・通信制御は[運用試験仕様の隔離復元](pilot-deployment-spec-v2.md#restore-isolation)に従う。
7. 第9.1節の検査を実行し、形式1は第8.3節の不足も補う。検査前の復元copyを保持する。
8. アプリを起動し、health、管理者login、園児・家族、現在・申請・履歴の写真、全種類の添付、代表業務画面、保護者の閲覧分離を確認する。
9. 起動時の送信再試行等で試験用DBが変化し得るため、切替用datasetは検査済みの同じsetから改めて準備する。試験で更新されたDBをそのまま稼働系へ切り替えない。
10. 切替用にも`prepare-restore`を用い、全認証失効・待機配送整理の件数と`restore-receipt.json`を確認する。確認済みパスワードによる再ログインと、失効済みtokenの拒否を確かめる。
11. TrueNASで壊れた現行runtimeの保全snapshotを取る。
12. app・workerとその他の書込み処理を停止し、切替用runtimeへmountを切り替える。
13. 同じGit SHA / imageで起動し、件数・認証・権限と代表画面を再確認してからCloudflare Tunnelを再接続する。
14. 保存先・schedule・保持・通知の構成を確認し、バックアップを明示的に再開する。
15. 利用者へ復旧時点、失われた可能性のある期間、再入力対象を通知する。
16. 実RPO/RTO、判断者、実施者、使用set、再開結果を記録する。

`prepare-restore`は新規の隔離directoryだけを対象に、session・action token・職員復旧コード・保護者登録session/招待tokenを失効し、待機メール・Push・カレンダー通知jobを取消/抑止する。パスワード自体は維持して本人の再ログインを可能にする。復元準備の成功は画面での復元試験合格とは別である。secretの変更だけで全認証記録が失効すると仮定せず、DBの直接手編集や復元試験中の送信失敗で代用しない。

### 13.3 添付だけの復元

DB行が残り、対応fileだけが欠損している場合は、同じまたはそれ以前の正常backupからhash・sizeを確認して個別fileを復元できる。DB行を復活させる必要がある場合は個別復元を行わず、隔離環境でDB全体の復元または承認済みデータ修復を行う。

## 14. 復元試験

| 試験 | 頻度 | 内容 |
| --- | --- | --- |
| 標準復元 | 毎月 | 直近日次backupを隔離datasetへ復元し、全自動検査とsmoke test |
| update rollback | schema変更またはmajor update前 | 旧Git SHAと更新前DBを対で戻す |
| 災害復旧 | 3か月ごと | source TrueNASを使わずoff-site copyとrecovery kitから復元 |
| 写真・添付整合 | 毎月 | 写真の現在・申請・履歴参照と画像表示、全添付の存在・size・hash・画面からの参照を確認 |
| recovery key | 3か月ごと | 隔離環境で復号・unlockできることを確認 |

試験は実際のproduction datasetを直接rollbackせず、外部公開なしの隔離環境で行う。実データを使う復元試験環境もproduction相当のアクセス制御・暗号化・削除手順を適用する。

### 14.1 合格証跡

- backup IDと復元元
- 試験開始・終了時刻
- 実施者、確認者
- Git SHA / image digest
- 全検査結果
- 各段階の結果、形式1の追加検査、写真・全添付・設定の検査、複製元manifestのhash
- 代表画面の確認結果。個人情報を含むscreenshotは証跡に添付しない
- 実RPO/RTO
- 問題、是正期限、担当者
- 試験用clone/datasetの削除日時

### 14.2 追加実装の回帰検証 { #acceptance-tests }

形式2と追加検査は、少なくとも次を架空データで検証する。全体のテスト成功件数だけで代用しない。

- 存在しない文書添付、size不一致、不正なJSON・path、写真参照切れ・読めない画像を失敗として検出する。
- 主DB・施設文例DBの取り違え、必須table・column欠落、未特定のアプリ版を失敗にする。必要schemaを持つ0件DBは受け付ける。
- 現在・変更申請・履歴の写真を保持し、履歴の当時の対象関係と保護者の閲覧範囲を確認する。
- 定期設定の保存・既定値・不正値を検査し、復元直後の無効化と明示的な再開を確認する。古い待機job・heartbeatを再利用しない。
- 形式1を変更せず追加検査でき、形式2の正常setを検証できる。未知形式、payloadの未登録・欠落・改ざんを拒否する。
- 複製失敗・中断・再試行で前回正常copyと検査済み元setが残り、段階の結果と通知が一致する。
- 全失効後の旧session/tokenの拒否、本人の再ログイン、復旧後の保留キューからの意図しない再配送がないことを確認する。

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

## 17. 実装状況と受入条件

### 17.1 実装済みの範囲

- `scripts.backup_runtime create`: 形式2。主DB・施設文例DB・全storage・正規化した定期設定、manifest・SHA-256、検査完了後の公開
- `verify`: 形式1・2の読取り。payloadとmanifestの照合、DB整合、全添付、登録済みschema・写真、主要件数比較。形式1の不足は明示する
- `convert-legacy`: 登録済み契約による形式1の追加検査と新しい形式2への変換。元setと親manifest hashを保持する
- `prepare-restore`: 新しい隔離先へDB・添付・無効な設定を導入し、旧認証と待機配送を失効。元set・既存directoryを上書きしない
- `scripts.backup_operations`: 複製のcopy/hash検査、外部証跡の追記、復元試験の実測記録、未取得・失敗・容量・期限監視、通知コマンド連携
- `/settings/backups`: 4段階の表示、元の失敗job・予定枠に紐づく手動再実行。必要な複製先IDが未設定なら複製済みと表示しない
- TrueNASのworkerは引き続き`backup-ui-trial`。DB書込みlockは使うが、正式な停止・snapshot・複製を実行しない

### 17.2 実装と実機受入の区別

第14.2節のケースを`test_backup_v2.py`および既存テストで検証する。[確認手順](backup-verification-guide.md)の結果を対象版・環境とともに記録する。

- 保存先の暗号化と別障害系統であることはCLIで自動判定せず、運用担当者が確認した記録IDを複製証跡へ残す
- CLIの複製はmount済みの保存先へのcopyであり、ZFS replication・off-site接続・鍵配備はホスト側の設定を要する
- `monitor`は定期実行・通知先を勝手に設定しない。ホストでの起動と通知先での受信を受入時に確認する
- 自動世代削除とアプリ共通のファイル書込みlockは未実装。正式運用は停止方式とTrueNAS側の保持管理を用いる
- ローカルの実装・架空データ検証から、実機反映・運用試験の完了を推測しない

### 17.3 段階A開始前

- [ ] 写真を含む主DB、施設文例DB、storage全体、定期実行設定をruntime datasetへ永続化する
- [ ] runtime dataset全体の15分snapshotを設定する
- [ ] app停止中の手動application-consistent snapshot手順を実施する
- [ ] 別poolまたは別装置へ少なくとも1つ複製する
- [ ] 写真・全添付・設定を含む隔離datasetへの復元を1回成功させ、各段階の証跡を記録する

### 17.4 限定実データ試験前

- [ ] 本改訂の追加検査・復元処理を実装・検証し、未確認の必須項目がない
- [ ] TrueNAS snapshot clone、backup helper、複製、世代削除を日次jobとしてorchestrationする
- [ ] job失敗、replication遅延、容量、復元期限のalertを実装する
- [ ] runtime・各保存先の保存時暗号化と別pool/off-site複製を構成し、複製先の検査結果を確認する
- [ ] session/action token一括失効と送信待ちキュー整理を実装し、復元後の拒否・再ログイン・再配送防止を検証する
- [ ] 月次標準復元と四半期災害復旧の担当・日程を登録する
- [ ] recovery kitを別保管し、source TrueNASなしで復号試験する

構成の有無をコードから推測せず、対象版・環境・確認者・確認日・結果を記録する。読取り権限や証跡不足で確認できない項目は未確認のままとし、チェックを付けない。

## 18. 参考資料

- [SQLite Online Backup API](https://sqlite.org/backup.html)
- [Python sqlite3 Connection.backup](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup)
- [SQLite WAL](https://sqlite.org/wal.html)
- [SQLite PRAGMA integrity_check / foreign_key_check](https://sqlite.org/pragma.html#pragma_integrity_check)
- [TrueNAS Periodic Snapshot Tasks](https://www.truenas.com/docs/scale/26/dataprotection/periodicsnapshottasks/addingperiodicsnapshottasks/)
- [TrueNAS Replication Tasks](https://www.truenas.com/docs/scale/26/dataprotection/replication/)
- [TrueNAS Encrypted Replication](https://www.truenas.com/docs/scale/26/dataprotection/replication/advancedreplication/replicationwithencryption/)
