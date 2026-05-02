# open-hoikuict 請求・徴収・Zenginフォーマット出力機能 仕様書

## 1. 概要

### 1.1 目的

`open-hoikuict` に、保育施設で発生する月次の請求・徴収業務を管理する機能を追加する。

本機能では、延長保育料金、給食費、教材費、写真代、行事費、その他費用を家族単位または園児単位で集計し、請求を確定したうえで、保護者口座からの口座振替に必要な **Zengin／全銀フォーマットの預金口座振替依頼ファイル** を作成できるようにする。

### 1.2 対象とするZenginフォーマット

本仕様では、Zenginフォーマットのうち、園が保護者から費用を徴収する用途を想定し、以下を対象とする。

| 項目 | 内容 |
|---|---|
| 用途 | 預金口座振替依頼 |
| 種別コード | `91` |
| レコード長 | 120バイト固定長 |
| レコード構成 | ヘッダー、データ、トレーラー、エンド |
| 文字コード | 初期値 `cp932`。金融機関仕様により変更可能 |
| 改行 | `CRLF` または改行なしを設定可能 |

> 注意: 金融機関や収納代行会社によって、細部のフォーマット、改行有無、文字コード、ファイル名、提出期限、許容文字が異なる場合がある。実装時には利用予定の金融機関仕様書に合わせて調整する。

---

## 2. 背景

保育施設では、毎月以下のような費用徴収作業が発生する。

- 延長保育利用料
- 給食費
- おやつ代
- 教材費
- 写真代
- 行事費
- 用品代
- 調整額、返金、減免

これらを手作業で集計し、銀行指定の口座振替データを作成する作業は負荷が高く、入力ミスや請求漏れが発生しやすい。

`open-hoikuict` に請求・徴収管理機能を追加することで、登降園記録や園児・家族情報と連携し、月次請求から口座振替ファイル作成、振替結果管理までを一貫して処理できるようにする。

---

## 3. 実装範囲

### 3.1 MVPで実装する範囲

| 機能 | 内容 |
|---|---|
| 請求月管理 | 対象月、対象期間、引落日、支払期限を管理する |
| 請求候補生成 | 登降園記録や料金ルールから請求明細を自動生成する |
| 延長料金計算 | 降園時刻をもとに延長料金を算出する |
| 給食費計算 | 月額固定または出席日数連動で給食費を算出する |
| その他費用登録 | 教材費、写真代、行事費などを手動登録する |
| 請求確定 | 家族単位の請求額を確定する |
| 口座情報管理 | 家族ごとの口座振替情報を管理する |
| Zenginファイル作成 | 確定済み請求から預金口座振替依頼ファイルを作成する |
| 振替結果取込 | 銀行から取得した結果ファイルを取り込み、入金状態を更新する |
| 権限制御 | 閲覧、編集、管理者権限に応じて操作を制限する |
| CSV出力 | 請求一覧、請求明細、振替対象一覧、振替結果を出力する |

### 3.2 MVPでは実装しない範囲

| 機能 | 扱い |
|---|---|
| 銀行API連携 | 対象外。ファイルダウンロードのみ対応 |
| 請求書PDF | 将来対応 |
| 領収書PDF | 将来対応 |
| 会計ソフト連携 | 将来対応 |
| クレジットカード決済 | 対象外 |
| コンビニ決済 | 対象外 |
| 自動督促 | 将来対応 |
| 複数施設横断請求 | 将来対応 |

---

## 4. 業務フロー

### 4.1 月次請求フロー

```text
請求月作成
  ↓
延長料金・給食費の自動計算
  ↓
その他費用の手動登録
  ↓
請求明細確認
  ↓
請求確定
  ↓
Zenginファイル作成
  ↓
金融機関または収納代行サービスへ提出
  ↓
振替結果ファイル取得
  ↓
振替結果取込
  ↓
入金済み・振替不能の管理
```

### 4.2 請求作成の流れ

1. 管理者または編集権限を持つ職員が請求月を作成する。
2. 対象期間、引落日、支払期限を設定する。
3. システムが対象園児・家族を抽出する。
4. 登降園記録をもとに延長料金を計算する。
5. 給食費ルールをもとに給食費を計算する。
6. 職員がその他費用を追加する。
7. 家族単位で請求額を確認する。
8. 請求を確定する。
9. 確定済み請求のみZengin出力対象とする。

---

## 5. 権限仕様

既存の認証ロールに合わせ、以下の権限制御を行う。

| 操作 | view_only | can_edit | admin |
|---|---:|---:|---:|
| 請求一覧閲覧 | ○ | ○ | ○ |
| 請求詳細閲覧 | ○ | ○ | ○ |
| 請求月作成 | × | ○ | ○ |
| 請求候補生成 | × | ○ | ○ |
| 手動費用登録 | × | ○ | ○ |
| 請求明細編集 | × | ○ | ○ |
| 請求確定 | × | ○ | ○ |
| 請求確定取消 | × | × | ○ |
| Zenginファイル作成 | × | ○ | ○ |
| Zenginファイル再出力 | × | × | ○ |
| 振替結果取込 | × | ○ | ○ |
| 口座情報閲覧 | × | ○ | ○ |
| 口座情報編集 | × | ○ | ○ |
| 請求設定編集 | × | × | ○ |
| 料金ルール編集 | × | × | ○ |

---

## 6. 画面仕様

### 6.1 追加メニュー

`/billing` 配下に請求・徴収機能を追加する。

| URL | 画面名 | 概要 |
|---|---|---|
| `/billing/` | 請求ダッシュボード | 当月請求、未確定、未入金、振替不能件数を表示 |
| `/billing/cycles` | 請求月一覧 | 月ごとの請求状態を表示 |
| `/billing/cycles/new` | 請求月作成 | 対象月、期間、引落日を登録 |
| `/billing/cycles/{cycle_id}` | 請求月詳細 | 家族別請求一覧、合計金額、状態を表示 |
| `/billing/cycles/{cycle_id}/generate` | 請求候補生成 | 延長料金・給食費を自動計算 |
| `/billing/claims/{claim_id}` | 請求詳細 | 家族単位の請求明細を表示 |
| `/billing/manual-charges/new` | その他費用登録 | 写真代、教材費、行事費などを登録 |
| `/billing/zengin/{cycle_id}` | Zengin出力 | 出力対象確認、エラー確認、ファイル作成 |
| `/billing/payment-results` | 振替結果取込 | 結果ファイルをアップロードし反映 |
| `/billing/settings` | 請求設定 | 施設口座、委託者情報、料金ルールを管理 |

### 6.2 家族画面への追加

家族詳細または家族編集画面に「請求・口座情報」セクションを追加する。

#### 表示項目

| 項目 | 内容 |
|---|---|
| 支払方法 | 口座振替、現金、銀行振込、免除 |
| 口座振替状態 | 未設定、依頼書回収済、利用中、停止中 |
| 銀行コード | 4桁 |
| 銀行名カナ | 半角カナ15バイト以内 |
| 支店コード | 3桁 |
| 支店名カナ | 半角カナ15バイト以内 |
| 預金種目 | 保護者引落口座の種目。普通、当座、納税準備、その他 |
| 口座番号 | 7桁以内。Zengin出力時は前ゼロ補完 |
| 口座名義カナ | 半角カナ30バイト以内 |
| 顧客番号 | 20桁数字。施設コード3桁 + 家族ID17桁を自動採番 |
| 新規コード | 0: その他、1: 初回、2: 変更 |
| 依頼書回収日 | 任意 |
| 備考 | 任意 |

#### 表示制御

| 項目 | 仕様 |
|---|---|
| 口座番号 | 一覧・詳細ではマスク表示。例: `****1234` |
| 口座名義 | 編集権限以上のみ表示 |
| 口座情報編集 | `can_edit` または `admin` のみ可能 |
| 口座情報のログ出力 | 禁止 |

