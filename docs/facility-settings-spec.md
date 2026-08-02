# 施設設定機能 仕様書（facility-settings）

- 対象リポジトリ: open-hoikuict
- ステータス: Draft revised
- 作成日: 2026-07-05
- 関連: 保護者キオスクUI、延長保育料金設定、補食判定、請求

---

## 1. 背景と目的

### 1.1 背景

現状、園ごとに差が出やすい運用値の一部がコードに固定されている。

例:

- 保護者キオスクのお迎え予定時刻候補
- 補食が必要になる時刻
- 補食費の金額
- お迎え予定者の選択肢

一方で、延長保育料の主要な料金パラメータは既に `ExtendedCareFeeRule` と `/extended-care-fees/settings` で設定できる。

既に設定可能なもの:

- 延長開始時刻
- 猶予時間
- 丸め単位
- 単価
- 日別上限額
- 適用期間

したがって、本仕様の `施設設定` は既存の延長保育料金ルールと重複させず、園全体の運用値、UI制御値、将来の請求連携に必要な基本値を扱う。

### 1.2 目的

園ごとに異なる運用パラメータを管理画面から変更できるようにする。

ただし、初期実装は最小限に絞る。

- 既定値だけで動く
- 既存の延長保育料金ルールと重複しない
- 料金・請求に影響しうる値は変更履歴を残す
- 請求明細化など影響範囲が広いものは段階的に実装する

### 1.3 基本方針

- 棚卸しは広く、実装は狭く進める
- 1デプロイ = 1施設を前提に、Phase 1ではシングルトン設定として扱う
- 設定行がなくても既定値で動作する
- 設定参照ヘルパは勝手に `commit()` しない
- 確定済み料金や確定済み請求を、設定変更だけで自動変更しない

---

## 2. スコープ

### 2.1 Phase 1 の対象

Phase 1では、保護者キオスクと補食判定に関わる最小限の項目だけを設定化する。

| 項目 | 目的 | 既定値 |
| --- | --- | --- |
| お迎え予定の最終選択時刻 | 保護者キオスクで選べる予定時刻の上限 | `19:00` |
| 補食判定時刻 | 予定時刻から補食が必要かを初期判定する | `18:00` |
| 補食費 | 画面上の注記に表示する補食費 | `100` |

Phase 1で行うこと:

- 施設設定モデルを追加する
- 管理者向け設定ページを追加する
- 変更履歴を記録する
- 保護者キオスクのお迎え予定時刻候補を設定値から生成する
- お迎え予定時刻が補食判定時刻以降の場合、補食チェックを自動でオンにする
- 補食費を確認画面・注記に表示する

### 2.2 Phase 1 ではやらないこと

Phase 1では、補食費を請求明細へ自動反映しない。

理由:

- 請求明細化には金額スナップショットが必要になる
- 設定変更後に過去の補食費をどう扱うかの仕様が必要になる
- `BillingChargeSourceType` に `snack_auto` のような種別を追加する必要がある
- 確定済み請求との整合性を設計する必要がある

補食費の請求連携は Phase 1.5 または Phase 2 で扱う。

### 2.3 スコープ外

- 延長開始時刻、猶予時間、丸め単位、単価、日別上限額の再設計
- 月額上限
- 曜日別ルール
- 年齢・クラス別ルール
- 補食費の請求明細自動生成
- 園ごとの文言カスタマイズ全般
- マルチ施設対応

---

## 3. 既存実装との責務分離

### 3.1 延長保育料金ルール

既存の `ExtendedCareFeeRule` を正とする。

対象:

- 延長開始時刻
- 猶予時間
- 丸め単位
- 単価
- 日別上限額
- 適用開始日・終了日
- 有効/無効

施設設定にはこれらと同じ意味の項目を追加しない。

### 3.2 施設設定

施設設定は、園全体の運用・UI・補助的な判定値を扱う。

Phase 1の対象:

