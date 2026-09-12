# 画面・URL一覧

UI調整とデバッグで迷子にならないための、現時点の主要画面遷移メモです。
API、CSV出力、WebSocket、HTMXの部分更新は、画面確認に関係するものだけ載せています。

- 最終照合日: 2026-09-13
- 照合元: `main.py`に登録されたFastAPIルート
- モックログインは `HOIKUICT_ENABLE_MOCK_AUTH=1` と各認証モードが `mock` の場合に登録。`local_password` の入口は各モードが有効な場合に登録される。
- 一覧は主要画面と操作入口を示す。POSTの確認・確定画面はフォームから進み、直接GETで開くページとは区別する。

## 共通

| 入口 | 主な遷移 |
| --- | --- |
| `/` | 未ログイン時はログイン案内、ログイン後は職員ホームを表示 |
| `/staff/portal` | ログイン後の職員ホームへの別名。未ログイン時は職員ログインへ |
| `/staff/attention` | ログイン中職員の要確認事項一覧 |
| `/staff/login` | local_passwordではID・パスワード、モックでは職員選択。成功後に `redirect` 指定先へ |
| `POST /staff/logout` | 職員セッションを終了し、ログイン画面へ |
| `/switch-role?redirect=...` | モック専用。`/staff/login?redirect=...` へ |

## ローカル認証・登録

| 機能 | 入口 | 主な遷移・条件 |
| --- | --- | --- |
| 職員初期設定 | `/staff/activate` | コード確認、ログインID確認、本人のパスワード設定 |
| 職員再設定 | `/staff/reset-password` | 管理者が発行したコードから本人が設定 |
| 管理者メール復旧 | `/staff/forgot-password` | メール案内から `/staff/recover-password` へ |
| 職員認証管理 | `/staff/users/{user_id}/authentication` | 初期設定・再設定コードの発行 |
| 保護者共通QR管理 | `/parent-accounts/registration-qr` | 受付開始・停止、案内印刷、QR画像 |
| 共通QRの申請 | `/parent-portal/register/apply` | メール確認、初回入力、園の承認 |
| 保護者初回入力の招待 | `/parent-accounts/enrollment/new` | 子どもの名前とメールから招待 |
| 招待の確認 | `/parent-portal/register/invite` | コード確認後 `/parent-portal/register/identity`、提出後 `/parent-portal/register/status` |
| 保護者認証管理 | `/parent-accounts/{account_id}/authentication` | 招待・再送、登録申請の承認・却下、コード発行、ログインID変更、停止 |
| 承認後の設定 | `/parent-portal/register/complete` | メールのリンク・コードからパスワード設定 |
| 保護者初期設定・再設定コード | `/parent-portal/activate`、`/parent-portal/reset` | コード確認後、本人がパスワードを設定 |
| 保護者パスワード変更 | `/parent-portal/account/password` | ログイン中の本人が変更 |

操作の選び方は[アカウントガイド](accounts.md)を参照。

## 職員側