---

## 7. データモデル仕様

### 7.1 BillingSetting

施設単位の請求・口座振替設定を保持する。

| カラム | 型 | 必須 | 説明 |
|---|---|---:|---|
| id | int | ○ | 主キー |
| facility_name | str | ○ | 園名 |
| collector_code | str | ○ | 委託者コード、10桁 |
| collector_name_kana | str | ○ | 委託者名、40バイト以内 |
| customer_number_facility_code | str | ○ | 顧客番号の先頭3桁。単一施設の場合は `000` を初期値とする |
| withdrawal_bank_code | str | ○ | 取引銀行番号、4桁 |
| withdrawal_bank_name_kana | str | 任意 | 取引銀行名、15バイト以内 |
| withdrawal_branch_code | str | ○ | 取引支店番号、3桁 |
| withdrawal_branch_name_kana | str | 任意 | 取引支店名、15バイト以内 |
| collector_account_type | str | ○ | 施設側の委託者口座種目。1: 普通、2: 当座、9: その他 |
| collector_account_number | str | ○ | 委託者口座番号、7桁以内。出力時は前ゼロ補完 |
| code_type | str | ○ | 原則 `0` |
| file_encoding | str | ○ | 初期値 `cp932` |
| line_separator | str | ○ | `CRLF` または `NONE` |
| content_hash_algorithm | str | ○ | 初期値 `sha256` |
| created_at | datetime | ○ | 作成日時 |
| updated_at | datetime | ○ | 更新日時 |

#### 預金種目コードの整理

施設側の委託者口座と、保護者側の引落口座では、許可する預金種目を分けて扱う。

| 対象 | カラム | Zengin上の項目 | MVPでの許可値 |
|---|---|---|---|
| 施設側 | `BillingSetting.collector_account_type` | ヘッダーレコードの預金種目 | `1`: 普通、`2`: 当座、`9`: その他 |
| 保護者側 | `FamilyBillingProfile.account_type` | データレコードの預金種目 | `1`: 普通、`2`: 当座、`3`: 納税準備、`9`: その他 |

`3: 納税準備` はデータレコード側、つまり引落対象口座側の選択肢としてのみ許可する。施設側の委託者口座ではMVPでは許可しない。金融機関の仕様書で施設側にも `3` が明示されている場合のみ、施設設定で許可値を拡張する。

### 7.2 FamilyBillingProfile

家族ごとの請求・口座振替情報を保持する。

| カラム | 型 | 必須 | 説明 |
|---|---|---:|---|
| id | int | ○ | 主キー |
| family_id | int | ○ | 家族ID。ユニーク |
| payment_method | str | ○ | `direct_debit`, `cash`, `bank_transfer`, `exempt` |
| direct_debit_status | str | ○ | `not_set`, `paper_received`, `active`, `suspended` |
| bank_code | str | 条件付き | 引落銀行番号、4桁 |
| bank_name_kana | str | 任意 | 引落銀行名、15バイト以内 |
| branch_code | str | 条件付き | 引落支店番号、3桁 |
| branch_name_kana | str | 任意 | 引落支店名、15バイト以内 |
| account_type | str | 条件付き | 保護者側の引落口座種目。1: 普通、2: 当座、3: 納税準備、9: その他 |
| account_number | str | 条件付き | 口座番号、7桁以内 |
| account_holder_kana | str | 条件付き | 預金者名、30バイト以内 |
| customer_number | str | ○ | 顧客番号。20桁数字。施設コード3桁 + 家族ID17桁 |
| new_code | str | ○ | 0: その他、1: 初回、2: 変更 |
| mandate_received_on | date | 任意 | 口座振替依頼書回収日 |
| note | str | 任意 | 備考 |
| created_at | datetime | ○ | 作成日時 |
| updated_at | datetime | ○ | 更新日時 |

#### 顧客番号の採番仕様

顧客番号はZenginデータレコード上ではC項目だが、MVPでは照合しやすさを優先し、システム採番値を **20桁数字固定** とする。

```text
顧客番号 = customer_number_facility_code 3桁 + family_id 17桁ゼロ埋め
```

例:

```text
customer_number_facility_code = 001
family_id = 123
customer_number = 00100000000000000123
```

| 項目 | 仕様 |
|---|---|
| 桁数 | 常に20桁 |
| 文字種 | 数字のみ |
| 施設コード | `BillingSetting.customer_number_facility_code` を使用。単一施設では `000` を初期値とする |
| 家族ID | `family_id` を17桁で前ゼロ埋め |
| 一意性 | `FamilyBillingProfile.customer_number` はユニーク |
| 変更 | 原則変更不可。変更が必要な場合は管理者のみ可能 |
| 複数施設対応 | 将来、施設ごとに3桁コードを割り当てることで同一family_id衝突を避ける |

顧客番号には請求IDを含めない。毎月の請求結果照合は、選択された `ZenginExport` と `customer_number` の組み合わせで行う。これにより、金融機関・収納代行会社側で顧客番号を保護者口座の固定識別子として扱う場合にも対応しやすくする。

### 7.3 FeeItem

費目マスタを保持する。

| カラム | 型 | 必須 | 説明 |
|---|---|---:|---|
| id | int | ○ | 主キー |
| code | str | ○ | `extension`, `meal`, `photo`, `material` など |
| name | str | ○ | 費目名 |
| category | str | ○ | `extension`, `meal`, `other`, `adjustment` |
| charge_unit | str | ○ | `child` または `family` |
| default_amount | int | 任意 | 標準単価 |
| taxable_type | str | ○ | `non_taxable`, `taxable`, `out_of_scope` |
| is_active | bool | ○ | 有効フラグ |
| display_order | int | ○ | 表示順 |
| created_at | datetime | ○ | 作成日時 |
| updated_at | datetime | ○ | 更新日時 |

### 7.4 ExtensionFeeRule

延長料金の計算ルールを保持する。

| カラム | 型 | 必須 | 説明 |
|---|---|---:|---|
| id | int | ○ | 主キー |
| name | str | ○ | ルール名 |
| valid_from | date | ○ | 適用開始日 |
| valid_to | date | 任意 | 適用終了日 |
| base_end_time | str | ○ | 通常保育終了時刻。例: `18:00` |
| grace_minutes | int | ○ | 猶予分 |
| unit_minutes | int | ○ | 課金単位分。例: 30 |
| amount_per_unit | int | ○ | 1単位あたり金額 |
| rounding_mode | str | ○ | 初期値 `ceil` |
| max_daily_amount | int | 任意 | 日別上限 |
| max_monthly_amount | int | 任意 | 月別上限 |
| created_at | datetime | ○ | 作成日時 |
| updated_at | datetime | ○ | 更新日時 |

### 7.5 MealFeeRule

給食費の計算ルールを保持する。

| カラム | 型 | 必須 | 説明 |
|---|---|---:|---|
| id | int | ○ | 主キー |
| name | str | ○ | ルール名 |
| calculation_type | str | ○ | `monthly_fixed`, `attendance_count`, `manual` |
| monthly_amount | int | 任意 | 月額固定金額 |
| unit_amount | int | 任意 | 1食あたり金額 |
| count_source | str | 任意 | `attendance_check_in`, `daily_contact_present`, `attendance_verification_present`, `verification_then_check_in`, `manual` |
| proration_policy | str | ○ | 月途中入退園時の扱い。`none`, `daily_by_enrolled_days`, `manual_adjustment` |
| proration_rounding | str | ○ | 日割り時の丸め。`round`, `floor`, `ceil`。初期値 `round` |
| valid_from | date | ○ | 適用開始日 |
| valid_to | date | 任意 | 適用終了日 |
| created_at | datetime | ○ | 作成日時 |
| updated_at | datetime | ○ | 更新日時 |

#### 月途中入退園の扱い