- 保護者が予定時刻として選べる上限
- 補食が必要かどうかの初期判定
- 補食費の表示値

### 3.3 上限時刻の意味

`お迎え予定の最終選択時刻` は、予定入力の上限である。

これは実際の降園打刻を拒否するための値ではない。

実際の降園が上限を超えた場合:

- 打刻は記録する
- 必要に応じて警告表示する
- 料金計算は既存の延長保育料金ルールに従う

---

## 4. データモデル

### 4.1 FacilitySettings

新設テーブル: `facility_settings`

Phase 1では1行だけを持つシングルトンテーブルとする。

```python
class FacilitySettings(SQLModel, table=True):
    __tablename__ = "facility_settings"

    id: int | None = Field(default=None, primary_key=True)

    pickup_plan_latest_time: str = Field(default="19:00", max_length=5)
    # 保護者キオスクで選択できるお迎え予定時刻の上限。HH:MM。

    snack_threshold_time: str = Field(default="18:00", max_length=5)
    # 予定時刻がこの時刻以降の場合、補食が必要として初期判定する。HH:MM。

    snack_fee: int = Field(default=100)
    # 補食費の表示用金額。Phase 1では請求明細へ自動反映しない。

    updated_at: datetime = Field(default_factory=utc_now)
    updated_by_user_id: UUID | None = Field(default=None, foreign_key="users.id")
    updated_by_name: str | None = None
```

時刻を `HH:MM` 文字列として持つ理由:

- 既存の `ExtendedCareFeeRule.start_time` が `HH:MM` 文字列である
- HTML form の `time` input と相性がよい
- 日付やタイムゾーン変換を伴わない園内運用時刻として扱える

内部処理では必ずパースヘルパを通して `datetime.time` に変換して比較する。

### 4.2 FacilitySettingsHistory

新設テーブル: `facility_settings_history`

```python
class FacilitySettingsHistory(SQLModel, table=True):
    __tablename__ = "facility_settings_history"

    id: int | None = Field(default=None, primary_key=True)
    changed_at: datetime = Field(default_factory=utc_now)
    changed_by_user_id: UUID | None = Field(default=None, foreign_key="users.id")
    changed_by_name: str | None = None

    field_name: str
    old_value: str
    new_value: str
```

方針:

- 設定保存時、変更されたフィールドごとに1行追加する
- 変更なし保存では履歴を追加しない
- 履歴は削除・編集しない
- モック職員では `user_id` がない場合があるため、`changed_by_name` も残す

### 4.3 設定取得ヘルパ

```python
def get_facility_settings(session: Session) -> FacilitySettings:
    settings = session.exec(select(FacilitySettings).order_by(FacilitySettings.id)).first()
    if settings is None:
        settings = FacilitySettings()
        session.add(settings)
        session.flush()
    return settings
```

重要:

- このヘルパ内では `commit()` しない
- 呼び出し元のトランザクションを勝手に確定しない
- 起動時初期化で明示的に設定行を作る場合も、このヘルパを使ってよい

---

## 5. 設定ページ

### 5.1 ルート

- GET `/settings/facility`
- POST `/settings/facility`

新設:

- `routers/facility_settings.py`
- `templates/facility_settings.html`

### 5.2 権限

管理者のみ編集可能とする。

- 表示: 管理者のみ
- 保存: 管理者のみ
- 権限判定: `require_admin(current_user)`

`can_edit` ではなく `admin` を要求する。

理由:

- 補食費など料金・請求に影響しうる値を含む
- 設定変更履歴を監査対象にしたい

### 5.3 画面構成

```text
施設設定
├── 保護者キオスク
│   └── お迎え予定の最終選択時刻
├── 補食
│   ├── 補食判定時刻
│   └── 補食費（円/回）
└── 変更履歴
    └── 直近20件
```

### 5.4 バリデーション

