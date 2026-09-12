# TrueNAS・Dockge・Cloudflare 実運用試験構成仕様

> 状態: 計画（実運用試験前の承認用）  
> 基準日: 2026年8月31日  
> 対象: TrueNAS SCALE上のDocker、Dockge、Cloudflare Tunnel / Access  
> 重要: この文書の受け入れ条件を満たすまでは、実在する園児・保護者・職員の情報を投入しない。

## 1. 目的

open-hoikuictをTrueNAS上で限定公開し、日常業務の流れ、認証、権限、データ永続化、バックアップ、障害時の代替運用を小規模に検証する。

この試験は「完成済み本番システムの導入」ではない。現在のREADMEおよび[リリース前チェックリスト](release-checklist.md)に残る条件を解消し、施設が本番移行を判断するための段階的なパイロットである。

## 2. 試験段階

| 段階 | データ | 利用者 | 公開制御 | 次段階へ進む条件 |
| --- | --- | --- | --- | --- |
| A: 技術試験 | 架空データのみ | 管理者と試験職員2〜5名 | Cloudflare Accessの個別許可 + アプリ認証 | 起動、認証、権限、更新、停止、復元試験に合格 |
| B: 業務試験 | 架空データのみ | 1クラス相当の職員 | 同上 | 2週間以上の業務シナリオと紙運用への切替に合格 |
| C: 限定実データ試験 | 必要最小限 | 承認済み職員・保護者 | Accessまたは承認済みの公開方針 + アプリ認証 | 本文の全ゲート、個人情報取扱承認、復旧試験に合格 |
| D: 本番 | 実データ | 全対象者 | 別途承認 | 本仕様の対象外 |

段階A・Bで実在情報を入力してはならない。段階Cは、[ベータ開始時の本番データ移行仕様](beta-production-data-migration-spec.md)が実装・リハーサル済みであることを前提とする。

## 3. ブランチ・リリース方針

ブランチは分ける。ただし、環境ごとに機能コードを複製しない。

- `main`: 共通コードの正本。検証済み変更だけを取り込む。
- `codex/pilot-truenas-dockge`: 導入文書、Compose、監視・バックアップ補助など試験固有の短期作業ブランチ。
- TrueNASへは作業ツリーを直接コピーせず、承認したコミットを指すタグまたはコミットSHAを展開する。
- デプロイ記録に、Git SHA、イメージIDまたはdigest、Composeのハッシュ、実施者、実施日時を残す。
- DBや`.env`、Tunnel token、秘密鍵をブランチ間で管理しない。これらはGit外のTrueNAS datasetへ置く。

現在の作業ツリーには未コミットの機能変更があるため、それらを整理してコミットするまではブランチ切替を行わない。

## 4. 論理構成

```text
利用端末
  -> Cloudflare (TLS / Access policy / edge protection)
    -> Cloudflare Tunnel (outbound-only connector)
      -> cloudflared container
        -> http://app:8000 (専用Docker network内のみ)
          -> open-hoikuict container
            -> /data/hoikuict.db + /app/storage (TrueNAS runtime dataset)
```

### 4.1 境界

- ルーターで80、443、8000番をTrueNASへポート転送しない。
- `app`サービスにComposeの`ports`を設定しない。`expose: 8000`だけを使用する。
- `cloudflared`と`app`だけを専用Docker networkへ参加させる。
- Dockge管理画面とTrueNAS管理画面をCloudflare Tunnelの同じ公開hostnameへ載せない。
- Cloudflare Accessは追加の入口制御であり、open-hoikuict自身の職員・保護者認証を置き換えない。
- CloudflareからTunnelまではHTTPS、Tunnelから`app`までは外部から到達できない専用Docker network上のHTTPとする。

Cloudflare Tunnelはorigin側からCloudflareへ外向き接続を確立するため、originに公開IPや受信ポートを設けない構成にできる。Accessを使用する場合は、公開hostnameのTunnel routeを作る前にAccess applicationと許可policyを作成し、意図せず無認証公開される時間を作らない。

## 5. TrueNASストレージ仕様

`<pool>`は実環境のpool名に置き換える。

| dataset / path例 | 内容 | SMB共有 | snapshot |
| --- | --- | --- | --- |
| `/mnt/<pool>/apps/dockge/stacks/open-hoikuict-pilot` | `compose.yaml`、Git checkout | 原則しない | 更新前 |
| `/mnt/<pool>/apps/open-hoikuict-pilot/runtime` | SQLite DB、施設文例DB、添付、preview | 禁止 | 15分 + 日次 + 更新前 |
| `/mnt/<pool>/apps/open-hoikuict-pilot/secrets` | `.env`、Tunnel token、blocklist | 禁止 | 暗号化・限定保管。通常snapshotの扱いを別途承認 |
| `/mnt/<pool>/backup/open-hoikuict-pilot` | 検証済みDB backup | 禁止 | 別poolまたは別装置へ複製 |

