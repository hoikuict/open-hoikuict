# 週案・日案 作成機能 追加仕様書 (rev.3)

`hoiku-plan-docs` に **週案（weekly_plan）** と **日案（daily_plan）** の作成機能を追加するための仕様です。
現行の年案・月案で確立した契約（`document_type` / `status` / `section_key` / `source_refs`）と UI コンポーネントを最大限に再利用し、後方互換を壊さずに「短期的な指導計画」までを一気通貫で扱えるようにします。

- 対象読者: 本リポジトリの実装者、`open-hoikuict` / `hoiku-plan-writer` 連携担当
- 前提ドキュメント: [README.md](../README.md) / [docs/integration-contract.md](integration-contract.md)
- 関連実装: `app/hoiku_plan_docs/contracts.py` / `models.py` / `services/generators.py` / `services/bunrei.py` / `web/routers/plans.py` / `web/routers/bunrei.py` / `serializers.py` / `store.py` / `templates/`

> **rev.2 で確定した主要な設計判断（矛盾解消）**
> 1. **MVP（フェーズ1）は手入力フォーム作成のみ。文例選択（`/bunrei/weekly` `/bunrei/daily`）はフェーズ2**（§2.3 / §10）。
> 2. **対象期間は必須・自動フォールバックなし**。Web は同フォーム再表示＋エラー、API は 422（§7.1）。
> 3. **接続は要約テキストに加え `parent_document_id` / `related_document_ids` を契約に追加**（§3.3 / §3.6）。
> 4. **`schedule` を永続契約として厳密定義**（`layout` / `column.key` / `row_key` / `ScheduleCell`、§3.4）。
> 5. **週案 `schedule`（weekly_grid）は常に生成・保存（空セル可）。API は週案/日案で必須出力、年案/月案では省略**（§3.4.5）。
> 6. **`age_class` はフォームで明示保持。`classroom_ref` から推定しない**（§3.7 / §6.1）。

> **rev.3 で追加した分離仕様**
> - 厚生労働省「保育分野の業務負担軽減・業務の再構築のためのガイドライン」（令和3年3月）を、既存仕様とは分離した **追加仕様** として §12 に追記。
> - 追加仕様は「業務負担軽減・重複削減・最低限項目・計画/記録/反省の一体化」の設計制約を定義する。既存のデータ契約・画面契約を直接置き換えず、MVP実装時の優先順位とUI/運用判断に反映する。

---

## 1. 背景と目的

### 1.1 現状

現行アプリは「長期的な指導計画」である **年案（`annual_plan`）** と「短期的な指導計画」の入口である **月案（`monthly_plan`）** までを実装済みです。

- 帳票は `PlanDocument` + `SectionBlock`（`section_key` で永続契約）で表現
- 生成は `services/generators.py`、文例選択生成は `services/bunrei.py`
- 保存は in-memory の `DocumentStore`、状態遷移は `draft → in_review → approved / rejected → archived`
- 権限は `view_only` / `can_edit` / `admin`、職員セッションは Cookie ベース（差し替え前提）

### 1.2 法令・指針上の位置づけ（実装根拠）

指導計画は **長期的な指導計画** と **短期的な指導計画** に分かれ、後者に **週案・日案** が含まれます。実装根拠は **公的資料を主**とし、一般情報サイトは「実務例の参考」として明確に分離します（§1.5）。

#### 一次根拠（公的資料）

- **保育所保育指針（厚生労働省告示第117号、平成29年）第1章 総則 3「保育の計画及び評価」(1)指導計画の作成**
  保育所は全体的な計画に基づき、「子どもの生活や発達を見通した長期的な指導計画」と、「それに関連しながら、より具体的な子どもの日々の生活に即した短期的な指導計画」を作成しなければならない。本仕様の **年案・月案＝長期／週案・日案＝短期** はこの区分に対応する。
  出典: 厚生労働省 https://www.mhlw.go.jp/web/t_doc?dataId=00010450
- **幼保連携型認定こども園 教育・保育要領（内閣府・文科省・厚労省告示第1号、平成29年）第1章 第2 指導計画の作成と園児の理解に基づいた評価**
  具体的なねらい及び内容を明確にし、適切な環境を構成して活動が展開されるようにする。週、日などの指導計画では **生活のリズム** と **意識・興味の連続性** に配慮する。出典: こども家庭庁 解説・資料 https://www.cfa.go.jp/policies/kokoseido/kodomoen/kokuji/
- **幼稚園教育要領 第3章（旧）指導計画作成上の留意事項** も短期計画（週・日）の連続性配慮を同趣旨で示す。出典: 文部科学省 https://www.mext.go.jp/a_menu/shotou/old-cs/1322230.htm

#### 補助的記述（抽象度が高いため副次扱い）

- 児童福祉施設の設備及び運営に関する基準に基づく「保育の計画的実施」の一環として、現場では月案→週案→日案へと具体化する。**特定条文の個別義務とは結び付けず、運用上の位置づけとして補助的に記載**する。

> 設計上の含意:
> 1. 週案・日案は **月案（上位は年案）との接続** を前提に作る（§3.3 / §3.6 で document ID を契約化）。
> 2. 週案は「1週間の見通し（ねらい・活動・環境・援助・評価）」、日案は「**時系列（デイリープログラム）**＋養護・教育のねらい・評価」を中心に持つ。
> 3. いずれも **評価・反省（振り返り観点）** を必須セクションとして持ち、次期計画へつなぐ。

### 1.3 目的

- 月案までだった作成導線を **週案・日案** まで拡張する。
- 既存の **文例DB / 園文例 / 確認フロー / 印刷プレビュー / 承認ワークフロー** を活用する。
- 連携契約に対し **追加のみ（非破壊）** で拡張する。

### 1.4 スコープ外

- 共通文例DB（`bunrei.sqlite`）への週案・日案専用文例の新規生成（当面は月案文例を流用。園文例で `週案`/`日案` を受け入れる拡張のみ行う）。
- 永続DB化（in-memory 踏襲。`schedule` のシリアライズは将来の永続化を見据えて確定させる）。
- 帳票PDF出力（`window.print()` を使用）。
- 行事・祝日・休園日のカレンダー連携、延長保育/短時間利用の時間割自動分岐（MVPは固定、§7.5）。

### 1.5 根拠の取り扱い方針

- **実装・契約の根拠** は §1.2 一次根拠（mhlw / cfa / mext）のみを用いる。
- 章立て・項目名・文例運用の **実務例の参考** として一般サイトを併記するが、規範根拠としては扱わない:
  保育box https://hoiku-box.net/useful_cat04/article077/ ／ Child Care System https://c-c-s.jp/ccsmag-archives/shidoukeikaku_20221013/ ／ ほいくis https://hoiku-is.jp/article/detail/349/

---

## 2. 全体設計方針とスコープ確定

### 2.1 契約・再利用の方針