| 項目 | ルール |
| --- | --- |
| お迎え予定の最終選択時刻 | `HH:MM` 形式、12:00〜23:00 |
| 補食判定時刻 | `HH:MM` 形式、12:00〜23:00 |
| 時刻の関係 | 補食判定時刻 < お迎え予定の最終選択時刻 |
| 補食費 | 0以上、10,000円以下の整数 |

### 5.5 保存時の警告文

設定保存前に確認ダイアログを表示する。

```text
この変更は保存以降の保護者キオスク表示と補食判定に適用されます。
過去の打刻・確定済み料金・確定済み請求は自動では変更されません。
```

---

## 6. 保護者キオスクへの反映

### 6.1 お迎え予定時刻候補

お迎え予定時刻候補は、施設設定の `pickup_plan_latest_time` を超えない範囲で生成する。

既定:

- 開始: `07:00`
- 終了: `pickup_plan_latest_time`
- 間隔: 15分

例:

`pickup_plan_latest_time = "19:30"` の場合:

- `19:00` は選択可
- `19:15` は選択可
- `19:30` は選択可
- `19:45` は選択不可

現在のUIのように「時」と「分」を別ボタンで選ぶ場合、選択中の時に応じて無効な分ボタンを無効化する。

より安全な実装として、内部では `HH:MM` の候補リストを生成し、UI側で時・分に分解して表示する。

### 6.2 補食チェックの初期判定

お迎え予定時刻が `snack_threshold_time` 以降の場合、補食チェックを自動でオンにする。

判定:

```text
planned_pickup_time >= snack_threshold_time
```

例:

| 補食判定時刻 | 予定時刻 | 初期値 |
| --- | --- | --- |
| 18:00 | 17:45 | 不要 |
| 18:00 | 18:00 | 必要 |
| 18:00 | 18:15 | 必要 |

保護者が手動でチェックを外すことは許可する。

理由:

- アレルギーや個別事情で補食提供しないケースがありうる
- 予定時刻は目安であり、実際の提供判断は現場運用に依存する

### 6.3 補食費表示

補食チェックがオンの場合、確認画面に以下を表示する。

```text
補食: 必要（100円）
```

Phase 1では、表示と判定のみ行う。

請求明細への自動反映は Phase 1.5 または Phase 2 で扱う。

---

## 7. 補食費の請求連携（将来Phase）

補食費を請求に反映する場合は、Phase 1とは別に以下を設計する。

### 7.1 追加候補

- `BillingChargeSourceType.snack_auto`
- 補食費用の `FeeItem`
- `AttendanceRecord.snack_fee_snapshot`
- 月次請求生成時の補食明細自動作成

### 7.2 スナップショット方針

補食費は設定変更されうるため、請求に使う場合は記録時点または請求生成時点の金額を明確にする必要がある。

候補:

1. お迎え予定確定時に `snack_fee_snapshot` を保存する
2. 請求生成時にその時点の設定を使う
3. 対象日の履歴から有効な設定を解決する

推奨:

Phase 1.5では 1 を採用する。

理由:

- 保護者に表示した金額と請求金額が一致しやすい
- 設定履歴から日付解決するより実装が単純
- 過去データ不変の原則に合う

---

## 8. 設定化候補リスト

Phase 1では実装しない項目も含め、園ごとに差が出うる項目を棚卸しする。

### 8.1 時刻系

| 項目 | 優先度 | 現状 | 備考 |
| --- | --- | --- | --- |
| お迎え予定の最終選択時刻 | A | 固定 | Phase 1 |
| 補食判定時刻 | A | 固定 | Phase 1 |
| 延長保育開始時刻 | A | 既存 | `ExtendedCareFeeRule.start_time` |
| 猶予時間 | A | 既存 | `ExtendedCareFeeRule.grace_minutes` |
| 丸め単位 | A | 既存 | `ExtendedCareFeeRule.rounding_minutes` |
| 登園受付開始時刻 | B | 固定 | 将来候補 |
| 通常保育の降園締切 | B | 固定 | 将来候補 |
| 未打刻アラートの判定時刻 | B | 固定 | attendance checks 関連 |

