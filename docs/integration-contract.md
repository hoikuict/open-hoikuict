# 連携契約

この文書は `hoiku-plan-docs`、`open-hoikuict`、`hoiku-plan-writer` の間で共有する文書作成機能の初期契約です。
キー名、状態名、識別形式は後方互換を維持します。

## 対象範囲

対象は年案・月案・週案・日案・個別指導計画の作成、レビュー、承認、参照です。
年案・月案・週案・日案は本体側の値を安定した識別情報として受け取ります。個別指導計画は園児、日次連絡、出欠、健康記録を参照できます。

## 職員認証

文書作成機能は職員セッションから次の値を受け取ります。

| field | type | required | example | note |
| --- | --- | --- | --- | --- |
| `role` | string | yes | `can_edit` | `view_only` / `can_edit` / `admin` |
| `actor_ref` | string | create/update/status で yes | `staff:00000000-0000-0000-0000-000000000000` | 操作主体の安定ID |
| `nursery_ref` | string | yes | `ひかり保育園` | 園の安定ID |
| `classroom_refs` | string[] | yes | `["5歳児 ひまわり組"]` | 担当クラスの安定ID |
| `name` | string | no | `担任` | 表示用 |

### 権限

| role | can view | can create | can submit | can approve/reject | can archive |
| --- | --- | --- | --- | --- | --- |
| `view_only` | yes | no | no | no | no |
| `can_edit` | yes | yes | yes | no | no |
| `admin` | yes | yes | yes | yes | yes |

`classroom_ref` は文書単位で保存します。`admin` は園内全クラスにアクセス可能です。`view_only` / `can_edit` は `classroom_refs` に含まれる文書だけを扱えます。

## 文書

### 文書種別

外部契約で許可する値は次の通りです。

| document_type | label | note |
| --- | --- | --- |
| `annual_plan` | 年案 | 年間指導計画 |
| `monthly_plan` | 月案 | 月間指導計画 |
| `weekly_plan` | 週案 | 週間指導計画 |
| `daily_plan` | 日案 | 日間指導計画 |
| `individual_plan` | 個別指導計画 | 0・1・2歳児向けの月単位個別計画 |

互換 alias:

| legacy | normalized |
| --- | --- |
| `annual` | `annual_plan` |
| `monthly` | `monthly_plan` |
| `weekly` | `weekly_plan` |
| `daily` | `daily_plan` |
| `individual` | `individual_plan` |

### 状態

| status | label | editable | meaning |
| --- | --- | --- | --- |
| `draft` | 下書き | yes | 作成、編集、再生成できる |
| `in_review` | レビュー待ち | limited | 承認者確認中 |
| `approved` | 承認済み | no | 正式版 |
| `rejected` | 差戻し | yes | 修正が必要 |
| `archived` | アーカイブ | no | 旧版参照専用 |

互換 alias:

| legacy | normalized |
| --- | --- |
| `returned` | `rejected` |

### 最小データ形

```json
{
  "id": 1,
  "document_type": "annual_plan",
  "status": "draft",
  "title": "2026年度 年案（5歳児 ひまわり組）",
  "nursery_ref": "ひかり保育園",
  "classroom_ref": "5歳児 ひまわり組",
  "actor_ref": "職員:担任",
  "school_year": 2026,
  "target_month": null,
  "target_week": null,
  "week_start_date": null,
  "target_date": null,
  "age_class": null,
  "child_ref": null,
  "child_name": null,
  "parent_document_id": null,
  "related_document_ids": [],
  "sections": [
    {
      "section_key": "annual_goal",
      "title": "年間の大きなねらい",
      "body": "...",
      "source_refs": ["profile.childcare_goal", "form.focus_growth"],
      "evidence_tags": ["園方針", "入力"],
      "needs_confirmation": false,
      "editor_note": null
    }
  ],
  "schedule": {
    "layout": "daily_timeline",
    "columns": [{"key": "env", "title": "環境構成"}],
    "rows": [
      {
        "row_key": "t_main",
        "label": "主な活動",
        "order": 40,
        "start_time": "10:15",
        "cells": {
          "env": {
            "body": "...",
            "source_refs": ["form.schedule"],
            "evidence_tags": ["入力"],
            "needs_confirmation": false
          }
        }
      }
    ]
  },
  "confirmation_items": []
}
```