| 観点 | 方針 |
| --- | --- |
| 文書種別 | `weekly_plan` / `daily_plan` を追加。互換 alias `weekly` / `daily`。 |
| 状態 | 既存の `draft/in_review/approved/rejected/archived` をそのまま使用。 |
| セクション | `section_key` を新規定義（永続契約）。叙述セクションは既存 `SectionBlock` を流用。 |
| 表形式データ | 日案の時系列・週案の曜日別グリッドを **構造化フィールド `schedule`** で表現（§3.4、永続契約）。 |
| 接続 | `parent_document_id` / `related_document_ids` + 要約テキストで月案→週案→日案を保持（§3.3）。 |
| 生成 | `generators.py` に `generate_weekly_plan` / `generate_daily_plan` を追加。 |
| 文例 | フェーズ2。`bunrei.py` に週案/日案候補を追加（月案文例を項目マッピングで流用）。 |
| 権限 | 既存の `require_can_edit` / `require_classroom_access` を適用（§7.4 で view_only のGET方針も定義）。 |

### 2.2 「任意フィールド」の意味（slots=True 対応）

`PlanDocument` は `@dataclass(slots=True)` のため、実行時に動的属性を足せません。本仕様で「任意フィールド」と書くものは **すべて dataclass 上の明示フィールド**（既定値 `None` / 空）として追加します。年案・月案では既定値のままとなり、生成・表示・API に影響しません。

### 2.3 フェーズ別スコープ（§4.6/§5.2 と §10 の矛盾解消）

| 機能 | フェーズ |
| --- | --- |
| 週案/日案の手入力フォーム作成・生成・詳細・編集・印刷 | **1（MVP）** |
| `schedule`（日案時系列＋週案グリッド）の生成・表示・セル編集 | **1（MVP）** |
| `parent_document_id` による接続と参照リスト | **1（MVP）** |
| 文例選択作成 `/bunrei/weekly` `/bunrei/daily`、園文例の `週案`/`日案` 受け入れ | **2** |
| 日案時系列の行追加/削除UI、週案↔日案の自動連携、永続DB化 | **3** |

§4.6・§5.2・§6.4 は **フェーズ2の仕様**として記載する（見出しに「[フェーズ2]」を付す）。MVP では `home.html` の文例カードは表示しても遷移先を「準備中」表示にするか、フェーズ2まで非表示とする（§4.1）。

---

## 3. データ契約の追加

### 3.1 文書種別（`contracts.py`）

```python
class DocumentType(StrEnum):
    ANNUAL_PLAN = "annual_plan"
    MONTHLY_PLAN = "monthly_plan"
    WEEKLY_PLAN = "weekly_plan"   # 追加
    DAILY_PLAN = "daily_plan"     # 追加

DOCUMENT_TYPE_LABELS = {
    DocumentType.ANNUAL_PLAN: "年案",
    DocumentType.MONTHLY_PLAN: "月案",
    DocumentType.WEEKLY_PLAN: "週案",   # 追加
    DocumentType.DAILY_PLAN: "日案",    # 追加
}

DOCUMENT_TYPE_ALIASES = {
    "annual": DocumentType.ANNUAL_PLAN,
    "monthly": DocumentType.MONTHLY_PLAN,
    "weekly": DocumentType.WEEKLY_PLAN,  # 追加
    "daily": DocumentType.DAILY_PLAN,    # 追加
}
```

### 3.2 セクションキー（永続契約・叙述部）

`section_key` は表示ラベルが変わっても変更しない永続識別子。週・日プレフィックスで月案キーと独立させる。

#### 週案（`weekly_plan`）

| section_key | title | purpose | 文例流用元（月案項目） |
| --- | --- | --- | --- |
| `weekly_goal` | 今週のねらい | 月案を受けた1週間の中心目標 | `教育のねらい`/`養護のねらい` |
| `weekly_children_snapshot` | 前週の子どもの姿 | 直近の姿の捉え・連続性 | `前月末の子どもの姿` |
| `weekly_activities` | 主な活動・経験 | 週内に予想/用意する活動 | `活動内容` |
| `weekly_environment` | 環境構成 | 週の環境構成 | `環境構成・保育者の援助` |
| `weekly_support` | 保育者の援助・配慮 | 週の援助方針 | `環境構成・保育者の援助` |
| `weekly_health_safety` | 健康・安全への配慮 | 保健・安全面 | `健康・安全への配慮` |
| `weekly_family_collaboration` | 家庭連携 | 保護者との連携 | `家庭との連携` |
| `weekly_reflection_viewpoint` | 週の評価・反省 | 次週へつなぐ振り返り | `評価・反省` |

加えて曜日別グリッドを `schedule`（§3.4）で**常に**持つ。

#### 日案（`daily_plan`）

| section_key | title | purpose | 文例流用元（月案項目） |
| --- | --- | --- | --- |
| `daily_goal` | 本日のねらい | 教育/養護の中心目標 | `教育のねらい`/`養護のねらい` |
| `daily_children_snapshot` | 前日までの子どもの姿 | 直近の姿・連続性 | `前月末の子どもの姿` |
| `daily_main_activity` | 主な活動 | 中心活動・ねらいとの関係 | `活動内容` |
| `daily_health_safety` | 健康・安全への配慮 | 当日の保健・安全 | `健康・安全への配慮` |
| `daily_food_education` | 食育 | 給食・おやつの配慮 | `食育` |
| `daily_family_collaboration` | 家庭連携 | 送迎時の伝達 | `家庭との連携` |
| `daily_reflection_viewpoint` | 本日の評価・反省 | 翌日・翌週へつなぐ振り返り | `評価・反省` |

加えて時系列を `schedule`（§3.4）で**必ず**持つ。

### 3.3 接続（document 参照の契約化）

要約テキストだけでなく、**参照元 document の安定参照** を保持する。現行 store の id は `int`。

```python
# models.py PlanDocument に追加（すべて既定値あり）
parent_document_id: int | None = None          # 直近上位（週案→月案 / 日案→週案）
related_document_ids: list[int] = field(default_factory=list)  # 補助参照（日案→月案 等）
```

- 週案作成時: フォームで選んだ月案の id を `parent_document_id` に格納。
- 日案作成時: 週案の id を `parent_document_id`、必要なら月案 id を `related_document_ids` に格納。
- 接続の本文要約（`related_monthly_summary` 等）は従来どおりセクション本文に織り込みつつ、`source_refs` に `weekly.related_context` / `daily.related_context` を付す（§3.5）。
- 参照整合性: 参照先が存在しない/別クラスの場合は接続を張らず（`None`）、`confirmation_items` に「上位計画の接続未確認」を積む。

### 3.4 `schedule`（永続契約・表形式） ★本仕様の中核

「見た目の表」ではなく **永続契約**として定義する。`layout` / `ScheduleColumn.key` / `ScheduleRow.row_key` は破壊的変更対象（年案・月案の `section_key` と同格）。

#### 3.4.1 モデル（`models.py`）