月額固定の給食費では、施設ごとの運用差を吸収するため `proration_policy` で扱いを決定する。

| `proration_policy` | 内容 |
|---|---|
| `none` | 日割りしない。対象期間中に1日でも在籍していれば月額全額を請求する。MVPの初期値 |
| `daily_by_enrolled_days` | `monthly_amount × 在籍日数 ÷ 対象期間日数` で日割り計算する |
| `manual_adjustment` | 自動日割りせず、職員が調整明細を登録する |

在籍日数は `Child.enrollment_date <= 対象日` かつ `withdrawal_date IS NULL または 対象日 <= Child.withdrawal_date` を満たす日数とする。

### 7.6 BillingCycle

月次請求サイクルを保持する。

| カラム | 型 | 必須 | 説明 |
|---|---|---:|---|
| id | int | ○ | 主キー |
| year_month | str | ○ | 請求月。例: `2026-04` |
| period_start | date | ○ | 対象期間開始日 |
| period_end | date | ○ | 対象期間終了日 |
| withdrawal_date | date | ○ | 引落日 |
| due_date | date | 任意 | 支払期限 |
| status | str | ○ | `draft`, `generated`, `confirmed`, `exported`, `result_imported`, `closed` |
| generated_at | datetime | 任意 | 生成日時 |
| confirmed_at | datetime | 任意 | 確定日時 |
| confirmed_by | str | 任意 | 確定者 |
| created_at | datetime | ○ | 作成日時 |
| updated_at | datetime | ○ | 更新日時 |

#### 制約

| 制約 | 内容 |
|---|---|
| `year_month` ユニーク | 同一請求月の二重作成を禁止する |
| 確定可能状態 | `confirm_cycle` は `generated` 状態のサイクルにのみ許可する |
| 出力可能状態 | Zengin出力は `confirmed` 状態のサイクルにのみ許可する |

### 7.7 BillingClaim

家族単位の請求を保持する。

| カラム | 型 | 必須 | 説明 |
|---|---|---:|---|
| id | int | ○ | 主キー |
| billing_cycle_id | int | ○ | 請求月ID |
| family_id | int | ○ | 家族ID |
| payment_method | str | ○ | 請求時点の支払方法 |
| total_amount | int | ○ | 請求合計金額 |
| status | str | ○ | `draft`, `confirmed`, `exported`, `paid`, `failed`, `exempted`, `canceled` |
| zengin_export_id | int | 任意 | Zengin出力ID |
| exported_at | datetime | 任意 | 出力日時 |
| result_code | str | 任意 | 振替結果コード |
| paid_at | datetime | 任意 | 入金日時 |
| failed_reason | str | 任意 | 振替不能理由 |
| carried_over_to_claim_id | int | 任意 | 振替不能分を翌月以降に繰り越した場合の繰越先請求ID |
| created_at | datetime | ○ | 作成日時 |
| updated_at | datetime | ○ | 更新日時 |

#### 免除家族の扱い

`FamilyBillingProfile.payment_method = exempt` の家族は、請求候補生成時にスキップせず、監査・一覧表示のため `BillingClaim` を作成する。

| 項目 | 値 |
|---|---|
| `payment_method` | `exempt` |
| `total_amount` | `0` |
| `status` | `exempted` |
| 明細 | 原則作成しない。必要に応じて金額0円のメモ明細を許可 |
| Zengin出力 | 対象外 |

これにより、請求月の一覧で「なぜ請求がないのか」を確認できるようにする。

### 7.8 BillingChargeLine

請求明細を保持する。

| カラム | 型 | 必須 | 説明 |
|---|---|---:|---|
| id | int | ○ | 主キー |
| billing_claim_id | int | ○ | 請求ID |
| fee_item_id | int | ○ | 費目ID |
| child_id | int | 任意 | 園児ID。家族単位費用の場合はNULL |
| source_type | str | ○ | `extension_auto`, `meal_auto`, `manual`, `adjustment`, `carryover` |
| source_date | date | 任意 | 発生日 |
| source_claim_id | int | 任意 | 繰越明細の場合の元請求ID |
| description | str | ○ | 明細説明 |
| quantity | int | ○ | 数量 |
| unit_label | str | 任意 | `回`, `食`, `月`, `式` など |
| unit_price | int | ○ | 単価 |
| amount | int | ○ | 金額 |
| is_locked | bool | ○ | 確定済みロック |
| created_at | datetime | ○ | 作成日時 |
| updated_at | datetime | ○ | 更新日時 |

### 7.9 ZenginExport

Zenginファイル出力履歴を保持する。

| カラム | 型 | 必須 | 説明 |
|---|---|---:|---|
| id | int | ○ | 主キー |
| billing_cycle_id | int | ○ | 請求月ID |
| withdrawal_date | date | ○ | 引落日 |
| file_name | str | ○ | ファイル名 |
| total_count | int | ○ | データ件数 |
| total_amount | int | ○ | 合計金額 |
| status | str | ○ | `created`, `downloaded`, `reissued`, `canceled` |
| content_hash | str | ○ | 出力ファイルバイト列のSHA-256ハッシュ、16進文字列 |
| settings_snapshot | dict | ○ | 出力時の施設設定 |
| created_by | str | ○ | 作成者 |
| created_at | datetime | ○ | 作成日時 |

`content_hash` は、利用者がダウンロードする実際のファイルバイト列に対して以下で計算する。

```python
import hashlib

content_hash = hashlib.sha256(file_bytes).hexdigest()
```

`line_separator = CRLF` の場合は、CRLFを含めた `file_bytes` をハッシュ対象にする。`line_separator = NONE` の場合は、120バイト固定長レコードの連結バイト列をハッシュ対象にする。

### 7.10 ZenginExportLine

Zengin出力対象の明細を保持する。

| カラム | 型 | 必須 | 説明 |
|---|---|---:|---|
| id | int | ○ | 主キー |
| zengin_export_id | int | ○ | Zengin出力ID |
| billing_claim_id | int | ○ | 請求ID |
| family_id | int | ○ | 家族ID |
| customer_number | str | ○ | 顧客番号 |
| amount | int | ○ | 引落金額 |
| bank_snapshot | dict | ○ | 出力時の口座情報 |
| result_code | str | 任意 | 振替結果コード |
| created_at | datetime | ○ | 作成日時 |

---

## 8. 請求計算仕様

### 8.1 延長料金

#### 8.1.1 入力情報

延長料金は、園児ごとの登降園記録をもとに計算する。

| 入力 | 内容 |
|---|---|
| 園児ID | 対象園児 |
| 登降園日 | 対象期間内の日付 |
| 降園時刻 | 延長判定に使用 |
| 通常保育終了時刻 | 料金ルールで設定 |
| 猶予時間 | 料金ルールで設定 |
| 課金単位 | 料金ルールで設定 |
| 単価 | 料金ルールで設定 |

#### 8.1.2 計算式

```text
基準時刻 = 通常保育終了時刻 + 猶予時間
超過分 = 降園時刻 - 基準時刻

超過分 <= 0 の場合:
  延長料金 = 0円

超過分 > 0 の場合:
  課金単位数 = ceil(超過分 / 課金単位分)
  延長料金 = 課金単位数 × 単価
```

#### 8.1.3 計算例

設定:

| 項目 | 値 |
|---|---:|
| 通常保育終了 | 18:00 |
| 猶予 | 0分 |
| 課金単位 | 30分 |
| 単価 | 300円 |

| 降園時刻 | 超過分 | 課金単位数 | 請求額 |
|---|---:|---:|---:|
| 18:00 | 0分 | 0 | 0円 |
| 18:01 | 1分 | 1 | 300円 |
| 18:30 | 30分 | 1 | 300円 |
| 18:31 | 31分 | 2 | 600円 |
| 19:00 | 60分 | 2 | 600円 |