### 8.2 料金系

| 項目 | 優先度 | 現状 | 備考 |
| --- | --- | --- | --- |
| 補食費 | A | 固定 | Phase 1では表示・判定のみ |
| 延長単価 | A | 既存 | `ExtendedCareFeeRule.unit_price` |
| 日別上限額 | A | 既存 | `ExtendedCareFeeRule.daily_cap_amount` |
| 月額上限 | A | なし | Phase 2候補 |
| 兄弟割引 | B | なし | Phase 2以降 |
| 曜日別ルール | B | なし | 別テーブル設計が必要 |
| 年齢・クラス別ルール | B | なし | 別テーブル設計が必要 |

### 8.3 打刻・出欠

| 項目 | 優先度 | 現状 | 備考 |
| --- | --- | --- | --- |
| お迎え予定者カテゴリ | B | 固定 | 母/父/祖父/祖母/ファミリーサポート/その他 |
| 欠席理由カテゴリ | B | 固定 | 将来候補 |
| 出欠不整合アラート条件 | B | 固定 | 将来候補 |

### 8.4 保護者連絡

| 項目 | 優先度 | 現状 | 備考 |
| --- | --- | --- | --- |
| 日次連絡の入力項目 | B | 固定 | 将来候補 |
| 日次連絡の必須項目 | B | 固定 | 将来候補 |
| 通知タイミング | C | なし | 将来候補 |

### 8.5 健康管理

| 項目 | 優先度 | 現状 | 備考 |
| --- | --- | --- | --- |
| 検温基準 | B | 固定 | 将来候補 |
| アレルギー表示方法 | C | 固定 | 将来候補 |
| 投薬確認項目 | C | 固定 | 将来候補 |

### 8.6 請求

| 項目 | 優先度 | 現状 | 備考 |
| --- | --- | --- | --- |
| Zengin/口座振替設定 | A | 既存 | `BillingSetting` |
| 請求締日 | A | なし | Phase 2候補 |
| 支払期限 | A | なし | Phase 2候補 |
| 費目名 | B | 一部既存 | `FeeItem` は存在、UI整理は別途 |
| 端数処理 | A | 一部既存 | 給食費の日割りでは `ProrationRounding` あり |
| 0円明細許可 | B | 一部固定 | `validate_charge_amount` 関連 |

### 8.7 帳票・CSV

| 項目 | 優先度 | 現状 | 備考 |
| --- | --- | --- | --- |
| 出力項目 | B | 固定 | 将来候補 |
| 並び順 | B | 固定 | 将来候補 |
| 園名・定型文言 | B | 一部固定 | 帳票別に検討 |

### 8.8 権限・カレンダー・表示文言

| 項目 | 優先度 | 現状 | 備考 |
| --- | --- | --- | --- |
| 施設設定を編集できる権限 | A | 管理者固定 | Phase 1 |
| 承認が必要な操作 | B | なし | 将来候補 |
| 開園日・休園日 | B | カレンダーで一部表現可能 | 設定化要否は要検討 |
| 土曜保育 | B | なし | 将来候補 |
| 園による呼称差 | C | 一部既存 | クラス名など |

---

## 9. 実装計画

### 9.1 事前コミット

現在進行中の保護者キオスクUI/JST/補食チェック対応は、施設設定機能とは分けて先にコミットする。

理由:

- UI改善と設定機能を混ぜるとレビューしづらい
- `AttendanceRecord.snack_required` の追加は独立した変更として扱える
- 施設設定のモデル追加・画面追加とは責務が違う

### 9.2 Phase 1 実装順

1. `FacilitySettings` / `FacilitySettingsHistory` モデル追加
2. 起動時マイグレーション追加
3. `facility_settings_service.py` 追加
4. 管理者向け設定ページ追加
5. 保護者キオスクの時刻候補生成を施設設定参照に変更
6. 補食判定時刻に基づくチェック初期値・注記表示を追加
7. テスト追加