- アプリデータはDocker内部の匿名領域だけに置かず、専用runtime datasetへbind mountする。
- runtime dataset内の`data`を`/data`、`storage`を`/app/storage`へmountする。後者にはお知らせ・職員ルーム添付が入る。
- DB本体、`-wal`、`-shm`は常に同じdatasetへ置く。
- datasetはアプリ実行UID/GIDだけが書き込めるようにし、全利用者への書込権限を与えない。
- snapshotはバックアップの一部であり、同一poolだけのsnapshotを唯一のバックアップにしない。RPO/RTO、保持、検査、復元は[バックアップ・復元仕様](backup-restore-spec.md)に従う。
- 少なくとも日次で別poolまたは別装置へ複製し、月1回以上、隔離した復元先で復元試験を行う。
- 稼働中SQLiteの単純な`.db`ファイルコピーは禁止する。SQLite backup APIを使うか、コンテナを停止してDB関連ファイルを一貫した時点で保全する。

段階Aの開始前は、短時間停止してdataset snapshotを取得する方式でよい。段階Cの前に、停止不要のSQLite backup APIを使う補助コマンドと世代管理を実装する。

## 6. コンテナ仕様

### 6.1 アプリ

| 項目 | 値 |
| --- | --- |
| build | 承認済みGit SHAの`Dockerfile` |
| 実行ユーザー | image内の非root `appuser` |
| restart | `unless-stopped` |
| listen | container内 `0.0.0.0:8000` |
| host port | なし |
| healthcheck | `GET http://127.0.0.1:8000/healthz` |
| 永続化 | runtime datasetの`data`を`/data`、`storage`を`/app/storage`へbind mount |
| DB | `sqlite:////data/hoikuict.db` |

`/healthz`はプロセスの軽量な稼働確認であり、DB読書きや認証を検査しない。別途、ログインとDBを使う外形監視・日次確認を設ける。

### 6.2 cloudflared

| 項目 | 値 |
| --- | --- |
| image | Cloudflare公式image。段階C前にdigest固定 |
| 管理方式 | remotely-managed tunnel |
| token | Git外の読取専用file。Compose本文やDockge画面へ直書きしない |
| origin service | `http://app:8000` |
| host port | なし |
| network | appと同じ専用network |

### 6.3 Docker network

専用CIDRを1つ決め、既存Docker network、LAN、VPNと重複しないことを事前確認する。例は`172.30.50.0/24`とするが、実値は環境調査後に決める。

`FORWARDED_ALLOW_IPS`にはこの専用CIDRだけを設定し、`*`は設定しない。`app`のhost portを閉じることと組み合わせ、専用network内の`cloudflared`だけを信頼する。

## 7. production必須設定

値は`.env`等のGit管理外ファイルに保存する。秘密値を文書、Issue、チャット、スクリーンショットへ記録しない。

| 設定 | 試験値・条件 |
| --- | --- |
| `HOIKUICT_ENV` | `production` |
| `HOIKUICT_ENABLE_MOCK_AUTH` | `0` |
| `HOIKUICT_STAFF_AUTH_MODE` | `local_password` |
| `HOIKUICT_PARENT_AUTH_MODE` | `local_password` |
| `HOIKUICT_SECRET_KEY` | 32文字以上の固定ランダム値 |
| `HOIKUICT_LOGIN_THROTTLE_HMAC_KEY` | 32バイト以上の別の固定ランダム値 |
| `HOIKUICT_COOKIE_SECURE` | `1` |
| `HOIKUICT_CSRF_ENFORCE` | `1` |
| `HOIKUICT_ALLOWED_ORIGINS` | `https://<pilot-hostname>`のみ |
| `FORWARDED_ALLOW_IPS` | 専用Docker network CIDR。`*`禁止 |
| `HOIKUICT_KIOSK_ACCESS_MODE` | 初期値`disabled`。利用時だけ`token` |
| `HOIKUICT_KIOSK_TOKEN` | kiosk=`token`時に別の固定ランダム値 |
| `HOIKUICT_PUSH_TRANSPORT` | `disabled` |
| `HOIKUICT_PARENT_MAIL_TRANSPORT` | `smtp` |
| `HOIKUICT_PARENT_REGISTRATION_BASE_URL` | `https://<pilot-hostname>` |
| `HOIKUICT_SMTP_HOST` / `PORT` / `STARTTLS` | 承認済みSMTP。`STARTTLS=1` |
| `HOIKUICT_SMTP_USERNAME` / `PASSWORD` | SMTP側が要求する場合に設定 |
| `HOIKUICT_PARENT_MAIL_FROM` | 承認済み送信元 |
| `HOIKUICT_PASSWORD_BLOCKLIST_PATH` | container内の読取専用blocklist file |

秘密鍵類は用途ごとに別値とし、アプリ再起動のたびに生成し直さない。変更すると既存sessionやtokenへ影響するため、ローテーション手順と実施記録を残す。

## 8. Cloudflare仕様

### 8.1 hostname

- 試験専用subdomainを使う。例: `pilot-hoiku.example.jp`。
- 本番hostnameと共有しない。
- Full DNS setupの場合、Tunnel route作成時のDNS recordをCloudflareで管理する。

### 8.2 Access