#### 8.1.4 対象外条件

以下の記録は自動計算対象外とする。

| 条件 | 理由 |
|---|---|
| 降園時刻が未入力 | 延長判定できないため |
| 登降園記録が削除済み | 無効データのため |
| 手動除外フラグあり | 職員判断で対象外にするため |
| 園児が請求対象外 | 退園済み、免除など |

### 8.2 給食費

給食費は施設ごとの運用差が大きいため、以下の方式を選択可能にする。

| 方式 | 内容 |
|---|---|
| 月額固定 | 対象月に在籍していれば固定額を請求する |
| 出席日数連動 | 出席日数 × 単価で請求する |
| 手動 | 自動計算せず、職員が登録する |

#### 8.2.1 月額固定

```text
給食費 = 月額固定金額
```

月途中入退園の場合は `MealFeeRule.proration_policy` に従う。

| `proration_policy` | 計算 |
|---|---|
| `none` | 月額固定金額をそのまま請求 |
| `daily_by_enrolled_days` | `monthly_amount × 在籍日数 ÷ 対象期間日数` |
| `manual_adjustment` | 月額固定金額を自動計算した後、必要に応じて職員が調整明細を登録 |

#### 8.2.2 出席日数連動

```text
給食費 = 出席日数 × 1食単価
```

出席日の判定は `MealFeeRule.count_source` で選択する。

| `count_source` | 判定 |
|---|---|
| `attendance_check_in` | `AttendanceRecord.check_in_at` が入力されている日を出席扱いとする |
| `daily_contact_present` | `DailyContactEntry.contact_type = present` の日を出席扱いとする |
| `attendance_verification_present` | `AttendanceVerification.status = present` の日を出席扱いとする |
| `verification_then_check_in` | 職員確認を優先する。`AttendanceVerification.status = present` は出席、`private_absent` または `sick_absent` は欠席、`unknown` または確認レコードなしの場合のみ `AttendanceRecord.check_in_at` にフォールバックする |
| `manual` | 職員が食数を入力する |

MVPの推奨初期値は `verification_then_check_in` とする。これにより、登園打刻が漏れていても職員が出席確認した日は給食費に含められる。一方で、職員が欠席確認した日は、保護者連絡や打刻データと矛盾していても欠席を優先する。

#### 8.2.3 出席判定の優先順位

`verification_then_check_in` の判定順序は以下とする。

```text
1. AttendanceVerification.status が present の場合
   → 出席

2. AttendanceVerification.status が private_absent または sick_absent の場合
   → 欠席

3. AttendanceVerification.status が unknown、または確認レコードがない場合
   → AttendanceRecord.check_in_at があれば出席、なければ欠席
```

`DailyContactEntry` は保護者申告であり、実績確認ではないため、MVPでは職員確認より優先しない。`daily_contact_present` を選んだ場合のみ、保護者連絡を食数計算の直接ソースとして扱う。

### 8.3 その他費用

その他費用は、手動登録を基本とする。

| 種別 | 例 |
|---|---|
| 写真代 | 写真購入代 |
| 教材費 | のり、はさみ、絵本など |
| 行事費 | 遠足、発表会、卒園関連 |
| 用品代 | 帽子、スモック、連絡帳など |
| 調整 | 返金、減免、端数調整 |

#### 登録方式

| 方式 | 内容 |
|---|---|
| 個別登録 | 家族または園児を指定して登録 |
| 一括登録 | クラス、園児一覧、CSVなどから登録 |
| マイナス明細 | 返金・減免として負数登録を許可 |
| 金額0円明細 | 備考用途として許可するか設定可能 |

### 8.4 免除・請求対象外の扱い

| 条件 | 請求候補生成時の扱い | Zengin出力 |
|---|---|---|
| `payment_method = exempt` | `total_amount = 0`, `status = exempted` の請求を作成する | 対象外 |
| 在籍期間外の園児 | 園児単位明細を作成しない | 対象外 |
| 退園済みだが対象期間内に在籍日がある園児 | 対象期間内の在籍日に限って計算する | 支払方法により判定 |
| 請求額0円以下 | 請求は保持するが口座振替対象外 | 対象外 |

免除家族を完全にスキップすると、月次一覧で「請求対象外なのか、設定漏れなのか」が判別しにくくなるため、MVPでは0円請求として明示的に生成する。

---

## 9. 請求状態遷移

### 9.1 BillingCycle

```text
draft
  ↓ generate
generated
  ↓ confirm
confirmed
  ↓ export_zengin
exported
  ↓ import_result
result_imported
  ↓ close
closed
```

### 9.2 BillingClaim

```text
draft
  ↓ confirm
confirmed
  ↓ export_zengin
exported
  ↓ result success
paid

exported
  ↓ result failed
failed
  ↓ carry_over_to_next_cycle
failed  ※元請求はfailedのまま、carried_over_to_claim_idを設定

payment_method = exempt
  ↓ generate
exempted

draft / confirmed
  ↓ cancel
canceled
```

免除請求は `exempted` として生成し、確定・Zengin出力の対象にはしない。


### 9.3 ロック仕様

| 状態 | 明細変更 | 口座情報の請求反映 | Zengin出力 |
|---|---:|---:|---:|
| draft | ○ | ○ | × |
| generated | ○ | ○ | × |
| confirmed | × | スナップショット固定 | ○ |
| exported | × | スナップショット固定 | 再出力のみ |
| paid | × | × | × |
| failed | × | × | ×。翌月繰越操作のみ可 |
| exempted | × | × | × |
| canceled | × | × | × |

---

## 10. Zenginファイル仕様

### 10.1 レコード構成

```text
ヘッダーレコード   1件
データレコード     1件以上
トレーラーレコード 1件
エンドレコード     1件
```

各レコードは120バイト固定長とする。

### 10.2 共通ルール

| 属性 | 仕様 |
|---|---|
| N項目 | 数字。右詰め、前ゼロ埋め |
| C項目 | 許容文字のみ。左詰め、後ろスペース埋め |
| ダミー | スペース埋め |
| 金額 | 円単位、カンマなし |
| 日付 | 引落日は `MMDD` |
| レコード長 | エンコード後120バイト |
| 出力文字 | 半角カナ、英大文字、数字、半角スペース、許可記号のみ |
| 文字コード | 初期値 `cp932` |

#### C項目の処理順序

C項目は必ず以下の順序で処理する。

```text
1. 入力値を取得する
2. 許容文字チェックを行う
3. 指定文字コードでエンコードする
4. エンコード後のバイト数を検証する
5. 不足バイト数ぶん半角スペースで後ろ埋めする
6. 後ろ埋め後のバイト数を再検証する
```

許容文字チェックを通過した文字は、初期実装の `cp932` ではすべて1バイトでエンコードできる文字に限定する。これにより、`length - len(encoded)` で算出した不足バイト数と、追加する半角スペース数が一致する。

#### 許容文字の初期値

| 種別 | 許容範囲 |
|---|---|
| 数字 | `0-9` |
| 英字 | `A-Z` のみ。小文字は不可。必要な場合は事前に大文字化する |
| 半角カナ | `｡-ﾟ` の範囲 |
| スペース | 半角スペースのみ |
| 記号 | `-`, `.`, `(`, `)`, `/` |

金融機関仕様で追加記号が必要な場合は、施設設定または金融機関プロファイルで許容文字セットを拡張し、対応するテストを追加する。

### 10.3 ヘッダーレコード

