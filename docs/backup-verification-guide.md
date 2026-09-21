# バックアップの実装確認と復元試験

2026年9月14日に実装した形式2を確認する手順です。[バックアップ・復元仕様 文書版1.2](backup-restore-spec.md)の受入条件に従います。ローカルのテスト成功、実機への配備、暗号化・複製先の設定、実機での復元試験はそれぞれ記録します。

## 最初に確認すること

| 項目 | 確認内容 |
| --- | --- |
| 対象版 | 新しい実装を含む確定Git SHA、app/worker image ID、実際のCompose hash |
| バックアップ形式 | 新しい作成CLIは2。旧CLIは形式2を読めないため、作成・検査用imageも保管する |
| schema契約 | 現行開発版は職員セッション設定を含む`staff-sessions-20260920`。9月19日版は`spec-changes-20260919`、9月17日版は`spec-changes-20260917`。写真追加後は`profile-photos-20260914`、追加直前は`before-profile-photos-20260914`。復元元の版に合う契約を使う |
| 実行方式 | 画面のworkerは稼働中の試験用。正式な取得はapp・worker・その他の書込みを止めたsnapshot/cloneを使用 |
| 復元先 | 稼働runtimeと別の、未作成directory。公開経路・実メール・Pushから隔離 |
| 秘密値 | 通常のbackup setへ入れず、別保管の暗号化recovery kitを使用 |

## 1. ローカルで回帰テストする

リポジトリ直下で実行します。テストは架空データの一時DBを使います。既存runtimeへ復元する操作は含みません。

```powershell
$env:PYTHONUTF8 = '1'
& .\venv\Scripts\python.exe -m pytest -q test_backup_runtime.py test_backup_jobs.py test_backup_schedule.py test_backup_v2.py test_profile_photo_preflight.py -o cache_dir=tmp/backup-check-cache
```

確認する振る舞いは次のとおりです。

- 写真・性別・全添付・設定を保存し、現在・変更申請・履歴の写真を復元できる
- 文書確認依頼の添付欠損、size不一致、不正JSON/path、写真参照切れ、読めない画像が失敗になる
- 必須table/columnのないDBを拒否し、正しいschemaを持つ0件DBは受け付ける
- 旧形式1は不足を表示し、追加検査・形式2への変換でも元setを変更しない
- 業務データの20%超の減少は、承認記録IDを指定しない限り失敗になる
- 復元直後の設定は無効、古いjob・heartbeatは未導入、旧認証と待機配送は失効・取消される
- 旧session/tokenを拒否し、本人のパスワードで新しくログインできる
- 複製失敗でも元setと前回世代を残し、複製失敗の証跡を保存する

全体確認では次を使用します。`.local-dev`と`.pytest_cache`はローカル作業物のため収集対象から除外します。

```powershell
& .\venv\Scripts\python.exe -m pytest -q --ignore=gen_bunnrei --ignore=.local-dev --ignore=.pytest_cache -o cache_dir=tmp/backup-check-cache
& .\venv\Scripts\python.exe -m ruff check .
& .\venv\Scripts\python.exe -m mkdocs build --strict
git diff --check
```

## 2. 実機用の設定を準備する

新しいimageをappとworkerの両方へ適用する前に、確定SHA・image ID・Compose hashを更新します。未設定のGit SHA、ゼロ埋めhash、`latest`等の固定されていないimageでは形式2の取得が失敗します。

| 設定 | 用途 |
| --- | --- |
| `BACKUP_GIT_SHA` / `BACKUP_APP_IMAGE` / `BACKUP_COMPOSE_SHA256` | 実際の版と構成を特定 |
| `CLOUDFLARED_IMAGE` | 固定digestを指定 |
| `BACKUP_RECOVERY_KIT_REF` | 復旧に使うkitの運用記録ID。秘密値そのものを入力しない |
| `BACKUP_BASELINE_REF` | 形式2の初回の件数を確認した運用記録ID |
| `BACKUP_REPLICA_TARGETS` | 必要な複製先ID。例:`local,offsite`。空のままでは画面の「別系統保存」は確認済みにならない |