`target_week` / `week_start_date` / `target_date` / `age_class` / `child_ref` / `child_name` / `parent_document_id` / `related_document_ids` / `schedule` は追加フィールドです。年案・月案では省略されることがあります。週案・日案では `schedule` を持ち、`layout`、`columns[].key`、`rows[].row_key` は永続契約です。`individual_plan` では `child_ref` が必須です。

`child_ref` は `child:{children.id}` 形式です。アルファ段階の単一園・単一 SQLite では `children.id` を安定識別子として扱います。園児マスタに外部 ID が導入された場合は互換 alias または migration を用意します。

## セクションキー

`section_key` は永続識別子です。表示ラベルや帳票レイアウトが変わっても変更しません。

### 年案

| section_key | title |
| --- | --- |
| `annual_goal` | 年間の大きなねらい |
| `term_1_outlook` | 4〜6月の見通し |
| `term_1_environment` | 4〜6月の環境構成 |
| `term_1_support` | 4〜6月の援助 |
| `term_1_family_collaboration` | 4〜6月の家庭連携 |
| `term_1_reflection_viewpoint` | 4〜6月の振り返り観点 |
| `term_2_outlook` | 7〜9月の見通し |
| `term_2_environment` | 7〜9月の環境構成 |
| `term_2_support` | 7〜9月の援助 |
| `term_2_family_collaboration` | 7〜9月の家庭連携 |
| `term_2_reflection_viewpoint` | 7〜9月の振り返り観点 |
| `term_3_outlook` | 10〜12月の見通し |
| `term_3_environment` | 10〜12月の環境構成 |
| `term_3_support` | 10〜12月の援助 |
| `term_3_family_collaboration` | 10〜12月の家庭連携 |
| `term_3_reflection_viewpoint` | 10〜12月の振り返り観点 |
| `term_4_outlook` | 1〜3月の見通し |
| `term_4_environment` | 1〜3月の環境構成 |
| `term_4_support` | 1〜3月の援助 |
| `term_4_family_collaboration` | 1〜3月の家庭連携 |
| `term_4_reflection_viewpoint` | 1〜3月の振り返り観点 |

### 月案

| section_key | title |
| --- | --- |
| `monthly_goal` | 今月のねらい |
| `children_snapshot` | 子どもの姿の捉え |
| `monthly_environment` | 環境構成 |
| `monthly_support` | 援助 |
| `monthly_health_safety` | 健康・安全への配慮 |
| `monthly_food_education` | 食育 |
| `monthly_events` | 行事 |
| `monthly_10_perspectives` | 10の姿 |
| `monthly_family_collaboration` | 家庭連携 |
| `monthly_reflection_viewpoint` | 月末の振り返り観点 |

### 週案

| section_key | title |
| --- | --- |
| `weekly_goal` | 今週のねらい |
| `weekly_children_snapshot` | 前週の子どもの姿 |
| `weekly_activities` | 主な活動・経験 |
| `weekly_environment` | 環境構成 |
| `weekly_support` | 保育者の援助・配慮 |
| `weekly_health_safety` | 健康・安全への配慮 |
| `weekly_family_collaboration` | 家庭連携 |
| `weekly_reflection_viewpoint` | 週の評価・反省 |

### 日案

| section_key | title |
| --- | --- |
| `daily_goal` | 本日のねらい |
| `daily_children_snapshot` | 前日までの子どもの姿 |
| `daily_main_activity` | 主な活動 |
| `daily_health_safety` | 健康・安全への配慮 |
| `daily_food_education` | 食育 |
| `daily_family_collaboration` | 家庭連携 |
| `daily_reflection_viewpoint` | 本日の評価・反省 |

### 個別指導計画

| section_key | title |
| --- | --- |
| `individual_children_snapshot` | 前月までの子どもの姿 |
| `individual_goal_care` | 養護のねらい |
| `individual_goal_education` | 教育のねらい |
| `individual_life_rhythm` | 生活リズム（食事・睡眠・排泄・遊び） |
| `individual_environment_support` | 環境構成・援助 |
| `individual_family_collaboration` | 家庭との連携 |
| `individual_reflection_viewpoint` | 評価・反省 |

## schedule 契約

週案・日案は表形式の `schedule` を持ちます。本文セクションと同様に、`layout`、`column.key`、`row_key` は表示ラベルが変わっても変更しない永続識別子です。

