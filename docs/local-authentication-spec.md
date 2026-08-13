# オンプレ・閉域向け自前認証仕様

- 文書ステータス: 計画
- 初版作成日: 2026-08-13
- 認証方式: Argon2idによるローカルパスワード認証
- 初期実装範囲: 職員・保護者認証、ローカルセッション、資格情報ライフサイクル、管理者MFA
- 関連文書: [セキュリティ最低ライン](security.md)、[職員ポータル仕様](staff-personal-portal-spec.md)、[連携契約](integration-contract.md)、[運用責任](operations.md)

## 1. 目的

現在の職員・保護者ログインは、開発・デモ用の利用者選択Cookieを使うモック認証である。本仕様では、インターネット上のIdentity ProviderやSaaSへ依存せず、オンプレミスまたは閉域ネットワーク内で完結する本番認証を導入する。

open-hoikuict自身が次を担当する。

- パスワード資格情報の安全な保存と検証
- 初期設定、変更、再設定、無効化
- 多要素認証
- ローカルアプリケーションセッション
- ログイン試行制限
- 職員・保護者の有効状態と認可
- 認証・認可の監査記録

パスワードハッシュにはbcryptではなくArgon2idを採用する。bcryptは既存hashの移行互換以外では新規使用しない。

## 2. 設計原則

### 2.1 オフライン完結

- 通常のログイン、ログアウト、MFA、初期設定、再設定は外部SaaSへ通信しない。
- DNS、インターネット、外部メール配信が停止していても管理者手順で資格情報を復旧できる。
- SMTP通知は任意拡張とし、認証の必須依存にしない。
- CDN上のJavaScript、外部CAPTCHA、外部漏えいパスワード照会APIをログイン時に呼ばない。

### 2.2 認証と認可の分離

パスワードとMFAは本人確認だけを担当する。園内権限は既存のローカルDBを正とする。

- 職員ロール: `admin` / `can_edit` / `view_only`
- 業務別権限
- 担当クラス
- 保護者と家庭・園児の紐付け
- アカウントの有効・無効状態

ログイン識別子やパスワードの変更によって、ロールや園児アクセス範囲を変更しない。

### 2.3 職員と保護者の分離

職員と保護者は同じハッシュ実装を利用しても、次を分ける。

| 項目 | 職員 | 保護者 |
| --- | --- | --- |
| ログイン入口 | `/staff/login` | `/parent-portal/login` |
| ローカル台帳 | `User` | `ParentAccount` |
| 資格情報 | staff principal | parent principal |
| session Cookie | 職員専用 | 保護者専用 |
| rate limit bucket | 職員専用 | 保護者専用 |
| MFA方針 | 管理者必須 | 初期実装では任意・後続で必須化を検討 |

同じログイン識別子が両方に存在しても、入口とprincipal種別が違うため相互ログインできない。

### 2.4 登降園キオスクの独立

`/guardian/**` の登降園キオスクは、職員・保護者の個人認証とは別の端末アクセス境界として維持する。

- 登園・降園操作のたびに職員または保護者のloginを要求しない。
- `PasswordCredential`、職員session、保護者sessionをキオスク利用条件にしない。
- キオスクrouteへ `LocalPasswordStaffAuthBackend` / `LocalPasswordParentAuthBackend` の認証必須dependencyを追加しない。
- キオスクは既存の `require_kiosk_access` だけで端末アクセスを判定する。
- キオスク端末Cookieを職員・保護者認証として受け入れない。
- 職員・保護者session Cookieをキオスク端末有効化の代わりに使用しない。
- 職員・保護者のlogin、logout、password変更、session失効によってキオスク端末Cookieを発行・削除しない。

ここでいう「個人認証なし」は、インターネット等へ完全無保護で公開する意味ではない。本番では施設が事前に有効化した専用端末、またはキオスクを無効化した構成だけを許可する。

| `HOIKUICT_KIOSK_ACCESS_MODE` | production | 用途 |
| --- | --- | --- |
| `token` | 許可 | `/guardian/activate` で端末を一度有効化し、以後は利用者loginなしで打刻する |
| `disabled` | 許可 | キオスクrouteを404として利用不可にする |
| `open` | 禁止 | 開発・隔離検証環境専用 |

`token` modeではactivation tokenをPOST bodyで受け取り、署名済みHttpOnly Cookieを `Path=/guardian` で発行する。秘密値をURLへ入れない。activation tokenのrotationで既存端末Cookieを無効化できることを維持する。

キオスクのPOSTも既存CSRF保護対象とする。端末有効化済みであってもCSRF検証を省略しない。リバースプロキシやネットワークでも、到達元を施設端末・施設ネットワーク等の必要最小限へ制限する。

## 3. 対象範囲

### 3.1 初期実装に含む