```python
@dataclass(slots=True)
class ScheduleColumn:
    key: str        # 永続キー（後述の固定集合）
    title: str      # 表示名

@dataclass(slots=True)
class ScheduleCell:
    body: str = ""
    source_refs: list[str] = field(default_factory=lambda: ["form.schedule"])
    needs_confirmation: bool = False
    editor_note: str | None = None

    @property
    def evidence_tags(self) -> list[str]:
        return evidence_tags_for(self.source_refs)

@dataclass(slots=True)
class ScheduleRow:
    row_key: str               # 永続・意味ベースキー（時刻は持たない、§3.4.3）
    label: str                 # 表示名（編集可）: "8:00 順次登園" / "月"
    order: int                 # 並び順（安定ソート用、ラベル編集と独立）
    start_time: str | None = None  # 任意 "08:00"（日案のみ。表示/将来の時刻計算用）
    cells: dict[str, ScheduleCell] = field(default_factory=dict)  # column.key -> cell

@dataclass(slots=True)
class PlanSchedule:
    layout: str                # "daily_timeline" | "weekly_grid"
    columns: list[ScheduleColumn]
    rows: list[ScheduleRow]    # 表示順は row.order で安定ソート
```

> **セル単位の根拠**: セルは `dict[str, ScheduleCell]` とし、`body` だけでなく `source_refs` / `needs_confirmation` をセル単位で持てる（文例や上位計画からセルを生成する将来拡張に対応）。

#### 3.4.2 `layout` と `column.key`（固定集合）

| layout | 用途 | 固定 column.key（順序固定） |
| --- | --- | --- |
| `daily_timeline` | 日案の時系列 | `env`（環境構成） / `children`（予想される子どもの姿） / `support`（保育者の援助・配慮） |
| `weekly_grid` | 週案の曜日別 | `activity`（主な活動・予想される活動） / `support`（環境・保育者の援助） |

#### 3.4.3 `row_key` 方針（揺れの固定）

**意味ベースで固定**（時刻ベースにしない）。理由: 時刻はラベル編集で変わるため、キーに含めると不安定。

- 日案（3〜5歳児・標準）: `t_arrival` / `t_free_am` / `t_meeting` / `t_main` / `t_lunch` / `t_nap` / `t_free_pm` / `t_departure`
- 日案（0〜2歳児・標準、§7.3）: `t_arrival` / `t_health_check` / `t_care_am`（授乳・離乳食/おむつ） / `t_free_am` / `t_lunch` / `t_nap` / `t_care_pm` / `t_free_pm` / `t_departure`
- 週案: `mon` / `tue` / `wed` / `thu` / `fri`（`sat` は作成時オプション、§7.4 / §7.5）

`label` は表示・編集用、`order` が並び順の唯一の根拠、`start_time` は日案の時刻表示・将来計算用（編集可、キーに非依存）。

#### 3.4.4 既定ひな型（生成時）

日案 `daily_timeline`（3〜5歳児）行の既定 `label` / `start_time` / `children` ひな型:

| row_key | order | start_time | label | 既定 `children` |
| --- | --- | --- | --- | --- |
| `t_arrival` | 10 | 08:00 | 順次登園・視診 | 健康観察、持ち物の始末 |
| `t_free_am` | 20 | 09:00 | 午前の遊び | 好きな遊びを選んで楽しむ |
| `t_meeting` | 30 | 10:00 | 朝の集まり | 出席・歌・今日の予定 |
| `t_main` | 40 | 10:15 | 主な活動 | （`daily_main_activity` と連動） |
| `t_lunch` | 50 | 11:30 | 昼食・給食 | 手洗い・配膳・食事（食育連動） |
| `t_nap` | 60 | 12:45 | 午睡 | 休息 |
| `t_free_pm` | 70 | 15:00 | 午後の遊び | 落ち着いて過ごす |
| `t_departure` | 80 | 16:30 | 順次降園 | 片付け・降園準備・保護者へ伝達 |

週案 `weekly_grid` は `mon`〜`fri`（order 10/20/30/40/50）、`activity`/`support` の各セルは空（`body=""`）で初期化。

#### 3.4.5 生成・保存・API の統一（任意/必須の確定）

| 種別 | schedule 生成 | 保存 | API 出力 |
| --- | --- | --- | --- |
| `daily_plan` | 必須（`daily_timeline`） | 必ず保存 | 必須出力 |
| `weekly_plan` | 必須（`weekly_grid`、**空セル可**） | 必ず保存（`None` にしない） | 必須出力 |
| `annual_plan` / `monthly_plan` | 生成しない | `schedule = None` | **キー自体を省略**（`null` ではなく省略、§3.6 で固定） |

#### 3.4.6 確認対象セル（確認フロー連携）

空欄は許容するが、**最低確認セル** を生成時に `needs_confirmation=True` で立て、`confirmation_items` に積む:

- 日案: `t_main.children` と `t_main.support`（主活動の姿と援助）。`daily_main_activity_note` 未入力なら必ず確認対象。
- 週案: グリッドは必須確認なし（叙述の `weekly_goal` が確認を担う）。

### 3.5 `source_refs` プレフィックスの追加（`contracts.py`）

`SOURCE_REF_PREFIX_TAGS` に **`weekly.` / `daily.` を追加**（タグは「入力」、`annual.`/`monthly.` と同方針）。

```python
SOURCE_REF_PREFIX_TAGS = {
    "profile.": "園方針",
    "knowledge.": "公的根拠",
    "form.": "入力",
    "annual.": "入力",
    "monthly.": "入力",
    "weekly.": "入力",     # 追加（例: weekly.related_context）
    "daily.": "入力",      # 追加（例: daily.related_context）
    "bunrei.": "文例",
    "facility.": "園文例",
    "outline.": "AI構成",
    "linking.": "AI構成",
}
```

### 3.6 JSON シリアライズ契約（`serializers.py`）

- 関数を `serialize_document(document) -> dict` に集約。`schedule` は `serialize_schedule(schedule) -> dict | None` を分離。
- **null/省略方針**: `schedule` が `None`（年案/月案）の場合は **キー自体を出力しない**（`"schedule": null` も出さない）。週案/日案は必ず `schedule` キーを含む。
- `target_week` / `week_start_date` / `target_date` / `parent_document_id` / `related_document_ids` も、値が `None`/空のときは出力しない（後方互換: 年案/月案の出力は従来と完全一致）。
- `schedule` 出力形:
  ```json
  {
    "layout": "daily_timeline",
    "columns": [{"key": "env", "title": "環境構成"}, ...],
    "rows": [
      {"row_key": "t_main", "label": "主な活動", "order": 40, "start_time": "10:15",
       "cells": {"children": {"body": "...", "evidence_tags": ["入力"], "needs_confirmation": true},
                 "support": {"body": "...", "evidence_tags": ["入力"], "needs_confirmation": true}}}
    ]
  }
  ```

### 3.7 期間・年度フィールドと算出ルール