| 順 | 項目 | 属性 | 桁 | 内容 |
|---:|---|---|---:|---|
| 1 | データ区分 | N | 1 | `1` |
| 2 | 種別コード | N | 2 | `91` |
| 3 | コード区分 | N | 1 | `0` |
| 4 | 委託者コード | N | 10 | 施設設定から取得 |
| 5 | 委託者名 | C | 40 | 半角カナ |
| 6 | 引落日 | N | 4 | `MMDD` |
| 7 | 取引銀行番号 | N | 4 | 施設の取引銀行コード |
| 8 | 取引銀行名 | C | 15 | 半角カナ |
| 9 | 取引支店番号 | N | 3 | 施設の取引支店コード |
| 10 | 取引支店名 | C | 15 | 半角カナ |
| 11 | 預金種目 | N | 1 | 委託者口座の預金種目 |
| 12 | 口座番号 | N | 7 | 委託者口座番号 |
| 13 | ダミー | C | 17 | スペース |

### 10.4 データレコード

| 順 | 項目 | 属性 | 桁 | 内容 |
|---:|---|---|---:|---|
| 1 | データ区分 | N | 1 | `2` |
| 2 | 引落銀行番号 | N | 4 | 保護者口座の銀行コード |
| 3 | 引落銀行名 | C | 15 | 半角カナ |
| 4 | 引落支店番号 | N | 3 | 保護者口座の支店コード |
| 5 | 引落支店名 | C | 15 | 半角カナ |
| 6 | ダミー | C | 4 | スペース |
| 7 | 預金種目 | N | 1 | 1: 普通、2: 当座、3: 納税準備、9: その他 |
| 8 | 口座番号 | N | 7 | 保護者口座番号 |
| 9 | 預金者名 | C | 30 | 口座名義カナ |
| 10 | 引落金額 | N | 10 | 請求金額 |
| 11 | 新規コード | N | 1 | 0: その他、1: 初回、2: 変更 |
| 12 | 顧客番号 | C | 20 | 20桁数字の顧客番号 |
| 13 | 振替結果コード | N | 1 | 依頼時は `0` |
| 14 | ダミー | C | 8 | スペース |

### 10.5 トレーラーレコード

| 順 | 項目 | 属性 | 桁 | 内容 |
|---:|---|---|---:|---|
| 1 | データ区分 | N | 1 | `8` |
| 2 | 合計件数 | N | 6 | データレコード件数 |
| 3 | 合計金額 | N | 12 | データレコードの引落金額合計 |
| 4 | 振替済件数 | N | 6 | 依頼時は `000000` |
| 5 | 振替済金額 | N | 12 | 依頼時は `000000000000` |
| 6 | 振替不能件数 | N | 6 | 依頼時は `000000` |
| 7 | 振替不能金額 | N | 12 | 依頼時は `000000000000` |
| 8 | ダミー | C | 65 | スペース |

### 10.6 エンドレコード

| 順 | 項目 | 属性 | 桁 | 内容 |
|---:|---|---|---:|---|
| 1 | データ区分 | N | 1 | `9` |
| 2 | ダミー | C | 119 | スペース |

---

## 11. Zengin出力前バリデーション

### 11.1 請求データのチェック

| チェック | エラー条件 |
|---|---|
| 請求状態 | `confirmed` でない |
| 支払方法 | `direct_debit` でない |
| 請求額 | 0円以下 |
| 請求取消 | `canceled` である |
| 入金済み | `paid` である |

### 11.2 口座情報のチェック

| チェック | エラー条件 |
|---|---|
| 銀行コード | 4桁数字でない |
| 支店コード | 3桁数字でない |
| 預金種目 | 保護者側は `1`, `2`, `3`, `9` 以外 |
| 口座番号 | 1〜7桁数字でない |
| 口座名義カナ | 空、または許容文字外 |
| 顧客番号 | 20桁数字でない、または空 |
| 新規コード | 0,1,2 以外 |

### 11.3 施設設定のチェック

| チェック | エラー条件 |
|---|---|
| 委託者コード | 10桁数字でない |
| 委託者名 | 空、または40バイト超過 |
| 取引銀行番号 | 4桁数字でない |
| 取引支店番号 | 3桁数字でない |
| 委託者口座種目 | 施設側は `1`, `2`, `9` 以外 |
| 委託者口座番号 | 1〜7桁数字でない |
| 引落日 | 未設定 |
| 文字コード | 未対応 |

### 11.4 レコード長チェック

各レコード生成後、必ず以下を確認する。

```text
len(record.encode(file_encoding)) == 120
```

120バイトでない場合、ファイル作成を中断する。

---

## 12. Zengin出力対象外条件

以下の請求はZenginファイルに含めない。

| 条件 | 理由 |
|---|---|
| 支払方法が現金 | 口座振替対象外 |
| 支払方法が銀行振込 | 口座振替対象外 |
| 支払方法が免除 | 口座振替対象外 |
| 口座振替状態が停止中 | 引落不可 |
| 請求額が0円以下 | 引落不要 |
| 請求が未確定 | 金額未確定 |
| 請求が入金済み | 二重請求防止 |
| 口座情報に不備がある | 金融機関提出不可 |

---

## 13. 振替結果取込仕様

### 13.1 概要

金融機関または収納代行会社から取得した振替結果ファイルを取り込み、Zengin出力明細および請求状態を更新する。

MVPでは、取込対象の結果ファイルは **預金口座振替依頼ファイルと同じ120バイト固定長のZengin形式** とする。構成はヘッダー、データ、トレーラー、エンドで、データレコードの振替結果コードを読み取る。

### 13.2 結果ファイルの形式

| 項目 | 仕様 |
|---|---|
| レコード長 | 120バイト固定長 |
| レコード構成 | ヘッダー、データ、トレーラー、エンド |
| 文字コード | 対象 `ZenginExport` の `file_encoding` と同じ |
| 改行 | 対象 `ZenginExport` の `line_separator` と同じ。ただし取込時はCRLFあり・なしの両方を許容して正規化する |
| データレコード | 出力時と同じ項目配置 |
| 結果コード位置 | データレコードの1始まり112バイト目、0始まりオフセット111、長さ1バイト |

取込時は、利用者が対象の `ZenginExport` を選択してからファイルをアップロードする。ヘッダーの委託者コード、引落日、取引銀行番号、取引支店番号が選択済み `ZenginExport.settings_snapshot` と一致しない場合は取込を中断する。

### 13.3 結果コード

| コード | 意味 | 請求状態 |
|---|---|---|
| 0 | 振替済 | `paid` |
| 1 | 資金不足 | `failed` |
| 2 | 取引なし | `failed` |
| 3 | 預金者都合による振替停止 | `failed` |
| 4 | 依頼書なし | `failed` |
| 8 | 委託者都合による停止 | `failed` |
| 9 | その他 | `failed` |

> 結果コードの意味は金融機関・収納代行会社によって異なる場合があるため、設定で変更可能にする。

### 13.4 照合キー

取込時は以下の順で照合する。

1. 選択された `ZenginExport.id`
2. データレコードの顧客番号
3. 引落金額
4. 口座情報スナップショット

顧客番号は家族単位で固定のため、単独では過去月の請求と衝突し得る。必ず対象 `ZenginExport` の明細内で照合する。

### 13.5 取込時の処理

| 結果 | 処理 |
|---|---|
| 振替済 | `BillingClaim.status = paid`、`paid_at` を設定 |
| 振替不能 | `BillingClaim.status = failed`、`failed_reason` を設定 |
| 顧客番号不一致 | 自動反映せず、エラー一覧に表示 |
| 金額不一致 | 自動反映せず、警告表示 |
| 既に入金済み | 二重反映しない |
| 未知の結果コード | 自動反映せず、確認対象にする |

### 13.6 振替不能後の再請求フロー

MVPでは、振替不能になった請求を自動で再出力しない。職員が確認したうえで、以下のいずれかを選択する。

| 対応 | 内容 |
|---|---|
| 現金・振込で回収 | 元請求を `failed` のままにし、別途手動で入金済みに変更する運用を将来追加する |
| 翌月繰越 | 次回以降の `BillingCycle` に繰越明細を作成する。MVPの標準対応 |
| 再振替 | 同月再振替はMVP対象外。必要な場合は新しい請求サイクルまたは手動明細で対応する |