| layout | document_type | column.key |
| --- | --- | --- |
| `weekly_grid` | `weekly_plan` | `activity` / `support` |
| `daily_timeline` | `daily_plan` | `env` / `children` / `support` |

週案の `row_key` は `mon` / `tue` / `wed` / `thu` / `fri` / `sat`、日案の `row_key` は `t_arrival` / `t_free_am` / `t_meeting` / `t_main` / `t_lunch` / `t_nap` / `t_free_pm` / `t_departure` などを使います。0〜2歳児では `t_care_am` / `t_care_pm` など個別の生活リズムに関する行を含みます。

## 根拠情報と表示タグ

`source_refs` は文字列配列です。prefix から表示タグを再計算します。

| prefix | evidence tag |
| --- | --- |
| `profile.*` | `園方針` |
| `knowledge.*` | `公的根拠` |
| `form.*` | `入力` |
| `annual.*` | `入力` |
| `monthly.*` | `入力` |
| `weekly.*` | `入力` |
| `daily.*` | `入力` |
| `individual.*` | `入力` |
| `bunrei.*` | `文例` |
| `facility.*` | `園文例` |
| `record.daily_contact:*` | `記録` |
| `record.attendance:*` | `記録` |
| `record.health_check:*` | `記録` |
| `outline.*` | `AI構成` |
| `linking.*` | `AI構成` |

各 section は最低 1 つ以上の `source_refs` と `evidence_tags` を持ちます。

### 記録連動

個別指導計画では、記録本文を自動転記せず、根拠ポインタとして `source_refs` に保存します。

| prefix | 形式 | 参照先 |
| --- | --- | --- |
| `record.daily_contact` | `record.daily_contact:{id}` | `daily_contact_entries` |
| `record.attendance` | `record.attendance:{child_id}:{YYYY-MM}` | 月次出欠集計 |
| `record.health_check` | `record.health_check:{id}` | `health_check_records` |

参照先が削除済みの場合、表示時に「参照先なし」として扱い、文書 JSON は壊しません。

### 文例DB

共通文例は `bunrei.*`、園文例は `facility.*` として根拠に残します。園文例は `nursery_ref` で必ず絞り込み、他園の候補として返しません。園文例の `masked` は自動マスクの有無であり、人による確認を省略する根拠にはしません。

園文例は画面から 1 件ずつ追加するほか、CSV・Excel（.xlsx）でまとめて取り込みます。取り込み列は `計画種別`、`年齢`、`月`、`項目`、`領域・観点`、`出所メモ`、`本文` を基本形とし、英語列名 `plan_type`、`age_class`、`month`、`item`、`ryoiki`、`source_note`、`text` も受け付けます。取り込み画面はこの基本形の空CSV・空Excelを配布します。取り込み時も `nursery_ref` は現在の職員セッションから固定し、利用者入力では上書きしません。

## 承認ログ

将来の永続化では最低限次を保存します。

| field | type |
| --- | --- |
| `document_id` | int or uuid |
| `document_type` | string |
| `action` | string |
| `comment` | string |
| `actor_ref` | string |
| `created_at` | datetime |

`action` は `submit`、`approve`、`reject`、`archive` のみ許可します。

## API 境界

初期実装では画面操作を優先し、JSON API は参照のみです。

| method | path | auth | purpose |
| --- | --- | --- | --- |
| `GET` | `/healthz` | none | 稼働確認 |
| `GET` | `/plans/api/documents/{document_id}` | staff | 文書 JSON 参照 |

後続で `POST /api/annual-plans`、`POST /api/monthly-plans`、`PATCH /api/documents/{id}/status` を追加する場合も、この contract の値だけを受け付けます。

## 破壊的変更の扱い

以下は破壊的変更です。

- 既存 `document_type` の削除または意味変更
- 既存 `status` の削除または意味変更
- 既存 `section_key` の削除または意味変更
- 既存 `schedule.layout`、`schedule.columns[].key`、`schedule.rows[].row_key` の削除または意味変更
- `source_refs` prefix ルールの変更
- `actor_ref`、`nursery_ref`、`classroom_ref` の意味変更

破壊的変更が必要な場合は、ADR、migration 方針、互換レイヤを同時に用意します。