```python
# PlanDocument 追加
target_week: str | None = None       # 週案: HTML week 入力 "YYYY-Www"（ISO週）
week_start_date: str | None = None   # 週案: 週開始日 "YYYY-MM-DD"（月曜）
target_date: str | None = None       # 日案: "YYYY-MM-DD"
age_class: str | None = None         # 週案/日案: "5歳児" 等（フォーム保持、推定しない）
```

**week_start_date / 年度 / 月の算出ルール（曖昧さ排除）**:

- `target_week` は HTML `<input type="week">` の `YYYY-Www`（ISO-8601 週番号、**月曜開始**）。
- `week_start_date` = その ISO 週の **月曜日**（`datetime.fromisocalendar(year, week, 1)`）。
- **年度（`school_year`）** = `week_start_date` の月が 4 月以上なら同年、1〜3 月なら前年（日本の年度）。
- **文例フィルタ用の「月」** = その週の **木曜日の月**（ISO 週は木曜の属する年に帰属する慣行に合わせ「過半日」基準で安定）。年度またぎ週もこの規則で一意に決まる。
- 文例画面では算出値を初期表示しつつ、**ユーザーが月を上書き可能**（§6.4）。

---

## 4. 画面・UI 仕様（現行UI踏襲）

既存クラス（`toolbar-band` / `work-grid` / `action-panel` / `form-layout` / `form-panel` / `field-grid` / `report-sheet` / `report-section` / `status` / `notice` / `inline-note` / `button--*`）を再利用。新規CSSは表組み（schedule）周りのみ。

### 4.1 ダッシュボード `home.html`

`work-grid` に週案・日案カードを追加。**view_only ユーザーには「年案/月案/週案/日案」作成カードを非表示**（§7.4）。文例カードは **フェーズ2で表示**（MVPでは出さない）。

```html
<a class="action-panel" href="/weekly-plans/new">
  <span class="action-panel__label">週間計画</span>
  <strong>週案</strong>
  <span>月案を受けて1週間の見通し（ねらい・活動・環境・援助）を作成します。</span>
</a>
<a class="action-panel action-panel--accent" href="/daily-plans/new">
  <span class="action-panel__label">日間計画</span>
  <strong>日案</strong>
  <span>1日の生活の流れ（時系列）と養護・教育のねらいを作成します。</span>
</a>
```

最近の帳票一覧は全種別表示済み。バッジは `document.document_type_label` がそのまま「週案/日案」を返す。

### 4.2 週案フォーム `templates/weekly_plans/form.html`（新規）

`monthly_plans/form.html` を踏襲。

- **基本情報**: 対象週 `<input type="week" name="target_week" required>` / クラス `classroom_ref` / **年齢 `age_class`（`select`、`age_class_options("月案")`）** / 作成者
- **土曜を含む**: `<input type="checkbox" name="include_saturday">`（既定 off、§7.5）
- **月案との接続**: `_monthly_documents_for_user(user)` を `reference-list` で表示し、**選択は `<select name="parent_document_id">`**（先頭は「接続しない」）。`related_monthly_summary`（textarea）。
- **今週の入力**: `previous_week_reflection` / `current_children_snapshot` / `weekly_activities_note` / `seasonal_context` / `family_context` / `class_notes`
- 送信先 `POST /weekly-plans`。

### 4.3 日案フォーム `templates/daily_plans/form.html`（新規）

- **基本情報**: 対象日 `<input type="date" name="target_date" required>` / クラス / **年齢 `age_class`（select）** / 作成者
- **週案・月案との接続**: 週案参照リスト + `<select name="parent_document_id">`。`related_weekly_summary`（textarea）。
- **本日の入力**: `daily_main_activity_note` / `current_children_snapshot` / `seasonal_context` / `health_notes` / `family_context`
- 時系列詳細は作成後の編集画面で調整（生成時にひな型自動投入）。
- 送信先 `POST /daily-plans`。

### 4.4 詳細 `documents/detail.html`（拡張）

- `report-sheet__meta` の期間表示:
  ```jinja
  <span>
    {% if document.target_week %}{{ document.target_week }}（{{ document.week_start_date }}〜）{% endif %}
    {% if document.target_date %}{{ document.target_date }}{% endif %}
  </span>
  ```
- **schedule の挿入位置（明示）**:
  - `layout == "daily_timeline"`: **叙述セクションの前**（本日のねらい等の直後、時系列を主役にする）→ 具体的には `report-sheet__meta` の直後に schedule、その後に叙述ループ。
  - `layout == "weekly_grid"`: **叙述セクションの後**（週のまとめとして末尾）。
  - 実装は `document.schedule and document.schedule.layout` で分岐し、テンプレートの先頭ブロック/末尾ブロックに同一マクロ `render_schedule(document.schedule)` を条件配置。
- 表マクロ（横スクロール・改行保持・印刷対応、§4.7）:

```jinja
{% macro render_schedule(schedule) %}
  <section class="report-section report-schedule">
    <div class="report-section__heading"><h2>
      {{ "1日の流れ" if schedule.layout == "daily_timeline" else "週の活動" }}
    </h2></div>
    <div class="schedule-scroll">
      <table class="schedule-table">
        <thead><tr>
          <th>{{ "時間" if schedule.layout == "daily_timeline" else "曜日" }}</th>
          {% for col in schedule.columns %}<th>{{ col.title }}</th>{% endfor %}
        </tr></thead>
        <tbody>
          {% for row in schedule.rows|sort(attribute="order") %}
            <tr>
              <th scope="row">{{ row.label }}</th>
              {% for col in schedule.columns %}
                {% set cell = row.cells.get(col.key) %}
                <td>{{ cell.body if cell else "" }}</td>
              {% endfor %}
            </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </section>
{% endmacro %}
```

### 4.5 編集 `documents/edit.html`（拡張）

- 叙述セクション編集は既存のまま。
- `schedule` がある場合、**サーバが保持する行・列を走査して** `textarea` を描画。フォーム名は **二重アンダースコア区切り** `cell__{row_key}__{column_key}`（`row_key` 内の単一 `_` と衝突しない、§5.4）。行ラベルは `rowlabel__{row_key}`、開始時刻は `rowtime__{row_key}`。
- POST 先は既存 `POST /documents/{id}` を流用。読取は **キー名をパースせず、`document.schedule` の既存 row/col を権威として** `form.get(f"cell__{row.row_key}__{col.key}")` で取得（§5.4）。
- 行追加/削除はフェーズ3。MVP は固定ひな型のセル本文・ラベル・時刻編集のみ。

### 4.6 [フェーズ2] 文例選択 `templates/bunrei/weekly.html` / `daily.html`（新規）

`bunrei/monthly.html` を流用。条件は「年齢（`age_class_options("月案")`）」「月」。POST 後は `/documents/{id}/edit` へ遷移し、日案は生成後に時系列ひな型を付与（§6.4）。

### 4.7 新規CSS（`static/styles.css` 追記）