| 機能 | 入口 | 主な遷移 |
| --- | --- | --- |
| 職員ホーム | `/`、`/staff/portal` | 当日予定、担当クラス出席、要確認 `/staff/attention`、職員ルームの保護者連絡タイムライン |
| 職員管理 | `/staff/users` | 新規 `/staff/users/new`、編集 `/staff/users/{user_id}/edit`、担当クラス `/staff/users/{user_id}/classrooms` |
| 職員権限設定 | `/staff/permissions` | 基本ロール、園児台帳管理、請求口座情報管理の更新 |
| 園児一覧 | `/children/` | 新規 `/children/new`、詳細 `/children/{child_id}`、編集 `/children/{child_id}/edit`、兄弟追加 `/children/new?sibling_id={child_id}` |
| 園児詳細 | `/children/{child_id}` | 編集、変更履歴、健康サマリー、子どもの記録、児童票 |
| 子どもの記録 | `/children/{child_id}/records` | 新規記録、訂正、無効化、児童票の根拠参照 |
| 児童票 | `/children/{child_id}/progress-records` | 新規 `/children/{child_id}/progress-records/new`、作成後は計画文書詳細へ |
| 児童票進捗 | `/child-records/progress` | 年齢区分・作成状況で絞り込み、園児別児童票へ |
| 児童記録設定 | `/settings/child-records` | 記録項目、年齢別頻度、閲覧範囲を版として保存 |
| 家庭管理 | `/families/` | 新規 `/families/new`、編集 `/families/{family_id}/edit`、この家族に園児追加 `/children/new?family_id={family_id}` |
| クラス管理 | `/classrooms/` | 新規 `/classrooms/new`、編集 `/classrooms/{classroom_id}/edit` |
| 健康管理 | `/health` | 健康サマリー `/children/{child_id}/health`、健診記録 `/children/{child_id}/health/check-records` |
| 健康サマリー | `/children/{child_id}/health` | 健康プロフィール、アレルギー管理、健診記録、園児詳細 |
| 健康プロフィール | `/children/{child_id}/health/profile` | 保存後、同画面へ |
| アレルギー管理 | `/children/{child_id}/health/allergies` | 新規、編集 `?edit={allergy_id}`、無効化、再有効化 |
| 健診記録 | `/children/{child_id}/health/check-records` | 新規記録後、同画面へ |
| 出欠一覧 | `/attendance/` | 日付・クラス・期間絞り込み、登園、降園、CSV/Excel出力、延長料金表示切替 |
| お迎え予定の変更 | `/attendance/{child_id}/pickup?date=...` | 予定時刻・予定者の変更と履歴 |
| 誤打刻の取消 | `/attendance/{child_id}/correction?date=...` | 降園のみ／登降園・予定の取消、理由と履歴、確定料金等の保護 |
| 出欠確認 | `/attendance-checks/` | 日付・クラス絞り込み、園児ごとの確認更新 |
| 日次連絡 | `/daily-contacts/` | 園児別詳細 `/daily-contacts/{child_id}` |
| 延長保育料金 | `/extended-care-fees/` | 再計算、確定、調整、対象外、CSV出力、料金ルール、請求転送 `/extended-care-fees/billing-transfer` |
| 延長保育料金・請求転送 | `/extended-care-fees/billing-transfer` | プレビュー、転送・再転送、転送解除、手入力競合の解消 |
| 延長保育料金ルール | `/extended-care-fees/settings` | ルール追加、既存ルール更新後、同画面へ |
| 請求入力 | `/billing/` | 入力サイクル作成、園児別入力 `/billing/cycles/{cycle_id}/child-charges`、全銀データ作成、入金デモ反映 |
| 請求口座情報 | `/billing/accounts` | 権限のある職員だけが家族口座情報を表示・編集 |
| 園児別請求一覧 | `/billing/cycles/{cycle_id}/child-charges` | 園児別詳細 `/billing/cycles/{cycle_id}/child-charges/{child_id}`、一括保存 |
| 園児別請求詳細 | `/billing/cycles/{cycle_id}/child-charges/{child_id}` | 請求項目保存、請求プロフィール保存 |
| 保護者キオスク | `/guardian` | クラス・園児選択、登園、迎え予定確認、降園確認 |
| キオスクの設定案内 | `/guardian/setup` | 端末登録の案内、管理者の設定確認 |
| キオスク端末有効化 | `/guardian/activate` | tokenモードの端末登録 |
| 専用キオスク | `/guardian/terminal` | 共用端末向けの表示、応答監視 |
| 端末監視設定 | `/settings/guardian-terminals` | 管理者による端末名・監視時間・有効無効の設定 |
| 迎え予定確認 | `POST /guardian/child/{child_id}/pickup` | 確定後、キオスクへ |
| 降園確認 | `POST /guardian/child/{child_id}/check-out` | 確定後、キオスクへ |
| お知らせ管理 | `/notices/` | 新規 `/notices/new`、編集 `/notices/{notice_id}/edit` |
| アンケート管理 | `/surveys/` | 新規 `/surveys/new`、詳細 `/surveys/{survey_id}`、編集 `/surveys/{survey_id}/edit`、回答CSV |
| 保護者アカウント | `/parent-accounts/` | 新規 `/parent-accounts/new`、編集 `/parent-accounts/{account_id}/edit`、認証管理、共通QR、初回入力の招待。保護者として確認 `/parent-portal/mock-login/{account_id}` はモック環境のみ |
| プロフィール変更申請 | `/child-change-requests` | 詳細 `/child-change-requests/{request_id}`、承認、却下 |
| データ入出力 | `/data-transfers/` | 職員・クラス・家庭・園児・保護者・リンクのテンプレート、出力、事前検証・確定、認可施設帳票 |
| カレンダー | `/calendar` | 表示切替 `/calendar/view`、予定作成 `/events/new`、予定詳細 `/events/{event_id}`、予定編集 `/events/{event_id}/edit`、検索 `/search/events` |
| カレンダー設定 | `/calendar` | カレンダー作成、更新、アーカイブ、復元、削除、共有、表示切替 |
| 職員ルーム | `/staff-rooms/` | メッセージ投稿、タイムライン更新、スレッド `/staff-rooms/threads/{parent_message_id}`、添付 `/staff-rooms/attachments/{attachment_id}` |
| 議事録 | `/meeting-notes/` | 新規作成後 `/meeting-notes/{note_id}`、詳細から一覧へ |
| 職員アンケート | `/staff-surveys/` | 回答画面 `/staff-surveys/{survey_id}`、保存後一覧へ |
| 園内記録 | `/records/` | 新規、詳細、編集、公開範囲、関連リンク、レビュー、廃止 |
| ハイライト | `/highlights/` | コメント、園内記録への昇格、アーカイブ |
| 年度継続記録 | `/event-series/` | 一覧、新規、詳細、年度別メンバー追加 |

