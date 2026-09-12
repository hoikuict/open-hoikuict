# 本番設定・セキュリティ

現況確認: 2026年9月13日。起動条件は `security_config.validate_runtime_security()`、認証・権限は各ルーターとサービスが検証します。このページは現行コードの設定を説明します。新規導入は[TrueNAS導入ガイド](truenas-beginner-installation-guide.md)から進めてください。

## productionの起動条件

| 設定 | 必須条件 |
| --- | --- |
| `HOIKUICT_ENV` | `production`。未指定時もproduction扱い |
| `HOIKUICT_STAFF_AUTH_MODE` / `HOIKUICT_PARENT_AUTH_MODE` | 両方 `local_password` |
| `HOIKUICT_ENABLE_MOCK_AUTH` / `HOIKUICT_ENABLE_MOCK_ROLE_OVERRIDE` | `1` を使用しない |
| `HOIKUICT_COOKIE_SECURE` / `HOIKUICT_CSRF_ENFORCE` | 両方 `1` |
| `HOIKUICT_SECRET_KEY` | 32文字以上 |
| `HOIKUICT_LOGIN_THROTTLE_HMAC_KEY` | 32バイト以上 |
| `HOIKUICT_PASSWORD_BLOCKLIST_PATH` | 読み取り可能なパスワード禁止リスト |
| `FORWARDED_ALLOW_IPS` | 信頼するプロキシのIP/CIDRを明示。`*` は不可 |
| `HOIKUICT_PARENT_MAIL_TRANSPORT` | `smtp` |
| `HOIKUICT_PARENT_REGISTRATION_BASE_URL` | HTTPSの施設URL |
| SMTP | `HOIKUICT_SMTP_HOST`、`HOIKUICT_SMTP_PORT`、`HOIKUICT_PARENT_MAIL_FROM`、`HOIKUICT_SMTP_STARTTLS=1` |
| `HOIKUICT_KIOSK_ACCESS_MODE` | `disabled` または `token`。`token`には登録トークンが必要 |
| `HOIKUICT_PUSH_TRANSPORT` | 既定は `disabled`。`capture`は禁止。`webpush`は追加検証あり |

productionを明示したプロセスへ、アプリ隣接の開発用 `.env` を自動マージしません。設定は配備先のCompose等で渡します。WebSocketドライバーも起動時に検査するため、`requirements.txt`のUvicorn依存を使います。

この検証を通ることは、権限設定・配送・バックアップが運用上正しいことまで保証しません。

## 認証と園児へのアクセス

職員と保護者は入口、セッションCookie、認証主体を分離します。ローカルパスワードにはArgon2id、セッションには推測困難なトークンを使い、試行制限と認証イベントを記録します。

職員の基本ロールは `admin` / `can_edit` / `view_only` です。業務別権限と担当クラスを設定し、閲覧専用者が更新できないことを確認します。保護者は明示的な `ParentChildLink` による対象児だけへアクセスします。「同じ家庭の全園児」を無条件で許可しません。

初期設定・復旧・停止は[アカウントガイド](accounts.md)へ。MFA・回復コードは後続計画であり、配備設定によって有効化できる現行機能ではありません。

## プロキシとブラウザー

Uvicornは `--proxy-headers` で起動し、信頼する転送元だけを `FORWARDED_ALLOW_IPS` に指定します。プロキシ以外からアプリへ直接到達する経路を制限し、任意の転送ヘッダーで接続元を偽装できない構成にします。

`HOIKUICT_ALLOWED_ORIGINS`には利用する施設originを設定します。Web Pushでは公開origin・登録URLとの一致も検査します。フォームのCSRF、Secure Cookie、WebSocketのorigin検査を含めて確認してください。

## キオスクの端末認証

`/guardian` は氏名を表示して打刻する端末機能です。本番の `open` モードは拒否されます。`token` の場合は `/guardian/activate` で端末を一度有効化し、職員・保護者の個人ログインとは独立して扱います。秘密値をURLへ付けません。

`/guardian/terminal` は専用の表示入口で、表示モードのCookie自体は認証を代替しません。[キオスク設定](chromebook-guardian-kiosk.md)に従って端末と接続制限を準備します。端末を失効させる場合はトークンまたはsecretのローテーションと、影響する端末の再有効化を計画します。

## メール・Web Push

本番SMTPの資格情報とVAPID秘密鍵はGitへ置かず、配備先で管理します。通知は本人の設定と有効な園児リンクを配送直前にも確認します。Web Pushの送信先・鍵・originの検証と端末テストは[本番設定手順](parent-push-production-setup.md)を参照してください。

## データと監査

- 通常起動で業務デモデータを生成せず、初期管理者はCLIで明示作成する。
- DBだけでなく、文例・添付・構成・鍵の保存先と復元方法を管理する。
- アカウント、権限、園児情報変更、打刻訂正、料金・請求などの履歴を確認する。
- 実在データをIssue、スクリーンショット、公開デモ、ログへ混入させない。

保管・復旧は[バックアップ仕様](backup-restore-spec.md)、施設の取扱方針は[個人情報](privacy.md)、脆弱性の報告先は[問い合わせ](license.md)を参照してください。