```css
.schedule-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.schedule-table { width: 100%; border-collapse: collapse; margin-top: 12px; min-width: 640px; }
.schedule-table th, .schedule-table td {
  border: 1px solid var(--line, #d9d9e3); padding: 8px 10px;
  vertical-align: top; text-align: left; font-size: 0.92rem;
  white-space: pre-wrap;            /* textarea の改行を保持 */
  word-break: break-word;
}
.schedule-table thead th { background: var(--surface-muted, #f4f4f8); }
.schedule-table th[scope="row"] { white-space: nowrap; width: 8rem; }
@media print {
  .schedule-scroll { overflow: visible; }            /* 印刷時は横スクロール解除 */
  .schedule-table { min-width: 0; }
  .schedule-table thead { display: table-header-group; } /* ページ跨ぎでヘッダ繰り返し */
  .schedule-table tr { page-break-inside: avoid; }
}
```

既存のカラー変数/トーンに合わせ、独自色は増やさない。

---

## 5. ルーティング・サーバ仕様

### 5.1 週案・日案ルート（`web/routers/plans.py`）

| method | path | 権限 | 説明 |
| --- | --- | --- | --- |
| GET | `/weekly-plans/new` | view可（view_onlyはカード非表示だがGETは閲覧可、§7.4） | 週案フォーム。月案参照リスト。 |
| POST | `/weekly-plans` | `can_edit` | バリデーション→`generate_weekly_plan`→保存→`/documents/{id}` |
| GET | `/daily-plans/new` | view可 | 日案フォーム。週案参照リスト。 |
| POST | `/daily-plans` | `can_edit` | バリデーション→`generate_daily_plan`→保存→`/documents/{id}` |

参照リストヘルパ（既存 `_annual_documents_for_user` と同型、**絞り込み付き**、§7.6）:
```python
def _monthly_documents_for_user(user, *, classroom_ref=None, limit=8): ...
def _weekly_documents_for_user(user, *, classroom_ref=None, limit=8): ...
# document_type フィルタ + classroom_ref 一致 + archived 除外 + updated_at 降順 + limit
```

### 5.2 [フェーズ2] 文例ルート（`web/routers/bunrei.py`）

| method | path | 説明 |
| --- | --- | --- |
| GET/POST | `/bunrei/weekly` | 週案文例選択（年齢・月）。`weekly_candidate_groups` |
| GET/POST | `/bunrei/daily` | 日案文例選択（年齢・月）。`daily_candidate_groups` |

POST は `create_monthly_from_bunrei` と同型 + 生成後に schedule 付与（§6.4）。

### 5.3 [フェーズ2] 園文例の受け入れ拡張（一貫更新）

`plan_type` 妥当値を `{"年案","月案"}` → `{"年案","月案","週案","日案"}` に拡張。**import 側だけでなく以下を一貫更新**:
- `services/bunrei.py`: `import_facility_examples` / `add_facility_example` の検証、警告文言。
- `web/routers/bunrei.py`: `create_facility_bunrei` の plan_type 既定/受理、リダイレクト分岐（`週案`→`/bunrei/weekly`、`日案`→`/bunrei/daily`）。
- `templates/bunrei/facility_new.html`: plan_type の `select` 選択肢に「週案/日案」を追加。
- 取り込みテンプレート注記・`README.md`・`docs/integration-contract.md` の取り込み列説明。
- テスト（§9）。

### 5.4 保存層（`store.py`）

- `create` / `get` / `list` は変更不要（`document_type` フィルタは Enum 追加に自動追従）。
- `update_document` を schedule 対応に拡張。**フォーム名をパースせず、document が持つ row/col を走査**して安全に読む:
  ```python
  def update_document(..., schedule_form: Mapping[str, str] | None = None):
      ...
      if document.schedule and schedule_form is not None:
          for row in document.schedule.rows:
              new_label = schedule_form.get(f"rowlabel__{row.row_key}")
              if new_label is not None: row.label = new_label.strip() or row.label
              new_time = schedule_form.get(f"rowtime__{row.row_key}")
              if new_time is not None: row.start_time = new_time.strip() or None
              for col in document.schedule.columns:
                  val = schedule_form.get(f"cell__{row.row_key}__{col.key}")
                  if val is None: continue
                  cell = row.cells.setdefault(col.key, ScheduleCell())
                  cell.body = val
                  # 本文が入ったら確認解除（最低確認セルのみ対象）
                  if cell.needs_confirmation and val.strip():
                      cell.needs_confirmation = False
  ```
- 叙述セクションのみ更新時に `schedule` を壊さない（`schedule_form is None` で no-op）。

### 5.5 JSON API（`serializers.py`）

§3.6 のとおり。`GET /api/documents/{id}` は週案/日案で `schedule` 等を含み、年案/月案の出力は従来と完全一致（後方互換）。

---

## 6. 生成ロジック仕様（`services/generators.py`）

### 6.1 共通方針

- `clean_text` / `confirmation_items` / `_section` / `evidence_tags_for` を流用。
- **`age_class` はフォーム値を使用**（`classroom_ref` から推定しない）。未指定時はフォーム必須化で防ぎ、生成側は `data["age_class"]` をそのまま採用。
- 接続: フォームの `parent_document_id` を `store.get` で検証し、クラス一致時のみ `parent_document_id` に設定。要約テキストは冒頭セクションに織り込み、`source_refs` に `weekly./daily.related_context` を付す。
- 未入力の中心情報は `needs_confirmation` + `editor_note` + `confirmation_items`（既存方針）。

### 6.2 `generate_daily_plan(data, user) -> PlanDocument`

入力: `target_date`(必須) / `age_class`(必須) / `classroom_ref` / `class_name` / `owner_name` / `parent_document_id` / `related_weekly_summary` / `current_children_snapshot` / `daily_main_activity_note` / `seasonal_context` / `health_notes` / `family_context`

処理:
1. 叙述セクション（§3.2 日案）を生成。`daily_goal` に `related_weekly_summary`＋`daily_main_activity_note`＋`current_children_snapshot` を織り込む。
2. `attach_daily_schedule(document, age_class, main_activity_note)`:
   - 3〜5歳児: §3.4.4 標準8行。
   - 0〜2歳児: §3.4.3 簡略版（§7.3 個別配慮の具体化）。
   - `t_main` の `children`/`support` に `daily_main_activity_note` を反映。未入力なら `t_main.children` / `t_main.support` を `needs_confirmation=True`（§3.4.6）。
   - 各セル `source_refs=["form.schedule"]`。
3. `schedule.layout="daily_timeline"`、`columns=[env, children, support]`。
4. `target_date` / `age_class` を保存。`title=f"{target_date} 日案（{class_name}）"`。

### 6.3 `generate_weekly_plan(data, user) -> PlanDocument`

入力: `target_week`(必須) / `age_class`(必須) / `include_saturday` / `classroom_ref` / `class_name` / `owner_name` / `parent_document_id` / `related_monthly_summary` / `previous_week_reflection` / `current_children_snapshot` / `weekly_activities_note` / `seasonal_context` / `family_context` / `class_notes`