- 職員・保護者それぞれのログインフォームとArgon2id検証
- 職員・保護者で分離したDB管理のopaque session
- 職員・保護者の初期設定・パスワード変更・管理者発行再設定コード
- 初期管理者作成CLI
- ログイン試行制限とアカウント列挙対策
- 管理者向けTOTP MFAと回復コード
- 資格情報・session・認証イベントの監査
- production起動時の必須設定検証
- 開発・テスト用モック認証との切替
- 既存の職員ロール・業務権限・担当クラスのリクエスト時再評価
- `ParentAccount.status` と `ParentChildLink` に基づく保護者アクセス境界の再評価
- 保護者logout時の当該ブラウザpush購読無効化
- 職員・保護者認証から独立した登降園キオスク端末アクセスの維持

### 3.2 後続フェーズ

- 施設内SMTPによる通知
- 保護者MFAの必須化
- WebAuthn / passkey
- 複数施設を横断するアカウント
- LDAP / Active Directory連携
- 既存bcrypt hashが存在する場合のログイン時Argon2id移行

### 3.3 対象外

- 平文または復号可能なパスワード保存
- SHA-256等の高速hash単体によるパスワード保存
- 管理者が利用者のパスワードを設定・閲覧する機能
- 秘密の質問
- 外部OAuth/OIDC/SAMLを初期実装の必須経路にすること
- 外部CAPTCHAへの依存
- 定期的な強制パスワード変更
- 大文字・小文字・数字・記号を機械的に強制する複雑性規則

## 4. パスワードハッシュ

### 4.1 アルゴリズム

Python実装には `argon2-cffi` の高水準 `PasswordHasher` を使い、低水準APIや独自Argon2実装を使用しない。

初期パラメータは次とする。

| parameter | value |
| --- | --- |
| variant | Argon2id |
| `memory_cost` | 65,536 KiB |
| `time_cost` | 3 |
| `parallelism` | 1 |
| `salt_len` | 16 bytes |
| `hash_len` | 32 bytes |

Argon2 encoded stringにはvariant、version、各cost、salt、hashが含まれる。saltはライブラリにCSPRNGで毎回生成させ、アプリから固定値を渡さない。

この値は基準であり、導入対象ハードウェア上でbenchmarkする。通常ログイン1回の検証目標は概ね250〜500msとし、想定同時ログイン数でメモリ枯渇しないことを確認する。性能調整で下げる場合も、OWASPのArgon2id最低例である19 MiB、2 iterations、parallelism 1を下回らない。下回る構成は本仕様の受入対象外とする。

参考:

- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [argon2-cffi API Reference](https://argon2-cffi.readthedocs.io/en/stable/api.html)
- [RFC 9106](https://www.rfc-editor.org/rfc/rfc9106.html)

### 4.2 hash更新

ログイン成功後に `check_needs_rehash()` を実行し、現在の承認済みパラメータと異なるhashは同一トランザクションで再hashする。平文パスワードをログイン処理外へ渡さず、ログ・監査・例外へ残さない。

パラメータ変更時は、変更前後の値、対象ハードウェアbenchmark、同時実行時のCPU・メモリ、適用日、承認者を記録する。

### 4.3 pepper

初期実装ではpepperを必須にしない。オンプレ単一ホストでDBとアプリsecretが同時に取得される構成では効果が限定的で、pepper喪失時に全利用者の再設定が必要になるためである。

将来pepperを導入する場合は、DBと別のsecret保管先、version、ローテーション、喪失時手順を先に仕様化する。環境変数をhash文字列へ単純連結する独自方式は採用しない。

## 5. パスワードポリシー

### 5.1 入力規則

- 最小15文字
- 最大128文字かつUTF-8で1,024 bytes以下
- 空白とUnicodeを許可
- pasteとpassword managerを妨げない
- 大文字、小文字、数字、記号の組合せを必須にしない
- 前後空白の自動削除、大小文字変換をしない
- Unicodeはhash前にNFCへ正規化する
- NUL文字と制御文字は拒否する

長さは正規化後のUnicode code point数で評価し、Argon2へUTF-8で渡す。確認欄との比較も同じ正規化後の値で行う。

### 5.2 blocklist

作成・変更・再設定時に、次を含むローカルblocklistと照合する。

- 頻出パスワード
- 公開済み漏えいパスワードのオフライン配布データ
- 園名、法人名、製品名
- ログイン識別子、メール、表示名を単純に含む値
- `password`、`hoiku`、年度・季節等の予測しやすい組合せ

blocklistはネットワークを使わず更新できる、checksum確認済みファイルとして配布する。照合のために入力パスワードを外部へ送信しない。拒否時は理由を示すが、blocklistの内容は公開しない。

### 5.3 変更頻度

漏えい、不正利用疑い、初期設定、管理者による失効等の理由がない限り、日数だけを理由に定期変更を強制しない。

参考: [NIST SP 800-63B Passwords](https://pages.nist.gov/800-63-4/sp800-63b/passwords/)

## 6. データモデル

### 6.1 `PasswordCredential`

資格情報を `User` / `ParentAccount` から分離する。

| field | type | required | note |
| --- | --- | --- | --- |
| `id` | UUID | yes | 内部ID |
| `principal_type` | string | yes | `staff` / `parent` |
| `staff_user_id` | UUID FK nullable | conditional | staff時のみ |
| `parent_account_id` | int FK nullable | conditional | parent時のみ |
| `login_id` | string | yes | 利用者表示用 |
| `login_id_normalized` | string | yes | principal種別内で一意 |
| `password_hash` | string nullable | conditional | Argon2 PHC encoded string |
| `hash_scheme` | string | yes | 初期値 `argon2id` |
| `must_change_password` | bool | yes | 既定false |
| `password_changed_at` | datetime nullable | no | UTC |
| `credential_version` | int | yes | 変更・resetで加算 |
| `disabled_at` | datetime nullable | no | 資格情報単位の無効化 |
| `disabled_reason` | string nullable | no | 秘密を含めない |
| `created_at` | datetime | yes | UTC |
| `updated_at` | datetime | yes | UTC |

制約:

- principal種別に応じ、2つのFKのうち正しい側だけが非nullである。
- 1ローカル利用者につき有効なPasswordCredentialは1件である。
- `(principal_type, login_id_normalized)` は一意である。
- `login_id_normalized` はNFKC後にcasefoldし、前後空白を除去する。
- `password_hash` がnullの資格情報は、初期設定完了までログインできない。
- 既存 `ParentAccount.password_hash` は新規利用せず、後続migrationで専用テーブルへ移す。

### 6.2 `CredentialActionToken`

初期設定、パスワード再設定、MFA復旧等の単回使用コードを管理する。

| field | type | required | note |
| --- | --- | --- | --- |
| `token_hash` | string PK | yes | 生tokenのSHA-256 hash |
| `credential_id` | UUID FK | yes | 対象資格情報 |
| `action` | string | yes | `activate` / `reset_password` / `recover_mfa` |
| `created_by_user_id` | UUID nullable | no | 初期CLIはnull可 |
| `created_at` | datetime | yes | UTC |
| `expires_at` | datetime | yes | UTC |
| `consumed_at` | datetime nullable | no | 単回使用 |
| `revoked_at` | datetime nullable | no | 再発行時等 |

生tokenは256 bit以上のCSPRNGで生成し、URL-safe表現または入力しやすい分割コードとして一度だけ表示する。DBにはhashだけを保存する。

- 初期設定コード: 24時間以内
- 通常再設定コード: 30分以内
- 緊急オフライン再設定: 最大4時間、理由必須

再発行時は同一actionの未使用tokenをすべて失効する。tokenをURL queryへ入れず、利用者がフォームへ入力する方式を標準にする。

### 6.3 `AuthSession`

ブラウザへ256 bit以上のopaque tokenを渡し、DBにはSHA-256 hashだけを保存する。

| field | type | required | note |
| --- | --- | --- | --- |
| `token_hash` | string PK | yes | 生tokenは保存しない |
| `principal_type` | string | yes | `staff` / `parent` |
| `credential_id` | UUID FK | yes | 認証した資格情報 |
| `staff_user_id` | UUID nullable | conditional | staff時 |
| `parent_account_id` | int nullable | conditional | parent時 |
| `credential_version` | int | yes | 作成時snapshot |
| `mfa_satisfied_at` | datetime nullable | no | MFA成功時 |
| `created_at` | datetime | yes | UTC |
| `last_seen_at` | datetime | yes | 更新頻度を抑える |
| `idle_expires_at` | datetime | yes | 職員既定30分 |
| `absolute_expires_at` | datetime | yes | 職員既定12時間 |
| `revoked_at` | datetime nullable | no | 失効日時 |
| `revoke_reason` | string nullable | no | logout、password_changed等 |

session解決時は、Credentialとローカル利用者の有効状態、credential version、期限を毎回確認する。ロール・権限は毎回 `User` から構成し、Cookieやsession行のsnapshotを認可の正本にしない。

### 6.4 `LoginThrottle`

総当たり試行を、存在するアカウントだけに依存せず制限する。

| field | type | required | note |
| --- | --- | --- | --- |
| `bucket_hash` | string PK | yes | login ID・接続元をHMAC化 |
| `bucket_type` | string | yes | `account` / `network` |
| `failure_count` | int | yes | 期間内失敗数 |
| `window_started_at` | datetime | yes | UTC |
| `blocked_until` | datetime nullable | no | 一時遅延 |
| `updated_at` | datetime | yes | UTC |

HMAC keyはDB外のsecretとし、login IDやIPを平文で保存しない。アカウントが存在しない場合も同じdummy Argon2検証とthrottle処理を行う。

### 6.5 `AuthenticationEvent`

login成功・失敗、logout、session失効、資格情報作成・無効化、activation/reset発行、password設定・変更、MFA登録・失敗・復旧、throttle適用を監査する。

日時、結果、理由コード、principal種別、ローカル利用者ID、資格情報ID、request IDを含める。パスワード、hash全文、action token、session token、TOTP secret、回復コードを含めない。

## 7. TOTP MFA

### 7.1 対象

- productionの `admin` はMFA登録済みでなければ通常業務へ進めない。
- `can_edit` / `view_only` は施設設定で必須化できる設計にする。
- 初期管理者はパスワード設定後、最初の管理画面利用前にMFAを登録する。
- 保護者MFAは初期リリースの必須条件にはしない。共通モデルで任意登録を許容できる設計とし、全保護者への必須化は利用性検証後に判断する。

### 7.2 `TotpCredential`

TOTPはRFC 6238準拠とし、30秒step、6桁、HMAC-SHA-1を相互運用上の初期値とする。検証窓は現在stepの前後1つまでとし、最後に成功したcounter以下の再利用を拒否する。

TOTP secretは検証に必要なためhash化できない。DBにはアプリ鍵でAEAD暗号化して保存し、暗号鍵はDB外へ置く。

| field | type | required | note |
| --- | --- | --- | --- |
| `id` | UUID | yes | 内部ID |
| `credential_id` | UUID FK | yes | 対象資格情報 |
| `encrypted_secret` | bytes | yes | AEAD暗号化 |
| `key_version` | string | yes | 鍵ローテーション用 |
| `confirmed_at` | datetime nullable | no | 初回code確認後に有効化 |
| `last_accepted_counter` | int nullable | no | replay防止 |
| `disabled_at` | datetime nullable | no | 無効化 |

暗号鍵 `HOIKUICT_CREDENTIAL_ENCRYPTION_KEY` は32 bytes以上のランダム値をsecret fileまたはOS secret storeから読み込む。リポジトリ、DB、backupと同じ場所へ平文保存しない。

### 7.3 回復コード

MFA登録時に128 bit以上のランダム回復コードを10個発行し、一度だけ表示する。DBには各コードのhashだけを保存し、使用時に1件ずつ消費する。再生成時は旧コードを全失効する。

管理者によるMFA解除は、別の有効管理者による本人確認と理由入力を必要とし、対象者の全sessionを失効する。管理者が1人しかいない場合はオフラインCLIと運用記録を使う。

## 8. Cookie仕様

productionでは職員と保護者のsession Cookieを分ける。

| 属性 | 職員 | 保護者 |
| --- | --- | --- |
| Name | `__Host-hoikuict_staff_session` | `__Host-hoikuict_parent_session` |
| Secure | true | true |
| HttpOnly | true | true |
| SameSite | Lax | Lax |
| Path | `/` | `/` |
| Domain | 指定しない | 指定しない |
| idle期限 | 既定30分 | 既定12時間 |
| absolute期限 | 既定12時間 | 既定7日 |

- Cookieにはopaque token以外を入れない。
- `Max-Age` はabsolute期限を超えない。
- login成功時と権限昇格を伴う再認証時にtokenをrotateする。
- 開発HTTPでは `__Host-` prefixを使わない開発専用名を使用する。
- ログイン、初期設定、再設定、MFA、logout完了、認証済み個人情報画面は `Cache-Control: private, no-store` とする。

キオスク端末Cookieは職員・保護者session Cookieと名前、用途、pathを分離する。キオスク端末Cookieの `Path` は `/guardian` とし、職員・保護者routeへ送信されることを前提にしない。職員・保護者Cookieの存在はキオスクアクセス判定へ影響させない。

## 9. ログインフロー

### 9.1 `GET /staff/login`

- 認証済みなら安全な内部redirectへ戻す。
- 未認証ならlogin IDとpasswordのフォームだけを表示する。
- 既存モックの職員一覧をproductionで表示しない。
- レスポンスを `no-store` とする。

### 9.2 `POST /staff/login`

1. CSRFを検証する。
2. login IDを正規化し、account・network throttleを確認する。
3. 対象Credentialを検索する。存在しなくてもdummy Argon2 hashを検証する。
4. Argon2idでpasswordを検証する。
5. Credentialと `User` の有効状態、職員ログイン対象範囲を確認する。
6. 失敗時は同一の利用者向け文言を返し、throttleと監査を更新する。
7. hash更新が必要なら再hashする。
8. 管理者またはMFA必須利用者は短命なpre-auth状態を作りMFA challengeへ進む。
9. MFA不要なら既存ブラウザsessionを失効し、新しい `AuthSession` を作る。
10. Cookieを設定し、CSRF tokenをrotateして安全な内部pathへ303で遷移する。

利用者向け失敗文言は「ログインIDまたはパスワードを確認してください」に統一する。アカウント不存在、無効、未設定、誤passwordを区別しない。

### 9.3 MFA challenge

- pre-auth tokenは10分以内、単回使用、HttpOnly CookieまたはDB sessionで管理する。
- password認証済みprincipal以外のTOTPを検証しない。
- TOTP失敗にも独立したrate limitを適用する。
- TOTPまたは未使用回復コード成功後にpre-authを破棄し、通常sessionを新規作成する。
- password成功だけでは管理者routeへ到達できない。

### 9.4 throttle既定値

- account bucketで5回連続失敗後、30秒の遅延を開始する。
- 以降は失敗に応じて指数的に延長し、最大15分とする。
- network bucketは5分間に30回を超える失敗を一時拒否する。
- 成功時はaccount連続失敗をresetするが、監査イベントは保持する。
- 永久lockは行わず、攻撃者によるアカウント固定を避ける。
- 管理者はthrottle状態を確認・解除できるが、解除操作を監査する。

値は施設規模と負荷試験で調整可能だが、実効的なrate limitを無効化できない。

参考: [NIST SP 800-63B Authentication](https://pages.nist.gov/800-63-4/sp800-63b.html)

### 9.5 `GET /parent-portal/login`

- 認証済みなら `/parent-portal/` または検証済みの保護者ポータル内部pathへ戻す。
- 未認証なら保護者用login IDとpasswordのフォームだけを表示する。
- 既存モックの保護者一覧をproductionで表示しない。
- 職員sessionが存在しても保護者認証済みとは扱わない。
- レスポンスを `no-store` とする。

### 9.6 `POST /parent-portal/login`

1. CSRFを検証する。
2. `principal_type=parent` のbucketでthrottleを確認する。
3. `principal_type=parent` と正規化login IDでCredentialを検索し、不在時もdummy Argon2を検証する。
4. password、Credential有効状態、`ParentAccount.status=active` を検証する。
5. 失敗時は職員と同じ一般化した文言、監査、throttleを適用する。
6. hash更新が必要なら再hashする。
7. 保護者用 `AuthSession` を作り、保護者専用Cookieを設定する。
8. `ParentAccount.last_login_at` を更新し、CSRF tokenをrotateする。
9. `/parent-portal/` または保存済みの安全な内部pathへ303で遷移する。

保護者sessionにはfamily IDやchild IDのアクセス範囲を保存しない。各リクエストで `ParentChildLink` を再評価し、同じ家庭であっても未紐付け園児へのアクセスを付与しない。

## 10. セッション解決と認可

既存 `StaffAuthBackend` / `ParentPortalAuthBackend` 抽象を維持し、`LocalPasswordStaffAuthBackend` / `LocalPasswordParentAuthBackend` を追加する。

- HTMLの認証必須GETが未認証の場合、`/staff/login?redirect=...` へ303で遷移する。
- JSON/APIは401を返し、HTMLを返さない。
- WebSocket handshakeも同じ職員sessionを検証する。
- `User.is_active=false`、Credential無効、version不一致、期限切れは即座に未認証とする。
- ロール・業務権限変更は次のリクエストから反映する。
- `last_seen_at` は書込増加を避け、5分以上の間隔で更新する。
- admin routeはsessionのMFA完了状態も確認する。
- 保護者routeは `ParentAccount.status` と明示的な `ParentChildLink` を毎回確認する。
- 職員Cookieを保護者backendで、保護者Cookieを職員backendで受け入れない。

backend選択は起動時に一度だけ行い、テスト間では既存reset機構でglobal状態を戻す。

## 11. 初期設定・パスワード変更・再設定

### 11.1 初期管理者

空DBではオフラインCLIだけが最初の管理者を作成できる。

```text
auth-user bootstrap-admin
```

CLIは氏名、login ID、連絡先、実行理由を受け取り、`User`、`PasswordCredential`、24時間のactivation tokenを作る。passwordやtokenをcommand line引数・環境変数で受け取らない。activation codeは端末へ一度だけ表示し、DBにはhashだけを保存する。

管理者は `/staff/activate` でcode、新しいpassword、確認passwordを入力し、その後TOTPを登録する。TOTP登録まで通常管理画面へ進めない。

### 11.2 職員追加

既存職員管理画面でUserを作成した後、管理者がactivation codeを発行する。管理者は本人へ対面、電話等の承認済み別経路でcodeを渡す。監査ログには実行者、対象者、期限、理由を残すがcodeは残さない。

### 11.3 保護者追加

`ParentAccount` と対象園児の `ParentChildLink` を管理者が確認した後、保護者用activation codeを発行する。codeは本人確認済みの対面、封書、電話等の施設承認済み経路で渡し、通常の園児連絡本文や共有掲示へ記載しない。

保護者は `/parent-portal/activate` でcodeと新passwordを設定する。activation成功だけでは閲覧園児を増やさず、アクセス範囲は既存の明示的な `ParentChildLink` に限定する。

### 11.4 認証済み変更

利用者自身のpassword変更は、現在passwordを再検証してから新passwordを設定する。

- credential versionを加算する。
- 現在操作中session以外の全sessionを失効する。
- 現在sessionもtokenをrotateする。
- blocklistとpassword policyを再適用する。
- 旧passwordの再利用履歴は初期実装では保存しない。

### 11.5 passwordを忘れた場合

閉域標準では職員・保護者が施設管理者へ連絡し、管理者が対象principal用の30分reset codeを発行する。管理者は新passwordを指定できず、利用者本人が各専用入口でcodeと新passwordを入力する。

ログイン画面の「パスワードを忘れた場合」はアカウント存在を判定せず、施設管理者への連絡方法だけを表示する。任意SMTPを導入するまで、公開フォームからメールを自動送信しない。

### 11.6 緊急復旧

有効管理者が全員ログインできない場合だけ、サーバーconsoleのオフラインCLIで短命reset codeまたはMFA recoveryを発行する。実行にはDB filesystem権限、対話確認、理由入力を必要とし、実行後に監査記録を確認する。

## 12. ログアウト・失効

`POST /staff/logout` と `POST /parent-portal/logout` はCSRF保護対象とする。

1. 現在の `AuthSession` を `explicit_logout` で失効する。
2. session Cookieを削除する。
3. CSRF tokenをrotateする。
4. `/` へ303で戻し、ログアウト完了を表示する。

保護者logoutでは、sessionを失効する前に既存仕様どおり当該ブラウザのpush購読を `explicit_logout` で無効化し、push device Cookieも削除する。その後、保護者session Cookieを削除して `/parent-portal/login` へ戻す。push購読処理が失敗しても認証sessionを残したままにせず、失敗を監査してlogout自体は完了させる。

User無効化、Credential無効化、password reset、管理者によるMFA解除、緊急失効では、対象者の全sessionを同一トランザクションで失効する。

退職時は `User.is_active=false`、Credential無効化、全session失効を一つのサービス操作として行う。退園・利用停止時は `ParentAccount.status` 変更、保護者Credential無効化、全session失効、全push購読無効化を一つのサービス操作として行う。

## 13. CSRF・リダイレクト・ログ

- login、activation、reset、MFA、logoutのPOSTは既存CSRF middlewareで保護する。
- `redirect` は相対的な内部pathだけを許可する。
- password、TOTP、回復コード、activation/reset codeをURLへ入れない。
- form bodyをaccess logへ出さない。
- 認証失敗画面にUserの存在、有効状態、ロール、内部例外を出さない。
- password hash全文を通常ログ・監査ログ・管理画面へ出さない。
- login formに `autocomplete="username"`、passwordに適切な `current-password` / `new-password` を設定する。

## 14. 秘密情報とbackup

### 14.1 アプリsecret

少なくともlogin throttle HMAC key、TOTP暗号鍵、既存アプリsecretをDB外に置く。secretは権限を制限したfileまたはOS secret storeから読み込む。`.env.example` には名前だけを記載し、実値を置かない。

### 14.2 backup

DB backupにはpassword hash、暗号化済みTOTP secret、session hash、監査ログが含まれるため、通常業務データと同等以上に保護する。

- backupを暗号化する。
- 復旧担当者を制限する。
- TOTP暗号鍵はDB backupと別管理する。
- 鍵を含めた災害復旧手順を用意するが、同一媒体へ平文同居させない。
- 復旧テスト後、復元された古いsessionとaction tokenを全失効する。

## 15. 環境変数と起動時検証

| 変数 | 必須条件 | 内容 |
| --- | --- | --- |
| `HOIKUICT_STAFF_AUTH_MODE` | 常時 | `mock` / `local_password` / `disabled` |
| `HOIKUICT_PARENT_AUTH_MODE` | 常時 | `mock` / `local_password` / `disabled` |
| `HOIKUICT_STAFF_SESSION_IDLE_MINUTES` | 任意 | 既定30、許容5〜480 |
| `HOIKUICT_STAFF_SESSION_ABSOLUTE_HOURS` | 任意 | 既定12、許容1〜24 |
| `HOIKUICT_PARENT_SESSION_IDLE_HOURS` | 任意 | 既定12、許容1〜168 |
| `HOIKUICT_PARENT_SESSION_ABSOLUTE_DAYS` | 任意 | 既定7、許容1〜30 |
| `HOIKUICT_LOGIN_THROTTLE_HMAC_KEY` | local_password時 | 32 bytes以上 |
| `HOIKUICT_CREDENTIAL_ENCRYPTION_KEY` | MFA有効時 | 32 bytes以上、version管理 |
| `HOIKUICT_PASSWORD_BLOCKLIST_PATH` | production | ローカルblocklist file |
| `HOIKUICT_KIOSK_ACCESS_MODE` | 常時 | `disabled` / `token` / 開発専用`open` |
| `HOIKUICT_KIOSK_TOKEN` | kiosk=token時 | 端末activation用secret |

移行期間中、development/testで新mode変数が未設定かつ `HOIKUICT_ENABLE_MOCK_AUTH=1` の場合だけ従来どおりmockと解釈できる。productionでは互換解釈を使わない。

productionでは次を満たさなければ起動を拒否する。

- `HOIKUICT_ENABLE_MOCK_AUTH` が有効でない
- `HOIKUICT_STAFF_AUTH_MODE=local_password`
- `HOIKUICT_PARENT_AUTH_MODE=local_password`
- `HOIKUICT_KIOSK_ACCESS_MODE` が `disabled` または `token`
- kiosk modeが `token` の場合、`HOIKUICT_KIOSK_TOKEN` が空でない
- secure CookieとCSRF保護が有効
- HMAC keyとTOTP暗号鍵が要件を満たす
- blocklist fileが存在し、読取可能で、最小件数とchecksum要件を満たす
- Argon2設定が最低値を下回らない
- password検証benchmarkが事前記録されている

## 16. 障害時の挙動

| 障害 | 挙動 |
| --- | --- |
| DB参照不可 | fail closed。認証済み扱いにしない |
| Argon2内部エラー | login拒否、一般化した503、秘密を含めず記録 |
| blocklist読込不可 | 新規設定・変更・resetを停止。既存password loginは継続可 |
| TOTP暗号鍵読込不可 | MFA必須loginを停止。MFA bypassしない |
| 監査ログ保存不可 | login成功sessionを作らずrollback |
| SMTP停止 | 手動code運用を使用。login自体には影響させない |
| 時刻ずれ | 時刻源を復旧し、TOTP検証窓を無制限に広げない |

認証障害を理由にproductionでmockへ自動fallbackしない。

## 17. 保護者認証の同時実装要件

保護者認証は職員認証と同じ初期リリース段階で実装し、片方だけをproductionへ有効化しない。共通のCredential・Argon2・session serviceを利用する一方、principal、入口、Cookie、throttle、認可テストを分離する。

- `ParentAccount.status=active` を毎回確認する。
- family・child linkをローカルDBだけの認可根拠とする。
- password hashは `PasswordCredential` に保存する。
- 既存 `ParentAccount.password_hash` を新規利用しない。
- login成功時に `last_login_at` を更新する。
- logout時は当該ブラウザのpush購読を無効化してからsessionを失効する。
- activation/reset codeは、施設が本人確認した対面、封書、電話等の承認済み経路で渡す。
- 保護者sessionは既定idle 12時間、absolute 7日とし、共有端末・家庭端末の実機試験を行う。
- 職員・保護者のどちらかの受入条件が未達なら、認証リリース全体を未完了とする。

## 18. テスト仕様

### 18.1 Argon2・password policy

- hashごとにsaltが異なる
- 正しいpasswordだけが検証成功する
- パラメータ不足hashを成功ログイン時にrehashする
- Unicode、空白、NFC、最大長を仕様どおり扱う
- NUL、制御文字、過大入力を拒否する
- blocklist、login ID・園名由来passwordを拒否する
- password、hash、生tokenをログへ出さない
- benchmarkと同時実行メモリ試験

### 18.2 職員・保護者loginと列挙対策

- 職員・保護者それぞれの正常login、誤password、不明login ID、無効principal、未設定Credential
- 失敗画面・status・主要な処理時間から存在有無を容易に判別できない
- 不明login IDでもdummy Argon2を実行する
- account・network throttle、指数遅延、成功時reset
- login ID正規化とprincipal種別分離
- safe redirect、CSRF、session fixation、Cookie属性
- 同一login IDのstaffとparentが各専用入口で別Credentialとして解決される
- staff Credentialを保護者入口へ、parent Credentialを職員入口へ入力してもloginできない

### 18.3 session・認可

- Cookie改ざん・DBにないsessionは401
- idle・absolute期限
- User/Credential無効化とcredential version変更を次リクエストで反映する
- role・業務権限変更をCookie再発行なしで反映する
- staff sessionでparent principalになれず、その逆も成立する
- `ParentAccount.status` 変更が次リクエストで反映される
- `ParentChildLink` のない園児を一覧・直接URL・更新APIから閲覧できない
- HTMLとJSONの未認証応答を分ける
- WebSocketが同じsession境界を使う

### 18.4 activation・reset・MFA

- token hashだけを保存し、期限、単回使用、再発行失効が成立する
- 管理者がpasswordを指定・閲覧できない
- staff activation codeをparentへ、parent activation codeをstaffへ使用できない
- 保護者activation後も `ParentChildLink` 以外のアクセスが増えない
- password変更・reset後にsessionを失効する
- 初期管理者CLIが秘密を引数に取らない
- TOTP登録確認前は有効にならない
- 正常code、前後1 step、範囲外、再利用counterを検証する
- MFA必須adminはpasswordだけで業務routeへ進めない
- 回復コード単回使用、MFA解除時の全session失効
- 暗号鍵不在時にbypassしない

### 18.5 回帰

- development/testで既存モック職員loginを維持する
- development/testで既存モック保護者loginを維持する
- productionでモックrouteが404になる
- 既存 `CurrentUser`、職員ポータル、担当クラス、権限テストが同じ意味で通る
- 保護者ポータル、園児アクセス、push logoutの既存テストがローカル認証でも通る
- productionで職員・保護者の片方だけを `local_password` にした設定を拒否する

### 18.6 登降園キオスク境界

- 職員・保護者が未loginでも、有効化済みキオスク端末から一覧表示と登降園打刻ができる
- 職員・保護者がlogin済みでも、未有効化端末は `token` modeのキオスクへアクセスできない
- キオスク端末Cookieで職員・保護者の保護routeへアクセスできない
- 職員・保護者session Cookieだけではキオスク端末認可を満たさない
- 職員・保護者login/logout、password変更、session全失効後もキオスク端末の有効状態が意図せず変化しない
- キオスクactivation tokenのrotationで既存端末Cookieが無効になる
- `disabled` modeではactivationを含む `/guardian/**` が404になる
- productionの `open` modeを起動時に拒否する
- キオスクの全POSTでCSRFを検証する
- 職員・保護者認証のテスト用dependency overrideがなくても、キオスク専用テストが成立する

## 19. 導入・切戻し

### 19.1 導入順

1. schema、Argon2 service、CLIを導入するがauth modeは変更しない。
2. 導入対象サーバーでArgon2 benchmarkと同時実行試験を行う。
3. blocklist、HMAC key、TOTP暗号鍵、backup手順を設定する。
4. 初期管理者をCLIで作り、activation、password、TOTP、回復コードを確認する。
5. ステージングで職員・保護者双方のlogin、logout、権限境界、無効化、reset、MFA、push logout、復旧を確認する。
6. 対象職員・保護者へprincipal別のactivation codeを発行する。
7. maintenance windowでstaff auth modeとparent auth modeを同時に `local_password` へ変更する。
8. 管理者loginを最初に確認し、テスト保護者のアクセス境界を確認してから全利用者を開放する。
9. 職員・保護者別のlogin成功率、失敗理由、throttle、Argon2 latency、session失効を監視する。

### 19.2 切戻し

本番でmock認証へ切り戻してはならない。障害時は入口をmaintenance表示または接続元制限下に置き、直前アプリ版へ戻す。DB migrationは追加型とし、旧アプリが新テーブルを無視できる状態を維持する。

## 20. 実装フェーズとブランチ分割

| 順序 | 推奨ブランチ | 内容 |
| --- | --- | --- |
| 0 | `codex/local-auth-spec` | 本仕様、仕様一覧、MkDocsナビゲーション |
| 1 | `codex/local-auth-credentials` | staff・parent Credential、action token、Argon2、policy、migration、単体テスト |
| 2 | `codex/local-auth-sessions` | 職員・保護者login/logout、分離session、throttle、両backend、統合テスト |
| 3 | `codex/local-auth-lifecycle-cli` | 初期管理者、職員・保護者activation/reset、失効、監査、運用手順 |
| 4 | `codex/local-auth-mfa-hardening` | TOTP、回復コード、鍵管理、production検証、負荷試験 |

各ブランチは前段がmainへ統合された後のmainから作る。各実装ブランチでstaffとparentを同時に扱い、片方だけを完成扱いにしない。一方でCredential、session、ライフサイクル、MFAは巨大な1ブランチへまとめない。

## 21. 受入条件

初期の職員・保護者認証は次をすべて満たした時に完了とする。

- Argon2idを承認済みパラメータで使い、導入サーバー上のbenchmark記録がある。
- password policy、ローカルblocklist、rate limitが有効である。
- password、hash全文、action token、session token、TOTP secretがログへ出ない。
- 不明login IDを含む失敗応答でアカウント列挙を抑止している。
- 職員・保護者の初期設定・変更・resetを管理者がpasswordを知らずに実行できる。
- 単回使用コードはhash保存、期限、消費、再発行失効を持つ。
- opaque session Cookieに権限やpassword情報が入っていない。
- User/Credential無効化、credential version、session期限が即時に反映される。
- ロールと業務権限がローカルDBを正として評価される。
- `ParentAccount.status` と `ParentChildLink` が保護者認可の正本として毎回評価される。
- 職員・保護者のCookie、principal、throttle、activation codeが相互利用できない。
- 保護者logoutで当該ブラウザのpush購読とsessionが失効する。
- 有効化済みキオスク端末が職員・保護者loginなしで登降園操作できる。
- キオスク端末Cookieと職員・保護者session Cookieが相互の認証・端末認可へ利用できない。
- productionでキオスク `open` modeを使用できず、`token` または `disabled` だけを許可する。
- productionのadminがTOTP MFAを完了しなければ管理画面へ進めない。
- 回復コードと緊急オフライン復旧手順が検証されている。
- productionでmock認証へfallbackできない。
- backup、TOTP暗号鍵、復旧後session失効の手順がある。
- 正常系、攻撃・誤設定系、障害系、負荷、回帰の自動テストが通る。
- ステージングで職員・保護者双方のlogin、logout、無効化、reset、認可境界、MFA、push logout、切戻しを確認している。