翌月繰越の仕様は以下とする。

1. 対象は `BillingClaim.status = failed` の請求のみ。
2. 繰越先は `draft` または `generated` の `BillingCycle` のみ。
3. 繰越先の同一家族 `BillingClaim` に、`source_type = carryover` の `BillingChargeLine` を作成する。
4. 繰越明細の `source_claim_id` に元請求IDを保存する。
5. 元請求の `carried_over_to_claim_id` に繰越先請求IDを保存する。
6. `carried_over_to_claim_id` が設定済みの請求は再度繰越できない。

---

## 14. ルーティング仕様

### 14.1 請求ルーター

| Method | Path | 内容 |
|---|---|---|
| GET | `/billing/` | 請求ダッシュボード |
| GET | `/billing/cycles` | 請求月一覧 |
| GET | `/billing/cycles/new` | 請求月作成フォーム |
| POST | `/billing/cycles` | 請求月作成 |
| GET | `/billing/cycles/{cycle_id}` | 請求月詳細 |
| POST | `/billing/cycles/{cycle_id}/generate` | 請求候補生成 |
| POST | `/billing/cycles/{cycle_id}/confirm` | 請求確定 |
| POST | `/billing/cycles/{cycle_id}/unconfirm` | 請求確定取消。管理者のみ |
| GET | `/billing/claims/{claim_id}` | 請求詳細 |
| POST | `/billing/claims/{claim_id}/manual-lines` | 手動明細追加 |
| POST | `/billing/lines/{line_id}/delete` | 明細削除 |
| GET | `/billing/settings` | 請求設定画面 |
| POST | `/billing/settings` | 請求設定更新 |

### 14.2 Zenginルーター

| Method | Path | 内容 |
|---|---|---|
| GET | `/billing/zengin/{cycle_id}` | Zengin出力プレビュー |
| POST | `/billing/zengin/{cycle_id}/create` | Zenginファイル作成 |
| GET | `/billing/zengin/exports/{export_id}/download` | ファイルダウンロード |
| POST | `/billing/zengin/exports/{export_id}/cancel` | 出力取消 |
| GET | `/billing/payment-results` | 振替結果取込画面 |
| POST | `/billing/payment-results/import` | 振替結果ファイル取込 |

---

## 15. サービス構成

### 15.1 追加ファイル

```text
open-hoikuict/
  billing_service.py
  billing_calculation_service.py
  zengin_service.py
  routers/
    billing.py
    zengin.py
  templates/
    billing/
      dashboard.html
      cycles.html
      cycle_detail.html
      claim_detail.html
      manual_charge_form.html
      settings.html
      zengin_preview.html
      payment_result_import.html
  tests/
    test_billing_models.py
    test_extension_fee_calculation.py
    test_meal_fee_calculation.py
    test_zengin_format.py
    test_zengin_result_import.py
    test_billing_permissions.py
```

### 15.2 main.py への追加

```python
from routers.billing import router as billing_router
from routers.zengin import router as zengin_router

app.include_router(billing_router)
app.include_router(zengin_router)
```

### 15.3 billing_calculation_service.py

| 関数 | 内容 |
|---|---|
| `generate_billing_cycle(session, cycle_id)` | 対象月の請求候補を生成する |
| `calculate_extension_fees(session, child, period)` | 園児ごとの延長料金明細を生成する |
| `calculate_meal_fees(session, child, period)` | 園児ごとの給食費明細を生成する |
| `resolve_meal_attendance_count(session, child, period, count_source)` | 給食費用の出席日数を算出する |
| `calculate_monthly_fixed_meal_fee(child, rule, cycle)` | 月額固定給食費を月途中入退園ルール込みで算出する |
| `apply_daily_caps(lines, rule)` | 日別上限を適用する |
| `apply_monthly_caps(lines, rule)` | 月別上限を適用する |
| `recalculate_claim_total(claim)` | 明細合計を請求に反映する |

### 15.4 billing_service.py

| 関数 | 内容 |
|---|---|
| `create_cycle(...)` | 請求月を作成する |
| `confirm_cycle(cycle_id)` | 請求月を確定する |
| `unconfirm_cycle(cycle_id)` | 請求確定を取消する |
| `cancel_claim(claim_id)` | 請求を取消する |
| `carry_over_failed_claims(from_cycle_id, to_cycle_id)` | 振替不能請求を翌月以降の請求に繰り越す |
| `add_manual_charge(...)` | 手動費用を追加する |
| `lock_claims(cycle_id)` | 確定後に明細をロックする |
| `get_claim_summary(cycle_id)` | 集計情報を取得する |

### 15.5 zengin_service.py

| 関数 | 内容 |
|---|---|
| `create_zengin_export(session, cycle_id)` | 出力履歴と出力明細を作成する |
| `build_zengin_file(export_id)` | Zenginファイルを作成する |
| `build_header_record(settings, withdrawal_date)` | ヘッダーレコードを作成する |
| `build_data_record(line)` | データレコードを作成する |
| `build_trailer_record(lines)` | トレーラーレコードを作成する |
| `build_end_record()` | エンドレコードを作成する |
| `format_n(value, length)` | N項目を整形する |
| `format_c(value, length)` | C項目を整形する |
| `validate_record_length(record)` | 120バイト長を検証する |
| `parse_result_file(file_bytes, export_id)` | 120バイト固定長の振替結果ファイルを解析し、対象出力と照合する |

---

## 16. Zengin項目整形ロジック

### 16.1 N項目

```python
def format_n(value: str | int | None, length: int) -> str:
    raw = "" if value is None else str(value)
    if not raw.isdigit():
        raise ValueError("N項目には数字のみ指定できます")
    if len(raw) > length:
        raise ValueError("N項目の桁数を超過しています")
    return raw.zfill(length)
```

### 16.2 C項目

C項目は、許容文字チェック、エンコード、バイト数検証、スペース埋め、再検証の順で処理する。

```python
import re

ZENGIN_C_ALLOWED_RE = re.compile(r"^[0-9A-Z \-.()/｡-ﾟ]*$")


def validate_zengin_c_chars(raw: str) -> None:
    if not ZENGIN_C_ALLOWED_RE.fullmatch(raw):
        raise ValueError("C項目に許容されない文字が含まれています")


def format_c(value: str | None, length: int, encoding: str = "cp932") -> str:
    raw = "" if value is None else value

    # 1. 許容文字チェックを先に行う。
    #    初期実装では、cp932で1バイトとなる半角文字だけを許可する。
    validate_zengin_c_chars(raw)

    # 2. エンコードできるか確認する。
    encoded = raw.encode(encoding, errors="strict")

    # 3. エンコード後のバイト長を検証する。
    if len(encoded) > length:
        raise ValueError("C項目のバイト数を超過しています")

    # 4. 不足バイト数ぶん半角スペースを追加する。
    padding_length = length - len(encoded)
    formatted = raw + " " * padding_length

    # 5. 後ろ埋め後のバイト長を再検証する。
    if len(formatted.encode(encoding, errors="strict")) != length:
        raise ValueError("C項目の整形後バイト数が不正です")

    return formatted
```

全角カナ、漢字、ひらがな、絵文字、全角記号、小文字英字は初期実装ではエラーにする。自動変換を行う場合は、変換前後の値を画面で確認できるようにし、変換後に必ず同じ許容文字チェックを実行する。

### 16.3 レコード長検証

```python
def validate_record(record: str, encoding: str = "cp932") -> None:
    if len(record.encode(encoding, errors="strict")) != 120:
        raise ValueError("レコード長が120バイトではありません")
```

### 16.4 ファイルバイト列生成とハッシュ