処理:
1. `week_start_date` / `school_year` / 月を §3.7 ルールで算出。
2. 叙述セクション（§3.2 週案）を生成。`weekly_goal` に接続・前週反省・現在の姿を織り込む。
3. `weekly_grid` を**常に**生成: 行 `mon`〜`fri`（`include_saturday` なら `sat` 追加）、列 `activity`/`support`、全セル空（`weekly_activities_note` があれば `mon.activity` 等に薄く配置可、なくても可）。
4. `target_week` / `week_start_date` / `age_class` を保存。`title=f"{week_start_date}週 週案（{class_name}）"`。

### 6.4 [フェーズ2] 文例からの生成（`services/bunrei.py`）

- `WEEKLY_SECTION_ITEMS` / `DAILY_SECTION_ITEMS` を `MONTHLY_SECTION_ITEMS` と同型で定義（§3.2「文例流用元」に準拠）。
- 共通文例は `plan_type="月案"`、園文例は `plan_type="週案"/"日案"` を参照（`_fetch_examples` を plan_type 引数で分離）。
- **年齢候補は `age_class_options("月案")` を使用**（週案/日案 plan_type の年齢一覧が共通文例に無いため、明示的に月案を参照）。
- **重複対策**: `weekly_environment` と `weekly_support` は同じ月案項目 `環境構成・保育者の援助` を引くため、候補は **example id で重複除外**し、両セクションに同一候補が並ばないようにする（または UI 上「環境・援助」を1グループに統合して表示し、選択結果を両 `section_key` に振り分ける）。
- 週案の **月判定** は §3.7（木曜の月）を初期値とし、文例画面の `month` セレクタでユーザー上書き可能。
- `build_document_from_bunrei` は **署名を拡張**（`target_week` / `week_start_date` / `target_date` / `age_class` / `parent_document_id` を受け取り `PlanDocument` に設定）。`schedule` はこの関数では作らず、**呼び出し側（router）が生成後に `attach_daily_schedule` / `attach_weekly_grid` を呼ぶ**責務とする（責務分離を明記）。

---

## 7. バリデーション・業務ルール

### 7.1 対象期間の必須化（フォールバック廃止）

- 週案 `target_week`・日案 `target_date` は **必須**。自動フォールバックはしない。
- Web: 未指定/不正値は **同フォームを再表示**（入力値保持 + `notice` エラー、HTTP 200）。
- JSON API（将来 `POST /api/...`）: **422 Unprocessable Entity**。
- 不正値の例: `target_week` が ISO 週として解釈不能、`target_date` が日付として解釈不能、年度範囲外。

### 7.2 権限・接続整合

- `require_can_edit` / `require_classroom_access` を必ず通す。
- `parent_document_id` は `store.get` で存在確認し、**同一クラス**のときのみ接続。不一致/不在は `None`＋確認項目。

### 7.3 0〜2歳児の個別配慮（現場適合）

0〜2歳児日案は「個別の生活リズム」を中核とする。標準行に加え、以下を **既定の列内容ガイド**として `support` セルのひな型に明記:
- `t_care_am` / `t_care_pm`: **授乳・離乳食 / 排泄（おむつ交換） / 睡眠** を個別に記録する旨をプレースホルダ表示。
- 叙述に `daily_*` の個別配慮を促す `editor_note`（「一人ひとりの生活リズム・健康状態に応じて記録」）。
- 1歳児クラスは午前の活動と午睡の比重を調整（`t_nap` の `start_time` 既定を早める）。

### 7.4 view_only のUX・土曜表示

- **view_only**: 作成カード/フォームへの導線（`home.html` のカード）は非表示。GET フォームURL直叩きは閲覧可とするが、送信ボタンを非活性化し POST は 403。
- **土曜**: 現行モデルに園設定がないため、MVP は **作成フォームの `include_saturday` チェック（document 単位）** で対応。既定は Mon–Fri。園全体設定モデルはフェーズ3。

### 7.5 行事・祝日・休園日・保育時間

- 週案グリッドの祝日/休園日: MVP は **セル自由記述**（例: `mon.activity="祝日のため休園"`）。カレンダー連携はスコープ外。
- 保育時間（長時間/短時間/延長保育）: MVP は **標準時間割固定**。延長・短時間の分岐はフェーズ3で `schedule` のひな型差し替えとして拡張。

### 7.6 参照リストの絞り込み

参照リスト（接続候補）は増加に備え、**クラス一致・archived 除外・`updated_at` 降順・上限8件**で表示。日案では `target_date` を含む週の週案を上位に並べる（同週優先）。

---

## 8. 実装タスク（ファイル別チェックリスト）

- [ ] `contracts.py`: 種別/ラベル/alias、`SOURCE_REF_PREFIX_TAGS` に `weekly.`/`daily.`、`WEEKLY_SECTIONS`/`DAILY_SECTIONS` と `section_definitions()` 分岐、日案/週案ひな型定数（行・列・order・start_time）。
- [ ] `models.py`: `ScheduleColumn`/`ScheduleCell`/`ScheduleRow`/`PlanSchedule`、`PlanDocument` に `target_week`/`week_start_date`/`target_date`/`age_class`/`parent_document_id`/`related_document_ids`/`schedule`（全て既定値あり）。
- [ ] `services/generators.py`: `generate_weekly_plan`/`generate_daily_plan`/`attach_daily_schedule`/`attach_weekly_grid`、週開始日・年度・月の算出ユーティリティ。
- [ ] `web/routers/plans.py`: 4ルート + 絞り込み付き参照リストヘルパ + バリデーション（必須/再表示/422）。
- [ ] `store.py`: `update_document` の schedule 対応（キー非パース・row/col 走査）。
- [ ] `serializers.py`: `serialize_schedule` + null/省略方針 + 後方互換。
- [ ] `templates/weekly_plans/form.html`・`daily_plans/form.html` 新規（年齢select・接続select・土曜チェック）。
- [ ] `templates/home.html`: 週案/日案カード（view_only 非表示、文例カードはフェーズ2）。
- [ ] `templates/documents/detail.html`: 期間表示 + `render_schedule` マクロ（位置分岐・横スクロール・改行・印刷）。
- [ ] `templates/documents/edit.html`: schedule セル/ラベル/時刻編集（`cell__`/`rowlabel__`/`rowtime__`）。
- [ ] `static/styles.css`: `.schedule-scroll` / `.schedule-table` + 印刷規則。
- [ ] `docs/integration-contract.md`: 種別/セクション/`schedule`契約/接続ID/最小データ形/破壊的変更に追記。
- [ ] `README.md`: 主な画面・文書種別に週案/日案を追記。
- [ ] [フェーズ2] `services/bunrei.py`/`web/routers/bunrei.py`/`templates/bunrei/*`: 文例候補・園文例 plan_type 一貫更新。

---

## 9. テスト方針（`tests/`）