workerでは上記の値を`HOIKUICT_BACKUP_*`環境変数へ渡します。TrueNAS用Composeは対応済みです。既に有効なscheduleがある場合も、検証が終わるまで試験workerを再開しないでください。

初回以後は同じ保存先・環境・施設の前回setと自動比較します。初回確認IDを再度指定しても比較を省略しません。承認済みの大量削除等で減少する場合は、停止方式のCLIで`--count-change-ref <承認記録ID>`を指定し、根拠を残します。

## 3. 停止方式で形式2を作る

app・worker・その他の書込み処理を停止してruntime snapshotを取得します。書込み可能cloneから取得する場合は、そのcloneだけをmountした専用Composeを使います。停止とsnapshotの順序は[運用試験仕様](pilot-deployment-spec-v2.md)を確認してください。

以下の`<...>`を確認した値に置き換えます。`--quiesced`は停止またはcloneの事実を確認してから指定します。

```bash
docker compose run --rm --no-deps backup create \
  --output-root /backup \
  --git-sha <approved-full-sha> \
  --app-image sha256:<actual-app-image-id> \
  --compose-sha256 <actual-compose-sha256> \
  --cloudflared-image cloudflare/cloudflared@sha256:<approved-digest> \
  --recovery-kit-ref <approved-kit-record-id> \
  --actor-ref <operation-record-id> \
  --baseline-ref <initial-count-review-id> \
  --retention-class change \
  --quiesced

docker compose run --rm --no-deps backup verify /backup/<backup-id> --json
```

合格時は`format_version: 2`、`status: ok`、`stages.acquired/verified: passed`です。`replicated/restored: unconfirmed`は、このコマンドだけではその2段階を確認していないことを示します。

失敗時は終了コード1と`.partial/FAILED.json`を確認します。`COMPLETE`のないsetを復旧元へ選びません。前回の正常世代や失敗の証跡を削除してやり直さず、原因を解消して新しいIDで再実行します。

## 4. 隔離先へ復元する

次のCLIは新しい復元先だけを作り、元setや既存directoryを上書きしません。復元先の親directoryを専用領域として準備し、実行ユーザーの書込み権限を確認します。

```bash
docker compose run --rm --no-deps \
  -v /mnt/<pool>/restore-checks:/restore \
  backup prepare-restore /backup/<backup-id> \
  --destination /restore/<new-run-directory> \
  --incident-ref <restore-operation-id> \
  --isolated
```

出力先は次の構成です。

```text
<new-run-directory>/
├── runtime/
│   ├── data/hoikuict.db
│   ├── data/facility.sqlite
│   ├── data/backup-control/schedule.json
│   └── storage/
├── restore-receipt.json
└── RESTORE_READY
```

`restore-receipt.json`には元backup ID・manifest hash・認証失効/配送取消の件数を記録します。`RESTORE_READY`は復元先の準備完了であり、画面での復元試験合格ではありません。