| 文書の確認依頼 | `/document-reviews/` | 本文・添付の提出、詳細 `/document-reviews/{review_id}`、管理者の判定 |
| バックアップ管理 | `/settings/backups` | 管理者の即時実行依頼、毎日・毎週の予定、履歴・結果 |

## 保護者側

| 機能 | 入口 | 主な遷移 |
| --- | --- | --- |
| 保護者ログイン | `/parent-portal/login` | ログイン後 `/parent-portal/` |
| 保護者ホーム | `/parent-portal/` | 日付切替、日次連絡、履歴、お知らせ、アンケート、プロフィール、子ども情報変更申請 |
| 保護者プロフィール | `/parent-portal/profile` | 保存後、同画面へ |
| 子ども情報変更申請選択 | `/parent-portal/children/profile` | 対象児選択 `/parent-portal/children/{child_id}/profile` |
| 子ども情報変更申請 | `/parent-portal/children/{child_id}/profile` | 申請後、ホームまたは同画面へ |
| 日次連絡入力 | `/parent-portal/children/{child_id}/contact` | 保存後、ホームへ |
| 日次連絡履歴 | `/parent-portal/history` | 過去連絡の編集 `/parent-portal/children/{child_id}/contact?date=...` |
| 保護者向けお知らせ | `/parent-portal/notices` | 詳細 `/parent-portal/notices/{notice_id}` |
| 保護者向けアンケート | `/parent-portal/surveys` | 回答 `/parent-portal/surveys/{survey_id}`、対象児選択付き回答 `?child_id={child_id}` |
| 通知設定 | `/parent-portal/push-settings` | 端末登録、プッシュ・メール受信設定、本人端末へのテスト通知 |
| 保護者ログアウト | `POST /parent-portal/logout` | 現在端末の購読を無効化し、`/parent-portal/login` へ |

## 指導計画

| 機能 | 入口 | 主な遷移 |
| --- | --- | --- |
| 指導計画ホーム | `/plans/` | 年案、月案、週案、日案、文例選択、自作文例追加、文書一覧 |
| 年案作成 | `/plans/annual-plans/new` | 保存後 `/plans/documents/{document_id}` |
| 月案作成 | `/plans/monthly-plans/new` | 保存後 `/plans/documents/{document_id}` |
| 週案作成 | `/plans/weekly-plans/new` | 保存後 `/plans/documents/{document_id}` |
| 日案作成 | `/plans/daily-plans/new` | 保存後 `/plans/documents/{document_id}` |
| 日案カレンダー | `/plans/daily-plans/` | 日別の作成状況・活動を確認し、日案作成または詳細へ |
| 文書一覧 | `/plans/documents/` | 詳細 `/plans/documents/{document_id}` |
| 文書詳細 | `/plans/documents/{document_id}` | 編集、ステータス更新、日案の振り返り、承認後の実施変更・確認・訂正 |
| 文書編集 | `/plans/documents/{document_id}/edit` | 保存後、詳細へ |
| 月案文例選択 | `/plans/bunrei/monthly` | 文例から作成後 `/plans/documents/{document_id}/edit` |
| 年案文例選択 | `/plans/bunrei/annual` | 文例から作成後 `/plans/documents/{document_id}/edit` |
| 自作文例追加 | `/plans/bunrei/facility/new` | 追加後、文例選択画面へ |

## 出力・補助

| 種類 | URL |
| --- | --- |
| 出欠CSV/Excel | `/attendance/export.csv`、`/attendance/export.xlsx` |
| 延長保育料金CSV | `/extended-care-fees/export.csv` |
| アンケート回答CSV | `/surveys/{survey_id}/answers.csv` |
| 全銀データ | `/billing/zengin/exports/{export_id}/download` |
| データ入出力テンプレート | `/data-transfers/templates/{file_name}` |
| データエクスポート | `/data-transfers/export/{file_name}` |
| 認可施設帳票出力 | `POST /data-transfers/ninka/export` |
| ヘルスチェック | `/healthz` |