**契約**
- `normalize_document_type("weekly"/"daily")` が正規化。`section_definitions(WEEKLY_PLAN/DAILY_PLAN)` が想定キー列を返す。
- `evidence_tags_for(["weekly.related_context"])` / `["daily.related_context"]` が `["入力"]`。

**生成**
- `generate_weekly_plan` が週案叙述一式 + `schedule.layout=="weekly_grid"`（常に非 None、`mon`〜`fri`、`include_saturday` で `sat` 追加）。
- `generate_daily_plan` が日案叙述 + `schedule.layout=="daily_timeline"`。年齢で行構成が切替（0〜2歳に `t_care_am`）。`daily_main_activity_note` 未入力時 `t_main.children/support` が `needs_confirmation` かつ `confirmation_items` に積まれる。

**期間算出**
- `target_week` の不正値で再表示（Web）/422（API 将来）。
- ISO 週→`week_start_date`（月曜）算出、年度（4月境界）判定、年度またぎ週の月判定（木曜基準）。

**ルーティング**
- `POST /weekly-plans` / `/daily-plans` が 303 で `/documents/{id}`、`document_type` 正。`view_only` は POST 403、GET は閲覧可。クラス外 `parent_document_id` は接続されず確認項目化。
- 参照リストが archived 除外・クラス一致・上限。

**保存**
- `update_document` で schedule セル本文/ラベル/時刻が更新。`row_key` に `_` を含む（`t_free_am`）場合も `cell__t_free_am__support` が正しく保存。
- 叙述のみ更新（`schedule_form is None`）で schedule が不変。最低確認セルに本文を入れると `needs_confirmation` 解除。

**API**
- 日案/週案で `schedule` を含む。年案/月案では `schedule`/期間キーを**省略**（`null` を出さない）= 従来出力と一致（後方互換スナップショット）。

**UI/印刷**
- detail テンプレートが schedule 表を描画（日案=前/週案=後の位置）。改行（`pre-wrap`）保持。`thead` 印刷繰り返し。

**[フェーズ2] 文例**
- `weekly_candidate_groups`/`daily_candidate_groups` が月案文例を項目マッピングで返す。`weekly_environment`/`weekly_support` の候補が id 重複しない。
- 年齢候補が `age_class_options("月案")` 由来。週案の月がユーザー上書き可能。
- 園文例 `plan_type="週案"/"日案"` の追加フォーム・import・絞り込み・警告文言・リダイレクトが一貫。

---

## 10. 段階的リリース計画（§2.3 と整合）

1. **フェーズ1（MVP）**: 契約・モデル・生成・週案/日案フォーム・詳細表示・印刷・`schedule` の生成/表示/セル編集・`parent_document_id` 接続と参照リスト・必須バリデーション・API シリアライズ。
2. **フェーズ2**: 文例選択（`/bunrei/weekly` `/bunrei/daily`）、園文例の週案/日案受け入れ（一貫更新）、`weekly_environment`/`weekly_support` の重複除外。
3. **フェーズ3**: 週案↔日案の自動連携（週案曜日行→日案生成、日案評価→週案集約）、日案時系列の行追加/削除UI、園全体設定（土曜/保育時間/延長）、永続DB化に伴う `schedule` シリアライズ確定。

---

## 11. 非破壊性の確認（連携契約）

- 既存 `document_type` / `status` / `section_key` / `source_refs` プレフィックスは変更しない（`weekly.`/`daily.` は**追加**）。
- 追加する種別・`section_key`・`schedule` 関連キー（`layout`/`column.key`/`row_key`）は新規追加のみ。これらも今後は永続契約とし、変更は破壊的変更として扱う（`integration-contract.md` に明記）。
- `PlanDocument` の新フィールドは明示フィールドかつ既定値あり（slots 対応、§2.2）。年案・月案の生成・表示・API 出力は従来と完全一致（schedule/期間キーは省略）。
- よって本仕様は破壊的変更に該当せず、ADR/migration は不要（契約ドキュメントへの追記のみ）。

---

## 12. 追加仕様（負担低減と豊かな計画づくり）

本章は、厚生労働省「保育分野の業務負担軽減・業務の再構築のためのガイドライン」（令和3年3月、以下「業務負担軽減ガイドライン」）を受けた **追加仕様** です。§1〜§11 の週案・日案作成仕様を置き換えるものではなく、MVP実装時の設計制約・優先順位・UI判断に反映する補助仕様として扱います。

本機能は、書類作成時間を短縮するだけでなく、保育者が **子どもの姿・ねらい・環境・援助・振り返りをつなげて考えやすくすること** で、短期計画の質を高めることを目的とする。最低限項目は「削るための上限」ではなく、豊かな計画を支える土台として扱う。

### 12.1 参照資料と反映範囲

参照資料:
- 厚生労働省「保育分野の業務負担軽減・業務の再構築のためのガイドライン」令和3年3月。
- 参照箇所: p.6（計画・記録など書類作成業務の見直しとICT活用）、p.18〜21（ICT活用と情報共有）、p.26〜27（計画・記録・書類業務の見直し）、p.28（ノンコンタクトタイム/タイムマネジメント）、p.40〜41（最低限記載することが望ましい項目）、p.61（週・日など短期的な指導計画の最低限項目）、p.63（週案・日案作成と指導計画評価が書類作成業務であること）。

反映範囲:
- 週案・日案の **項目設計**、**入力導線**、**確認フロー**、**上位計画からの転記削減**、**評価・反省の接続** に反映する。
- 監査・行政提出様式そのものの再現、写真記録、保護者連絡、登降園/出退勤連携、タイムスタディ機能は本仕様の対象外。ただし将来拡張の根拠として記録する。

### 12.2 追加設計原則

業務負担軽減ガイドラインは、単なる業務省略ではなく、保育の質を確保しながら計画・記録業務を見直すことを求める。このため、週案・日案機能では「入力量を減らす」ことだけを目的にせず、少ない入力から保育者の思考が深まるよう以下を設計原則とする。

- **重複入力を避ける**: 月案→週案→日案で同じ情報を再入力させない。`parent_document_id` と要約入力を使い、必要な文脈だけを引き継ぐ。
- **最低限項目を土台に豊かに展開する**: 週案・日案の必須確認は、ガイドライン p.61 の最低限項目に対応する項目を中心に置く。ただし、子どもの具体的な姿、ねらいとのつながり、環境、援助、個別配慮、家庭・職員間連携、振り返りを段階的に深められる余白を残す。
- **計画・記録・反省を分断しない**: 短期的な計画は、実践後の記録・反省とつながる様式にする。`weekly_reflection_viewpoint` / `daily_reflection_viewpoint` は次期計画の入力候補として扱えるよう、section_key を永続化する。
- **紙様式の単純なICT化にしない**: 既存の紙帳票をそのまま画面化せず、入力負担と現場での使いやすさを優先する。
- **クラス担任全員で扱える様式にする**: 作成者1人に依存しないよう、編集画面はセクション本文と `schedule` セルを分け、短時間で分担編集できる構造にする。
- **保育の質を落とさない**: 項目削減によって、子どもの姿・ねらい・内容・環境構成・援助/配慮が欠落しないよう、確認フローで補う。