### 9.3 コミット分割案

1. `docs: add facility settings spec`
2. `feat: add facility settings model and service`
3. `feat: add facility settings admin page`
4. `feat: apply facility settings to guardian pickup form`
5. `test: cover facility settings behavior`

---

## 10. テスト観点

`test_facility_settings.py` を新設する。

### 10.1 設定取得

- 設定行がない状態で既定値の `FacilitySettings` が返る
- ヘルパ内で `commit()` されない

### 10.2 バリデーション

- 不正な時刻形式が拒否される
- `snack_threshold_time >= pickup_plan_latest_time` が拒否される
- `snack_fee < 0` が拒否される
- `snack_fee > 10000` が拒否される

### 10.3 履歴

- 変更されたフィールドだけ履歴が増える
- 変更なし保存では履歴が増えない
- `changed_by_user_id` がない場合も `changed_by_name` が残る

### 10.4 権限

- 管理者は設定ページを表示・保存できる
- 編集可ユーザーはアクセスできない
- 閲覧のみユーザーはアクセスできない

### 10.5 キオスク反映

- 既定値では `19:00` までの候補が表示される
- `pickup_plan_latest_time = "19:30"` の場合、`19:45` は選べない
- `snack_threshold_time = "18:00"` の場合、`18:00` 以降で補食チェックが自動オンになる
- 保護者が補食チェックを手動で外せる

### 10.6 既存延長保育計算の不変性

- 施設設定を変更しても、`ExtendedCareFeeRule` による延長保育料計算結果は変わらない
- 確認済み延長保育料金は設定変更だけでは変わらない

---

## 11. 未決事項

### 11.1 補食費の請求連携

Phase 1では請求に反映しない。

Phase 1.5またはPhase 2で以下を決める。

- `snack_auto` の請求種別を追加するか
- 補食費を `meal_auto` に含めるか
- 補食費用の `FeeItem` をどう作るか
- `AttendanceRecord` に補食費スナップショットを持たせるか
- 月次請求生成時にどのタイミングの金額を使うか

### 11.2 お迎え予定者カテゴリの設定化

Phase 1では固定のままとする。

将来、施設設定に含める場合は `JSON` カラムまたは別テーブルを検討する。

### 11.3 通常保育時間との関係

通常保育の降園締切、短時間認定、標準時間認定は本仕様では扱わない。

将来、認定区分別の保育時間設定が必要になった場合は、`FacilitySettings` の単純なカラム追加ではなく、別テーブルで設計する。

---

## 12. 実装メモ

### 12.1 推奨ヘルパ

- `parse_hhmm(value: str) -> time`
- `format_hhmm(value: time) -> str`
- `build_pickup_time_options(latest_time: str, start_time: str = "07:00", interval_minutes: int = 15) -> list[str]`
- `is_snack_required_for_pickup(planned_pickup_time: str, snack_threshold_time: str) -> bool`

### 12.2 既存コードへの反映候補

- `routers/guardian.py`
  - 固定の `PICKUP_HOUR_OPTIONS` を設定参照に置換
  - 補食チェックの初期値を設定参照に置換

- `templates/guardian/kiosk.html`
  - 上限を超える時刻候補を表示しない
  - 補食費注記を表示する

- `templates/guardian/pickup_confirm.html`
  - 補食費を表示する

- `main.py`
  - `facility_settings_router` を追加

- `templates/base.html`
  - 管理系ナビに「施設設定」を追加する

---

## 13. Phase 1 完了条件

- 管理者が施設設定ページで3項目を保存できる
- 設定変更履歴が残る
- 既定値だけで保護者キオスクが動く
- お迎え予定時刻候補が上限時刻を超えない
- 補食判定時刻以降の予定時刻で補食チェックが自動オンになる
- 補食費が確認画面に表示される
- 既存の延長保育料金計算テストが壊れない
- 施設設定変更だけで確定済み料金・請求が変わらない