- 段階A・BはAccess self-hosted public applicationを作成する。
- policyはdeny-by-defaultとし、許可対象を試験参加者の個別メールアドレスまたは承認済みIdP groupへ限定する。
- MFAと短いsession durationを有効にする。
- Tunnel側の`Protect with Access`を有効にし、Access tokenをTunnelで検証する。
- Access通過後も、アプリの個別アカウントで再認証する。

段階Cで保護者が参加する場合、全対象者がAccessを利用できるかを先に確認する。Accessを外す判断は、WAF/rate limit、アプリ認証、監視、インシデント対応を含む別の公開承認とする。

### 8.3 edge設定

- TLSはCloudflareの現行推奨設定を使用する。
- 管理・認証URLへのrate limitingやbot対策は、正常な保護者・職員操作を妨げない条件で検証する。
- Cache RulesでHTML、認証後画面、個人情報を含むresponseをcacheしない。
- Cloudflare logへquery stringや個人情報を過剰に残さない。

## 9. 監視とログ

| 対象 | 確認 | 初期頻度 |
| --- | --- | --- |
| app container | health、restart count、例外 | 毎日 + alert |
| cloudflared | connector接続、再接続、認証失敗 | 毎日 + alert |
| 公開URL | Access、アプリlogin、主要画面 | 毎日 |
| storage | dataset使用率、pool状態 | 毎日 + 閾値alert |
| backup | 最終成功日時、世代数、別系統複製 | 毎日 |
| security | login失敗、権限変更、アカウント停止 | 毎日 |

通常ログへ氏名、住所、健康情報、password、session、Tunnel tokenを出さない。ログ閲覧者と保存期間を決める。

## 10. 更新・ロールバック

1. 承認したGit SHAからimageをbuildし、image IDを記録する。
2. 検証環境で自動テストとスモークテストを行う。
3. app停止またはSQLite backup APIで整合したbackupを作り、TrueNAS snapshotを取得する。
4. Dockgeで更新し、health、login、主要画面、DB件数を確認する。
5. 失敗時はappを停止し、コードだけでなく、そのコードと対になるDB snapshotへ戻す。

スキーマ変更後に古いimageだけへ戻してはならない。現時点ではAlembicによる正式なmulti-DB migrationがないため、更新前backupと復元リハーサルを必須とする。

## 11. 受け入れ条件

### 段階A開始

- [ ] 作業ブランチの変更がレビューされ、デプロイ対象Git SHAが固定されている
- [ ] 架空データだけを使用することを参加者へ説明した
- [ ] appのhost portが公開されていない
- [ ] Access policyが個別許可・deny-by-defaultになっている
- [ ] production security validationを通過している
- [ ] Dockge、TrueNAS管理画面がインターネット公開されていない
- [ ] 専用dataset、snapshot、別系統backup先が用意されている
- [ ] 紙・電話等の代替運用と連絡責任者が決まっている

### 段階C開始

- [ ] [リリース前チェックリスト](release-checklist.md)の実運用該当項目がすべて合格している
- [ ] 本番データ移行を新規DBでリハーサルし、整合性検査に合格している
- [ ] 保護者が他家庭・未紐付け園児を閲覧できないことを直接URLを含め確認した
- [ ] 管理者、編集者、閲覧専用、保護者の権限差を確認した
- [ ] SMTP、招待、password resetを実機確認した
- [ ] backupから隔離datasetへの復元を成功させ、所要時間を記録した
- [ ] 更新失敗時にGit SHAとDBを対で戻す試験に成功した
- [ ] 個人情報の利用目的、保存期間、削除、漏えい時連絡を承認した
- [ ] サポート時間、停止判断者、Cloudflare/TrueNAS障害時の責任分界を決めた

## 12. 現時点の導入阻害事項

既存の`deploy/dockge/compose.yaml`は開発の土台であり、次の理由からそのまま段階Aへ使わない。

1. `ports`で8000番をhostへ公開している。
2. `cloudflared`が同一stackに定義されていない。
3. production必須のstaff/parent auth、SMTP、password blocklist設定が不足している。
4. named volumeの実体とTrueNAS snapshot/replication対象の対応が運用上明示されず、添付保存先`/app/storage`も永続化されていない。
5. imageのcommit/digest固定、backup補助、restore検証、監視が未整備である。
6. 本番データ移行仕様が計画状態であり、実データ投入の受け入れ条件をまだ満たしていない。

これらは[実運用試験手順書](truenas-dockge-cloudflare-pilot-runbook.md)に従って段階的に解消する。

## 13. 参考資料

- [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)
- [Cloudflare: Publish a self-hosted application](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)
- [Cloudflare Tunnel run parameters](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/)
- [TrueNAS: Adding and Managing Datasets](https://www.truenas.com/docs/scale/datasets/datasets/)
- [TrueNAS: Adding Periodic Snapshot Tasks](https://www.truenas.com/docs/scale/dataprotection/periodicsnapshottasks/addingperiodicsnapshottasks/)
- [Dockge README](https://github.com/louislam/dockge/blob/master/README.md)
