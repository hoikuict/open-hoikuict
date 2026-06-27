# 画面遷移リスト

UI調整とデバッグで迷子にならないための、現時点の主要画面遷移メモです。
API、CSV出力、WebSocket、HTMXの部分更新は、画面確認に関係するものだけ載せています。

## 共通

| 入口 | 主な遷移 |
| --- | --- |
| `/` | `/children` へリダイレクト |
| `/staff/login` | 職員選択後、`redirect` 指定先へ |
| `/staff/logout` | ログアウト後、指定先またはログイン画面へ |
| `/switch-role?redirect=...` | `/staff/login?redirect=...` へ |

## 職員側

| 機能 | 入口 | 主な遷移 |
| --- | --- | --- |
| 園児一覧 | `/children/` | 新規 `/children/new`、詳細 `/children/{child_id}`、編集 `/children/{child_id}/edit`、兄弟追加 `/children/new?sibling_id={child_id}` |
| 園児詳細 | `/children/{child_id}` | 編集、健康サマリー `/children/{child_id}/health` |
| 家庭管理 | `/families/` | 新規 `/families/new`、編集 `/families/{family_id}/edit`、この家族に園児追加 `/children/new?family_id={family_id}` |
| クラス管理 | `/classrooms/` | 新規 `/classrooms/new`、編集 `/classrooms/{classroom_id}/edit` |
| 健康管理 | `/health` | 健康サマリー `/children/{child_id}/health`、健診記録 `/children/{child_id}/health/check-records` |
| 健康サマリー | `/children/{child_id}/health` | 健康プロフィール、アレルギー管理、健診記録、園児詳細 |
| 健康プロフィール | `/children/{child_id}/health/profile` | 保存後、同画面へ |
| アレルギー管理 | `/children/{child_id}/health/allergies` | 新規、編集 `?edit={allergy_id}`、無効化、再有効化 |
| 健診記録 | `/children/{child_id}/health/check-records` | 新規記録後、同画面へ |
| 出欠一覧 | `/attendance` | 日付・クラス絞り込み、登園、降園、CSV/Excel出力 |
| 出欠確認 | `/attendance-checks/` | 日付・クラス絞り込み、園児ごとの確認更新 |
| 日次連絡 | `/daily-contacts/` | 園児別詳細 `/daily-contacts/{child_id}` |
| 延長保育料金 | `/extended-care-fees/` | 再計算、確定、調整、対象外、CSV出力、料金ルール `/extended-care-fees/settings` |
| 延長保育料金ルール | `/extended-care-fees/settings` | ルール追加、既存ルール更新後、同画面へ |
| 請求入力 | `/billing/` | 入力サイクル作成、園児別入力 `/billing/cycles/{cycle_id}/child-charges`、全銀データ作成、入金デモ反映 |
| 園児別請求一覧 | `/billing/cycles/{cycle_id}/child-charges` | 園児別詳細 `/billing/cycles/{cycle_id}/child-charges/{child_id}`、一括保存 |
| 園児別請求詳細 | `/billing/cycles/{cycle_id}/child-charges/{child_id}` | 請求項目保存、請求プロフィール保存 |
| 保護者キオスク | `/guardian` | クラス・園児選択、登園、迎え予定確認、降園確認 |
| 迎え予定確認 | `/guardian/child/{child_id}/pickup` | 確定後、キオスクへ |
| 降園確認 | `/guardian/child/{child_id}/check-out` | 確定後、キオスクへ |
| お知らせ管理 | `/notices/` | 新規 `/notices/new`、編集 `/notices/{notice_id}/edit` |
| アンケート管理 | `/surveys/` | 新規 `/surveys/new`、詳細 `/surveys/{survey_id}`、編集 `/surveys/{survey_id}/edit`、回答CSV |
| 保護者アカウント | `/parent-accounts/` | 新規 `/parent-accounts/new`、編集 `/parent-accounts/{account_id}/edit`、保護者として確認 `/parent-portal/mock-login/{account_id}` |
| プロフィール変更申請 | `/child-change-requests` | 詳細 `/child-change-requests/{request_id}`、承認、却下 |
| データ入出力 | `/data-transfers/` | テンプレート取得、エクスポート、インポート確認、インポート確定 |
| カレンダー | `/calendar` | 表示切替 `/calendar/view`、予定作成 `/events/new`、予定詳細 `/events/{event_id}`、予定編集 `/events/{event_id}/edit`、検索 `/search/events` |
| カレンダー設定 | `/calendar` | カレンダー作成、更新、アーカイブ、復元、削除、共有、表示切替 |
| 職員ルーム | `/staff-rooms/` | メッセージ投稿、タイムライン更新、スレッド `/staff-rooms/threads/{parent_message_id}`、添付 `/staff-rooms/attachments/{attachment_id}` |
| 議事録 | `/meeting-notes/` | 新規作成後 `/meeting-notes/{note_id}`、詳細から一覧へ |
| 職員アンケート | `/staff-surveys/` | 回答画面 `/staff-surveys/{survey_id}`、保存後一覧へ |

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
| 保護者ログアウト | `/parent-portal/logout` | `/parent-portal/login` へ |

## 指導計画

| 機能 | 入口 | 主な遷移 |
| --- | --- | --- |
| 指導計画ホーム | `/plans/` | 年案、月案、週案、日案、文例選択、自作文例追加、文書一覧 |
| 年案作成 | `/plans/annual-plans/new` | 保存後 `/plans/documents/{document_id}` |
| 月案作成 | `/plans/monthly-plans/new` | 保存後 `/plans/documents/{document_id}` |
| 週案作成 | `/plans/weekly-plans/new` | 保存後 `/plans/documents/{document_id}` |
| 日案作成 | `/plans/daily-plans/new` | 保存後 `/plans/documents/{document_id}` |
| 文書一覧 | `/plans/documents/` | 詳細 `/plans/documents/{document_id}` |
| 文書詳細 | `/plans/documents/{document_id}` | 編集 `/plans/documents/{document_id}/edit`、ステータス更新 |
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
| ヘルスチェック | `/healthz` |