```python
import hashlib


def build_file_bytes(records: list[str], encoding: str, line_separator: str) -> bytes:
    encoded_records = []
    for record in records:
        validate_record(record, encoding)
        encoded_records.append(record.encode(encoding, errors="strict"))

    if line_separator == "CRLF":
        return b"".join(record + b"\r\n" for record in encoded_records)

    if line_separator == "NONE":
        return b"".join(encoded_records)

    raise ValueError("未対応の改行設定です")


def calculate_content_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()
```

---

## 17. CSV出力仕様

### 17.1 請求一覧CSV

| カラム | 内容 |
|---|---|
| 請求月 | `YYYY-MM` |
| 家族ID | 家族ID |
| 家族名 | 家族名 |
| 支払方法 | 口座振替、現金、銀行振込、免除 |
| 請求額 | 合計金額 |
| 状態 | 未確定、確定、出力済、入金済、不能 |
| 振替結果 | 結果コード、不能理由 |

### 17.2 請求明細CSV

| カラム | 内容 |
|---|---|
| 請求月 | `YYYY-MM` |
| 家族ID | 家族ID |
| 園児ID | 園児ID |
| 園児名 | 園児名 |
| 費目 | 費目名 |
| 内容 | 明細説明 |
| 数量 | 数量 |
| 単価 | 単価 |
| 金額 | 金額 |
| 発生日 | 発生日 |

### 17.3 口座振替対象CSV

| カラム | 内容 |
|---|---|
| 家族ID | 家族ID |
| 顧客番号 | 顧客番号 |
| 請求額 | 引落金額 |
| 銀行コード | 銀行コード |
| 支店コード | 支店コード |
| 口座種別 | 預金種目 |
| 口座番号 | マスク表示 |
| 状態 | 出力対象、エラー、除外 |
| エラー内容 | 口座情報不備など |

### 17.4 振替結果CSV

| カラム | 内容 |
|---|---|
| 顧客番号 | 顧客番号 |
| 家族ID | 家族ID |
| 請求ID | 請求ID |
| 引落金額 | 引落金額 |
| 結果コード | 結果コード |
| 結果内容 | 振替済、資金不足など |
| 反映状態 | 反映済、要確認 |

---

## 18. セキュリティ・個人情報保護

口座情報は重要な個人情報として扱う。

| 項目 | 仕様 |
|---|---|
| 口座番号表示 | 原則マスク表示 |
| 口座情報編集 | `can_edit` 以上のみ |
| 施設設定編集 | `admin` のみ |
| ログ出力 | 口座番号、口座名義、顧客番号を出力しない |
| ファイル内容保存 | 原則DBに保存しない。ハッシュと履歴のみ保存 |
| 出力履歴 | 作成者、作成日時、件数、金額、ハッシュを保存 |
| 再出力 | 管理者のみ可能 |
| 監査ログ | 出力、再出力、取消、結果取込を記録 |
| アップロードファイル | 取込後に不要な一時ファイルを削除 |
| 文字入力 | 半角カナ、数字、英大文字、許可記号に制限 |

---

## 19. テスト仕様

### 19.1 延長料金テスト

| ケース | 期待結果 |
|---|---|
| 18:00降園 | 0円 |
| 18:01降園、30分単位 | 1単位分を請求 |
| 18:30降園、30分単位 | 1単位分を請求 |
| 18:31降園、30分単位 | 2単位分を請求 |
| 降園時刻なし | 請求しない |
| 日別上限あり | 日別上限を超えない |
| 月別上限あり、合計6,000円・上限5,000円 | 請求額は5,000円。上限適用後の明細合計も5,000円 |
| 手動除外 | 請求しない |

### 19.2 給食費テスト

| ケース | 期待結果 |
|---|---|
| 月額固定、日割りなし | 固定額を請求 |
| 月額固定、月途中入園、`daily_by_enrolled_days` | 在籍日数に応じて日割り請求 |
| 月額固定、月途中退園、`daily_by_enrolled_days` | 在籍日数に応じて日割り請求 |
| 出席日数連動、`attendance_check_in` | 登園打刻がある日数 × 単価を請求 |
| 出席日数連動、`attendance_verification_present` | 職員確認が出席の日数 × 単価を請求 |
| 出席日数連動、`verification_then_check_in`、打刻なし・職員確認出席 | 出席としてカウントする |
| 出席日数連動、`verification_then_check_in`、打刻あり・職員確認欠席 | 欠席としてカウントする |
| 欠席日 | 食数に含めない |
| 手動食数 | 入力食数 × 単価を請求 |
| ルール未設定 | エラーまたは手動扱い |

### 19.3 Zenginフォーマットテスト

| ケース | 期待結果 |
|---|---|
| ヘッダーレコード生成 | 120バイト |
| データレコード生成 | 120バイト |
| トレーラーレコード生成 | 120バイト |
| エンドレコード生成 | 120バイト |
| N項目 `0` | `0` が空文字にならず、指定桁のゼロ埋めになる |
| N項目 | 右詰めゼロ埋め |
| C項目 | 許容文字チェック後、左詰めスペース埋め |
| C項目に全角カナ | バリデーションエラー |
| C項目に小文字英字 | バリデーションエラー、または明示的な大文字変換後に再検証 |
| C項目のバイト超過 | バリデーションエラー |
| 合計件数 | データレコード件数と一致 |
| 合計金額 | データレコード金額合計と一致 |
| 保護者側預金種目 `3` | データレコードでは許可 |
| 施設側預金種目 `3` | ヘッダーレコードではMVP上エラー |
| 改行CRLF | 各120バイトレコードの後ろにCRLF |
| 改行なし | 120バイトレコードを連結 |
| content_hash | 実際の出力バイト列に対するSHA-256と一致 |

### 19.4 振替結果取込テスト

| ケース | 期待結果 |
|---|---|
| 120バイト固定長の結果ファイル | 正常に解析できる |
| CRLFあり結果ファイル | 正規化して解析できる |
| CRLFなし結果ファイル | 120バイト単位で解析できる |
| 結果コード0 | `paid` になる |
| 結果コード1 | `failed`、理由は資金不足 |
| 顧客番号不一致 | 自動反映しない |
| 金額不一致 | 自動反映しない |
| 選択したZenginExportとヘッダー不一致 | 取込を中断する |
| 既に入金済み | 二重反映しない |
| 未知の結果コード | 要確認扱い |
| failed請求の翌月繰越 | 繰越先に `source_type = carryover` の明細を作成し、元請求に `carried_over_to_claim_id` を設定 |
| 繰越済みfailed請求の再繰越 | エラー |

### 19.5 権限テスト

| ケース | 期待結果 |
|---|---|
| view_only が請求作成 | 403 |
| can_edit が請求作成 | 成功 |
| can_edit が請求候補生成 | 成功 |
| can_edit が `generated` 状態の請求確定 | 成功 |
| can_edit が請求設定編集 | 403 |
| admin が請求設定編集 | 成功 |
| can_edit が再出力 | 403 |
| admin が再出力 | 成功 |

### 19.6 請求サイクル・状態遷移テスト

| ケース | 期待結果 |
|---|---|
| 同一 `year_month` の請求月を二重作成 | ユニーク制約またはアプリケーションバリデーションでエラー |
| `draft` 状態のサイクルを確定 | エラー。先に請求候補生成が必要 |
| `generated` 状態のサイクルを確定 | 成功 |
| `confirmed` 状態のサイクルを再確定 | エラーまたは冪等処理として変更なし。どちらかに統一し、MVPではエラー |
| `confirmed` 状態で明細追加 | エラー |
| `exempt` 家族の請求候補生成 | `total_amount = 0`, `status = exempted` の請求が作成される |
| 0円請求のZengin出力 | 出力対象外 |

---

## 20. 受け入れ基準

MVPの受け入れ基準は以下とする。