### 12.3 最低限項目との対応

業務負担軽減ガイドライン p.61 では、週などの単位の計画として「子どもの姿」「ねらい及び内容」「環境構成・援助・配慮」、日などの単位の計画として「1日のねらい、主な保育の内容、1日の流れ」「環境構成・援助・配慮」が示されている。本仕様では次のように対応させる。

| ガイドライン上の最低限項目 | 週案での対応 | 日案での対応 |
| --- | --- | --- |
| 子どもの姿 | `weekly_children_snapshot` | `daily_children_snapshot`（任意だが未入力時は確認対象候補） |
| ねらい及び内容 | `weekly_goal` / `weekly_activities` | `daily_goal` / `daily_main_activity` |
| 環境構成・援助・配慮 | `weekly_environment` / `weekly_support` / `schedule.support` | `schedule.env` / `schedule.support` / `daily_health_safety` |
| 1日の流れ | 対象外（週案は `weekly_grid`） | `schedule.layout=="daily_timeline"` |
| 振り返り・改善 | `weekly_reflection_viewpoint` | `daily_reflection_viewpoint` |

MVPでは既存の詳細なセクション構成（§3.2）を維持する。ただし UI 上は最低限項目を優先して表示し、家庭連携・食育・行事等は入力負担が過大にならないよう任意入力・生成補助として扱う。最低限項目は、計画を薄くするための削減目標ではなく、計画を豊かにするために必ず押さえる起点である。

### 12.4 入力負担軽減の画面仕様

- 週案フォーム・日案フォームでは、必須入力を `target_week` / `target_date`、`classroom_ref`、`age_class`、作成者、中心となる姿・ねらい・活動に限定する。
- 上位計画から引き継げる情報は `parent_document_id` と参照リストで選択させ、本文の再入力を求めない。要約 textarea は空欄許容とし、未入力時は生成側が「上位計画の接続未確認」を確認項目に積む。
- `schedule` は全セル入力を必須にしない。日案では `t_main.children` / `t_main.support` のみ最低確認セルとし、他セルは後から編集できる空欄を許容する。
- 週案 `weekly_grid` は、初期状態では空セル可とする。月案内容を機械的に曜日へ展開しすぎず、現場が必要な曜日だけ記入できるようにする。
- 編集画面では、叙述セクションと `schedule` を別ブロックに分ける。担任間で分担しやすいよう、各セルのラベル・時刻・本文を個別編集できる。
- 空欄は「手抜き」ではなく、観察・担任間対話・実践後の振り返りで育てる余白として扱う。生成時は空欄を責めるのではなく、深める観点を `needs_confirmation` / `editor_note` として示す。

### 12.5 重複削減と再利用ルール

- 同一内容を複数セクションへ自動複製しない。必要な場合は `source_refs` で出所を残し、本文は短く要約する。
- 月案から週案へは `monthly.related_context`、週案から日案へは `weekly.related_context` を用いる。`daily.related_context` は日案を次期計画が参照する場合のために予約する。
- `weekly_environment` と `weekly_support` は意味が近いが、環境（人・物・場）と援助（保育者の関わり）を分ける。生成時に同文を入れない。
- `daily_health_safety` と `schedule.support` が重複しないよう、前者は当日全体の健康・安全方針、後者は時間帯ごとの援助・配慮として使い分ける。
- 評価・反省セクションは、次の週案・日案生成時の参照候補とする。フェーズ3の自動連携で `source_refs=["weekly.reflection", "daily.reflection"]` を追加できるよう予約する。

### 12.6 計画・記録・反省の一体化（将来拡張を見据えたMVP制約）

業務負担軽減ガイドライン p.26 は、短期的な計画について「記録を含めた様式」とし、計画・実践の記録・反省を一つの様式にする考え方を示している。MVPでは記録機能そのものは追加しないが、以下の制約を守る。

- `weekly_reflection_viewpoint` / `daily_reflection_viewpoint` は空欄でも作成し、後から編集可能にする。
- `confirmation_items` は作成時の不足だけでなく、実践後に確認すべき観点を残す用途にも使えるよう、文言を「確認が必要な入力」に限定しすぎない。
- 日案の `schedule` は「計画」だが、将来の実践記録を同じ行・列に紐づけられるよう、`row_key` / `column.key` を永続契約とする。
- APIでは `schedule.rows[].row_key` と `schedule.rows[].cells` を安定出力し、将来の記録・評価テーブルが同じキーを参照できるようにする。

### 12.7 業務改善観点の非機能要件

- **作成時間の短縮**: 手入力フォームは1画面で完結し、必須項目を増やしすぎない。長文入力を前提にしない。
- **思考の支援**: 生成本文・確認メモ・プレースホルダは、単に空欄を埋めるためではなく、子どもの姿からねらい、環境、援助、振り返りへ考えをつなぐための観点を示す。
- **視認性**: 印刷時・画面閲覧時とも、最低限項目が見つけやすい順序にする。日案では `daily_timeline` を目立つ位置に置く。
- **分担しやすさ**: 複数担任で修正できるよう、1つの巨大 textarea にせず、セクション/セル単位で編集する。
- **導入しやすさ**: ICTに不慣れな職員でも扱えるよう、MVPではドラッグ&ドロップや複雑な行追加UIを避ける。行追加/削除はフェーズ3。
- **保育の質の担保**: 入力省略によって最低限項目が空になる場合は、エラーで止めるのではなく `needs_confirmation` と `editor_note` で確認を促す。

### 12.8 テスト追加

§9 に加えて、以下を追加テスト候補とする。

- 週案・日案の生成結果が、ガイドライン p.61 の最低限項目に対応する section/schedule を必ず持つ。
- 未入力時に、最低限項目のうち中心となる姿・ねらい・活動・援助が `confirmation_items` または `needs_confirmation` に反映される。
- 上位計画を選択した場合、同一本文が複数セクションに丸ごと複製されず、`source_refs` と要約本文で接続される。
- `daily_health_safety` と `schedule.support` の生成本文が同一文にならない。
- 編集画面で `schedule` セルだけを更新しても、叙述セクションと振り返りセクションが壊れない。

### 12.9 フェーズへの反映

- **フェーズ1（MVP）**: 最低限項目を土台に、少ない入力から豊かな週案・日案へ育てられることを優先する。`schedule` は固定ひな型 + 空欄許容 + 最低確認セルで実装する。
- **フェーズ2**: 文例選択では、候補を大量に出しすぎず、最低限項目に対応する候補を優先表示する。園文例も週案・日案専用文例を受け入れるが、重複候補を抑制する。
- **フェーズ3**: 計画・記録・反省の一体化を進め、日案の実践記録、週案への評価集約、タイムスタディやノンコンタクトタイムとの連携可能性を検討する。