復元appは[隔離復元の具体条件](pilot-deployment-spec-v2.md#restore-isolation)で起動します。production設定を維持し、SMTPをループバックへ向け、Push・kioskを無効にし、Cloudflare Tunnelとbackup-workerを含めず外向き通信を遮断します。

- [ ] 管理用HTTPSで管理者がパスワードから新しくログインできる
- [ ] 園児の性別、現在の園児・保護者写真、変更申請・履歴の写真を表示できる
- [ ] お知らせ・職員ルーム・文書確認依頼の添付を開ける
- [ ] 他家庭・未許可園児の写真/添付を直接URLで取得できない
- [ ] 古いsession・有効化/復旧/招待コードが拒否される
- [ ] 復元前からの待機メール・Pushが配送されない
- [ ] 定期実行は無効、古いjob・heartbeatは導入されていない
- [ ] 所要時間と、失われる可能性がある期間を測定した

切替が必要になった場合は、同じ検査済みsetから**別の新しいdirectoryへ再度`prepare-restore`**を実行します。試験中にログイン等で変化したDBをそのまま稼働系へ切り替えません。公開再開後に設定を確認してからバックアップを明示的に再開します。

## 5. 旧形式1を使う場合

通常の`verify`は不足項目を`legacy_gaps`へ返します。対象アプリ版に対応する登録済みschema契約を指定して追加検査します。

```bash
python -m scripts.backup_runtime verify /backup/<old-id> \
  --schema-contract profile-photos-20260914 --json

python -m scripts.backup_runtime convert-legacy /backup/<old-id> \
  --output-root /converted-backups \
  --schema-contract profile-photos-20260914 \
  --recovery-kit-ref <approved-kit-record-id> \
  --actor-ref <conversion-operation-id> \
  --baseline-ref <initial-count-review-id>
```

写真導入直前の版には`before-profile-photos-20260914`を使用します。契約を変更して不足schemaをごまかさず、対象版の構造と一致することを確認します。旧setのGit SHA/image等が未特定なら変換を中止して復旧元の版を調査します。定期実行設定は旧setにないため、既定の無効状態から再設定します。

## 6. 別系統へ複製し、証跡を残す

以下はPythonと新しい検査コードが利用でき、両保存先がmountされた運用ホストで実行します。保存先の暗号化・鍵管理・別障害系統であることを先に確認し、その記録IDを指定します。CLIはこれらの物理構成を自動検出しません。

```bash
python -m scripts.backup_operations replicate /backup/<backup-id> \
  --destination-root /mounted-local-backup/sets \
  --destination-ref local \
  --encryption-ref <encryption-audit-id> \
  --independence-ref <storage-separation-audit-id> \
  --evidence-root /runtime/data/backup-control/evidence
```

off-siteも別の保存先へ同じ手順で複製し、`--destination-ref offsite`とします。証跡先は稼働appが読む`backup-control/evidence`に対応させ、backup本体の内側へ置きません。必要な全保存先の証跡が揃うと、同じbackup IDの画面が「別系統保存: 確認済み」になります。複製先の既存setが異なる場合は上書きせず失敗します。

画面での復元試験後、以下のJSONを記録用ファイルに保存します。未確認項目を`true`にせず、実測値と運用記録IDへ置き換えてください。

```json
{
  "test_ref": "restore-test-record-id",
  "actor_ref": "operator-record-id",
  "rpo_seconds": 0,
  "rto_seconds": 0,
  "checks": {
    "login": false,
    "photos": false,
    "attachments": false,
    "family_isolation": false,
    "no_external_delivery": false,
    "schedule_disabled": false,
    "old_tokens_rejected": false,
    "pending_queues_cancelled": false,
    "fresh_login": false
  }
}
```

```bash
python -m scripts.backup_operations record-restore-test /backup/<backup-id> \
  --report /operations/<completed-report>.json \
  --evidence-root /runtime/data/backup-control/evidence
```

全項目が`true`の場合だけ復元試験の合格証跡になります。個人情報を含む画面画像や秘密値を報告JSONに入れません。

## 7. 監視・通知と実機受入の残り

```bash
python -m scripts.backup_operations monitor \
  --output-root /backup \
  --evidence-root /runtime/data/backup-control/evidence \
  --facility-ref <facility-reference> \
  --required-destinations local,offsite
```

異常時は終了コード1と`problems`を返します。試験workerも監視するときだけ`--control-dir /runtime/data/backup-control`を加えます。ホストの定期実行で起動し、必要なら`--notify-command-file`で通知コマンドの引数配列JSONを指定します。コマンドはshellを経由せず、結果JSONを標準入力で受け取ります。通知コマンドの秘密値は別管理し、承認したテスト宛先で受信を確認します。

実機で確認する残りは、停止方式の日次処理、15分snapshot、保持設定、別pool/off-siteの接続・暗号化・復号、ホスト監視の定期起動と通知先での受信です。自動世代削除は今回のCLIに含まれません。[保持期間と受入条件](backup-restore-spec.md)に沿ってTrueNAS側で設定します。