1. 請求月を作成できる。
2. 同一請求月の二重作成を防止できる。
3. 対象期間の登降園記録から延長料金を自動計算できる。
4. 延長料金の日別上限・月別上限を適用できる。
5. 給食費を月額固定または出席日数連動で計算できる。
6. 給食費の出席判定で `AttendanceVerification` を利用できる。
7. 月途中入退園時の給食費日割り方針を設定できる。
8. その他費用を家族単位・園児単位で手動追加できる。
9. 免除家族は0円・`exempted` の請求として生成される。
10. 家族単位で請求額を確認できる。
11. `generated` 状態の請求月のみ確定できる。
12. 確定済み請求は明細変更できない。
13. 口座振替対象の請求だけをZengin出力対象にできる。
14. 口座情報不備がある場合、ファイル作成前にエラー表示される。
15. C項目は、許容文字チェック、エンコード、バイト数検証、スペース埋め、再検証の順で処理される。
16. Zenginファイルの全レコードが120バイトで出力される。
17. トレーラーレコードの合計件数・合計金額がデータレコードと一致する。
18. 作成したZenginファイルをダウンロードできる。
19. 出力ファイルのSHA-256ハッシュを保存できる。
20. 120バイト固定長の振替結果ファイルを取り込み、入金済み・振替不能を反映できる。
21. 振替不能請求を翌月以降に繰り越せる。
22. 権限に応じて操作が制限される。
23. 主要ロジックに自動テストがある。

---

## 21. 実装ステップ

### Step 1: DBモデル追加

以下のモデルを追加する。

```text
BillingSetting
FamilyBillingProfile
FeeItem
ExtensionFeeRule
MealFeeRule
BillingCycle
BillingClaim
BillingChargeLine
ZenginExport
ZenginExportLine
```

### Step 2: 家族口座情報画面の追加

家族詳細・編集画面に、支払方法と口座振替情報を登録するセクションを追加する。

### Step 3: 請求設定画面の追加

`/billing/settings` で以下を設定できるようにする。

- 施設の委託者情報
- 施設の取引銀行情報
- Zengin出力設定
- 費目マスタ
- 延長料金ルール
- 給食費ルール

### Step 4: 請求月作成機能の追加

`BillingCycle` を作成し、請求対象期間、引落日、支払期限を管理する。

### Step 5: 請求候補生成機能の追加

対象家族ごとに `BillingClaim` を作成し、園児ごとに `BillingChargeLine` を生成する。

### Step 6: 延長料金計算の実装

登降園記録の降園時刻をもとに延長料金を計算する。

### Step 7: 給食費計算の実装

月額固定または出席日数連動で給食費を計算する。

### Step 8: その他費用登録の実装

職員が任意の費用を家族単位または園児単位で登録できるようにする。

### Step 9: 請求確定の実装

請求明細をロックし、請求状態を `confirmed` に変更する。

### Step 10: Zenginファイル出力の実装

確定済み請求からZenginファイルを作成する。

### Step 11: 振替結果取込の実装

振替結果ファイルを解析し、請求状態に反映する。

### Step 12: テスト追加

延長料金、給食費、Zenginフォーマット、振替結果取込、権限制御のテストを追加する。

---

## 22. 初期実装で優先すべき順序

初期実装では、以下の順に進める。

1. 家族単位の請求データモデル
2. 家族ごとの口座振替情報
3. 費目マスタ
4. 手動費用登録
5. 延長料金自動計算
6. 請求確定
7. Zenginファイル出力
8. 振替結果取込
9. 給食費の出席日数連動対応

給食費は施設ごとの差が大きいため、最初は「月額固定」と「手動登録」を先に実装し、その後に「出席日数連動」を追加するのが安全である。

---

## 23. 補足仕様

### 23.1 顧客番号の設計

顧客番号は20バイトのC項目だが、MVPでは **20桁数字固定** として扱う。

```text
顧客番号 = 施設コード3桁 + family_id 17桁ゼロ埋め
```

例:

```text
施設コード: 001
family_id: 123
顧客番号: 00100000000000000123
```

| 項目 | 決定内容 |
|---|---|
| パディング | `family_id` を17桁で前ゼロ埋め |
| 施設コード | `BillingSetting.customer_number_facility_code` を先頭3桁に付与 |
| 単一施設 | 初期値 `000` を使用 |
| 複数施設対応 | 将来、施設ごとに3桁コードを採番して衝突を防ぐ |
| 請求ID | 顧客番号には含めない |
| 照合 | `ZenginExport.id + customer_number + amount` を基本に照合する |

### 23.2 Zengin出力時のスナップショット

Zengin出力後に家族の口座情報が変更されても、過去の出力履歴が変わらないように、出力時点の口座情報を `ZenginExportLine.bank_snapshot` に保存する。

保存対象:

- 銀行コード
- 銀行名カナ
- 支店コード
- 支店名カナ
- 預金種目
- 口座番号
- 口座名義カナ
- 顧客番号
- 新規コード

### 23.3 再出力

Zenginファイルの再出力は管理者のみ可能とする。

再出力時は以下を行う。

1. 既存の `ZenginExport` を `reissued` または `canceled` にする。
2. 新しい `ZenginExport` を作成する。
3. 再出力理由を記録する。
4. 監査ログに作成者、日時、理由を記録する。

### 23.4 金額の扱い

| 条件 | 扱い |
|---|---|
| 正の金額 | 通常請求 |
| 0円 | Zengin出力対象外 |
| 負の金額 | 返金・減免明細として請求内では許可。ただし請求合計が0円以下の場合はZengin出力対象外 |
| 小数 | 使用しない。すべて円単位整数 |

### 23.5 決定済み仕様のまとめ

| 論点 | 決定 |
|---|---|
| C項目の処理順序 | 許容文字チェック → エンコード → バイト数検証 → スペース埋め → 再検証 |
| 預金種目 | 施設側は `1`, `2`, `9`。保護者側は `1`, `2`, `3`, `9` |
| 顧客番号 | 施設コード3桁 + family_id17桁ゼロ埋めの20桁数字 |
| 給食費の出席判定 | `verification_then_check_in` を推奨初期値とし、職員確認を優先 |
| 免除家族 | 0円・`exempted` の請求を生成し、Zengin出力対象外 |
| 振替不能後 | 自動再請求しない。MVPでは翌月繰越明細を作成 |
| 月途中入退園 | `MealFeeRule.proration_policy` で制御。初期値は日割りなし |
| 結果ファイル | 120バイト固定長のZengin結果ファイルとして取り込む |
| content_hash | ダウンロードされる実ファイルバイト列のSHA-256 |

### 23.6 金融機関ごとに確認が必要な事項

以下は本仕様で初期値を定めるが、導入先の金融機関・収納代行会社の仕様書に合わせて変更できるようにする。

| 項目 | 初期値 |
|---|---|
| 文字コード | `cp932` |
| 改行 | `CRLF` または `NONE` を施設設定で選択 |
| 許容記号 | `-`, `.`, `(`, `)`, `/` |
| 結果コードの意味 | 標準マッピングを持つが設定で上書き可能 |
| ファイル名 | 初期実装ではシステム生成。金融機関指定がある場合は設定化 |

---

## 24. 完了条件

本機能は、以下が満たされた時点でMVP完了とする。

- 請求月を作成できる。
- 延長料金、給食費、その他費用を請求明細として管理できる。
- 家族単位の請求を確定できる。
- 口座振替対象のみ抽出できる。
- 120バイト固定長のZenginファイルを作成できる。
- 出力前に口座情報・金額・文字列・レコード長を検証できる。
- 出力ファイルのSHA-256ハッシュを保存できる。
- 120バイト固定長の振替結果ファイルを取り込み、請求状態を更新できる。
- 振替不能請求を翌月以降に繰り越せる。
- 権限に応じた操作制限がある。
- 主要機能の自動テストが通る。
