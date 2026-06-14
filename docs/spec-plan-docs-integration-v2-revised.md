# open-hoikuict への hoiku-plan-docs 統合仕様 v2.1

対象リポジトリ: `hoikuict/open-hoikuict`（統合先）、`hoikuict/hoiku-plan-docs`（統合元）
前提段階: アルファ。本物の認証（パスワード、外部 IdP 等）は実装しない。

本書は `spec-plan-docs-integration-v2.md` の修正版である。主な修正点は次のとおり。

- コンテナ healthcheck 用エンドポイントを `/health` ではなく `/healthz` に変更する。`/health` は open-hoikuict 既存の健康管理画面で使われているため。
- 本体モック認証の実際の cookie 名（`mock_role` / `mock_staff_name` / `mock_calendar_user_id`）に合わせて、職員選択と actor_ref 解決を明確化する。
- HTMX POST 時の職員未選択リダイレクトは `HX-Redirect` を返す仕様にする。
- `SQLModel.metadata.create_all()` 前に `plan_docs.db_models` が import されることを明記する。
- 個別指導計画の記録参照期間を「対象月の前月」に統一する。
- 出欠集計の定義、一括下書き作成の重複防止、DB unique 制約を追加する。
- `facility.sqlite` seed の配置と runtime file 初期化責務を明確化する。
- `routers/database.py` の旧 DB モジュールを削除対象として明記する。

## 目的

1. hoiku-plan-docs（年案・月案・週案・日案の文書作成機能）を open-hoikuict 本体に取り込み、単一アプリ・単一セッションとして動かす。
2. 0・1・2歳児向けの個別指導計画（`individual_plan`）を新しい文書種別として追加し、本体に蓄積される記録と将来連動できる形にする。
3. `docs/integration-contract.md` の契約を破壊しない。追加のみ行う。
4. コンテナ再作成時にも本体 DB と園文例 DB が失われない配置にする。

## 対象外

- 本物の認証・認可の実装。モックの統合までを行い、将来の差し替えポイントは維持する。
- JSON 書き込み API（`POST /api/annual-plans` 等）。参照 API のみ移設する。
- hoiku-plan-writer 実用版への生成サービス差し替え。
- 多園（マルチテナント）対応。
- 記録からの本文自動生成・自動要約。Phase 3 では記録の参照と根拠引用までとし、生成は後続とする。
- アプリ内バックアップ機能。volume 化はバックアップではなく、コンテナ再作成への耐性である。

## 統合方式

コードマージとする。reverse proxy / 別プロセス方式は採らない。

個別指導計画は園児マスタ・日次連絡・出欠・健康記録との連携が本質であり、同一プロセス・同一 DB で読めることが利点になるため。hoiku-plan-docs リポジトリは履歴が浅いため単純コピーで取り込み、完了後に移転先を README に明記して archive する。

## Phase 1: コード移設・マウント・モック認証統合

### ディレクトリ配置

```
open-hoikuict/
  plan_docs/
    __init__.py
    contracts.py
    models.py
    store.py              # DocumentStore（in-memory）。Phase 2 で実装差し替え
    auth_adapter.py       # 本体モックセッションから plan_docs StaffUser を組み立てる
    serializers.py
    runtime.py            # facility.sqlite seed-copy 等の起動時初期化
    services/
      __init__.py / bunrei.py / generators.py / text.py
    routers/
      __init__.py / home.py / plans.py / documents.py / bunrei.py
  templates/
    plan_docs/
  gen_bunnrei/
    bunrei.sqlite         # 共通文例。読み取り専用シード
    facility.sqlite       # 園文例の初期 seed
  data/                   # 実行時の書き込みファイル置き場（.gitignore 対象）
  docs/
    integration-contract.md
    spec-weekly-daily-plans.md
  Dockerfile
  deploy/
    dockge/compose.yaml
```

移設しないもの:

- plan-docs の `main.py`（create_app）
- `web/templating.py`
- `static/styles.css`
- 独自 `base.html`
- `auth.py`（CookieStaffAuthBackend）
- `web/routers/staff_auth.py`

アプリ生成・テンプレート基盤・セッションは open-hoikuict 側に一本化する。

### ルーティング

plan_docs の全ルーターを `/plans` プレフィックスで本体 `main.py` に登録する。

| 旧 | 新 |
| --- | --- |
| `/` | `/plans/` |
| `/annual-plans/new` ほか各計画 | `/plans/annual-plans/new` ほか |
| `/bunrei/*` | `/plans/bunrei/*` |
| `/documents/*` | `/plans/documents/*` |
| `/api/documents/{id}` | `/plans/api/documents/{id}` |
| `/staff/login` `/staff/session` `/staff/logout` | 廃止。本体の `/staff/login` を使う |
| `/health` | 移設しない。既存の健康管理画面として維持する |
| コンテナ healthcheck | 新規 `/healthz` を使う |

`/healthz` は HTML テンプレートを使わず、DB 接続を必須としない軽量 JSON を返す。

```json
{"status": "ok"}
```

テンプレート内の `href` / `action` / `hx-*` パスは `/plans` 前提に全置換する。置換漏れは次の検索で機械的に潰す。

```powershell
rg -n 'href="/|action="/|hx-get="/|hx-post="/|hx-put="/|hx-delete="/' templates/plan_docs plan_docs
```

### モック認証の統合

方針: 職員の選択・ロール切り替えは本体の `/staff/login` だけで行う。plan-docs 独自 cookie（`staff_role`, `staff_actor_id`, `staff_nursery_id`, `staff_classrooms`, `staff_name`）は全廃する。

open-hoikuict 側のモック認証 cookie は次を正とする。

| cookie | 用途 |
| --- | --- |
| `mock_role` | `view_only` / `can_edit` / `admin` |
| `mock_staff_name` | 職員表示名 |
| `mock_calendar_user_id` | `users.id` の UUID。職員選択済み判定にも使う |

`plan_docs/auth_adapter.py` に `resolve_plan_docs_staff_user` を置く。plan_docs ルーターはこの依存関数から plan_docs 用 StaffUser を受け取る。

```python
def resolve_plan_docs_staff_user(
    request: Request,
    session: Session = Depends(get_session),
) -> StaffUser:
    ...
```

plan-docs 由来の `StaffAuthBackend` Protocol を残す場合でも、DB を読む処理は FastAPI dependency 経由に寄せる。`request` だけで `classrooms` を読む設計にはしない。テストでは `resolve_plan_docs_staff_user` と `get_session` を dependency override できることを完了条件に含める。

| plan_docs フィールド | 解決方法 |
| --- | --- |
| `role` | 本体モックセッションの role |
| `name` | 本体セッションの職員表示名 |
| `actor_ref` | 職員選択済みなら `staff:{users.id}`。未選択時は `None` |
| `nursery_ref` | 環境変数 `HOIKU_NURSERY_REF`。既定値 `ひかり保育園` |
| `classroom_refs` | `classrooms` テーブルの全クラス名 |

決定事項と帰結:

- 職員未選択時の扱い: 閲覧は未選択でも許す。文書の作成・編集・ステータス操作・園文例取り込みなどの POST 系操作は actor_ref を必須とする。
- 通常リクエストで actor_ref が必要なのに未選択の場合、`/staff/login?redirect=元URL` へ 303 リダイレクトする。
- HTMX リクエストで actor_ref が必要なのに未選択の場合、レスポンスヘッダー `HX-Redirect: /staff/login?redirect=元URL` を返す。部分 HTML としてログイン画面を差し込まない。
- クラススコープはアルファでは全権付与とする。本体に職員とクラスの割り当てモデルが存在しないため。`can_access_classroom` と文書側の `classroom_ref` 保存は維持する。
- `classroom_ref` は自由入力をやめる。作成フォームのクラス欄は `classrooms` テーブルからの select にする。
- 旧形式 `職員:担任` 等の actor_ref 互換変換は不要。Phase 2 永続化より前に統合を終え、DB には `staff:{uuid}` 形式のみを入れる。

`contracts.py` の `Role` / `ROLE_LABELS` は plan_docs 側に残してよい。ただし値の正は本体 `auth.py` とし、import 時 assert で不一致を検出する。

### テンプレートの再親付け

- plan-docs の `base.html` / `styles.css` を破棄し、全テンプレートを本体 `templates/base.html` の extends に書き換える。
- テンプレート名は `plan_docs/...` 形式へ全修正する。
- plan_docs 画面のヘッダ職員名・ロール表示は本体セッション由来の一つだけにする。
- 帳票印刷 CSS は documents/detail.html の `{% block head %}` に閉じて持たせる。
- 本体サイドバーに `指導計画`（`/plans/`）リンクを 1 つ追加する。

### bunrei DB と runtime file 初期化

- 読み取り専用シード `bunrei.sqlite` は `gen_bunnrei/bunrei.sqlite` に置き、`HOIKU_BUNREI_DB_PATH` で上書き可。
- 園文例の初期 seed は `gen_bunnrei/facility.sqlite` に置く。
- 書き込みが発生する園文例 DB の既定パスは `./data/facility.sqlite` とし、`HOIKU_FACILITY_BUNREI_DB_PATH` で上書き可。
- アプリ起動時に `plan_docs.runtime.ensure_runtime_files()` を呼び、`HOIKU_FACILITY_BUNREI_DB_PATH` のファイルが存在しなければ `gen_bunnrei/facility.sqlite` からコピーする。
- seed-copy の責務はアプリ起動時に一本化する。Docker entrypoint には同じ処理を重複実装しない。
- `bunrei.py` の `REPO_ROOT = parents[3]` は移設で階層が変わるため修正し、パス解決のテストを追加する。

### テスト

- `tests/test_plan_docs.py` を追加する。
- 対象は本体 `main.app` または plan_docs ルーターを含むテスト用 FastAPI app とする。
- 全パスに `/plans` を付与する。
- 認証は本体モック cookie（`mock_role`, `mock_staff_name`, `mock_calendar_user_id`）でセットアップする。
- HTMX POST の未ログイン時に `HX-Redirect` が返ることをテストする。
- `/healthz` が 200 を返し、既存 `/health` 健康管理画面を壊していないことを確認する。

### Phase 1 完了条件

- `uvicorn main:app` 一本で本体機能と `/plans/` 配下が動く。
- `/health` は既存の健康管理画面として維持され、コンテナ healthcheck は `/healthz` を参照する。
- 職員の選択・ロール切り替えが本体 `/staff/login` の一箇所で済み、plan_docs 側の権限に反映される。
- 年案〜日案の作成・一覧・詳細・印刷・ステータス操作、文例選択 UI、園文例取り込みが移設前と同等に動く。
- HTMX 操作で職員未選択時にログイン画面が部分差し替えされない。
- 全テスト pass。

## Phase 2: SQLite 永続化

in-memory の `DocumentStore` を本体 `hoikuict.db` への保存に差し替える。契約 JSON（serializers.py の出力形）を JSON カラムにそのまま格納し、sections / schedule は正規化しない。検索要件はスカラー列で足りるため。

### テーブル（SQLModel、plan_docs/db_models.py）

```
plan_documents
  id int PK
  document_type str (index)
  status str (index)
  title str
  nursery_ref str
  classroom_ref str (index)
  actor_ref str
  owner_name str
  school_year int? (index)
  target_month str?
  target_week str?
  week_start_date str?
  target_date str?
  age_class str?
  child_id int? (FK children.id, index)
  child_ref str?
  child_name str?
  parent_document_id int?
  related_document_ids JSON
  sections JSON
  schedule JSON?
  confirmation_items JSON
  created_at datetime
  updated_at datetime

plan_document_actions
  id int PK
  document_id int (FK plan_documents.id, index)
  document_type str
  action str
  comment str?
  actor_ref str
  created_at datetime
```

`plan_document_actions.action` は `submit` / `approve` / `reject` / `archive` のみとする。

Phase 3 用に、次の unique 制約を最初から入れる。

```
UniqueConstraint("document_type", "child_id", "target_month", name="uq_plan_document_child_month")
```

この制約は `individual_plan` で `child_id` と `target_month` が必須になるため、一括下書きの重複防止に効く。SQLite では NULL を含む unique が重複扱いにならないため、既存の年案・月案・週案・日案で `child_id` が NULL の文書には影響しない。

child_id（内部 FK）と child_ref（契約文字列）を両方持つ。外部契約 JSON に出すのは child_ref のみ。内部 FK は記録との JOIN 用で、契約には含めない。

### 実装方針

- `DocumentStore` のメソッド群を Protocol として固定し、`SqlDocumentStore` を実装する。
- ルーターはモジュールグローバル参照をやめ、`Depends(get_document_store)` に変更する。
- テストは in-memory 実装またはテスト用 SQLite 実装を注入する。
- dataclass と DB 行の変換は serializers.py を双方向に拡張する。
- 契約値の検証は serializers.py または contracts.py の層で行う。
- ステータス変更時に `plan_document_actions` へ 1 行追加し、詳細画面に操作履歴を表示する。
- テーブル作成は本体 `create_db_and_tables()` に乗る。
- `SQLModel.metadata.create_all()` の前に `plan_docs.db_models` が import 済みであることを保証する。

実装例:

```python
def create_db_and_tables() -> None:
    import plan_docs.db_models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    ...
```

または `main.initialize_application()` の最初で import してもよい。ただし、テストで `database.create_db_and_tables()` だけを呼んだ場合にも plan_docs テーブルが作られる方が安全なので、`database.py` 側での import を推奨する。

### DB 設定の環境変数化

`database.py` の `DATABASE_URL` を環境変数化する。

```python
import os

DATABASE_URL = os.getenv("HOIKUICT_DATABASE_URL", "sqlite:///./hoikuict.db")
engine = create_engine(DATABASE_URL, echo=False)
```

`routers/database.py` は旧構成の残骸であり、現行ルーターから参照されていない。Phase 2 で削除する。削除できない事情が見つかった場合は、同じ環境変数化を適用して二重定義の差異をなくす。

### Phase 2 完了条件

- 再起動後も文書が残る。
- 承認ログが残り、詳細画面で参照できる。
- `plan_docs.db_models` の import 漏れでテーブルが作られない問題が起きない。
- contract JSON の round-trip テスト（無劣化で往復）を追加し pass。
- `HOIKUICT_DATABASE_URL` で DB パスを変更できる。
- 未使用の `routers/database.py` が削除されている、または環境変数化済みである。

## Phase 3: 個別指導計画（0・1・2歳児）と記録連動の拡張点

保育所保育指針が 3歳未満児に求める個別的な計画を、月単位・園児単位の文書として追加する。本体 DB（children / classrooms、および記録テーブル）への読み取り依存がここで初めて発生する。

### 契約追加（integration-contract.md に追記）

document_type:

| document_type | label | 互換 alias |
| --- | --- | --- |
| `individual_plan` | 個別指導計画 | `individual` |

追加フィールド:

| field | type | required | note |
| --- | --- | --- | --- |
| `child_ref` | string | individual_plan で必須 | `child:{children.id}` 形式 |
| `child_name` | string | 任意 | 作成時点スナップショット。表示専用 |

child_ref に内部 PK を埋め込むのは「安定した外部識別情報」原則からの逸脱である。ただし、アルファ段階の単一園・単一 SQLite では children.id は事実上安定なので許容する。園児マスタへ外部 ID を導入する時点で `child_ref` の再設計または互換 alias を追加する。

section_key（個別指導計画）:

| section_key | title |
| --- | --- |
| `individual_children_snapshot` | 前月までの子どもの姿 |
| `individual_goal_care` | 養護のねらい |
| `individual_goal_education` | 教育のねらい |
| `individual_life_rhythm` | 生活リズム（食事・睡眠・排泄・遊び） |
| `individual_environment_support` | 環境構成・援助 |
| `individual_family_collaboration` | 家庭との連携 |
| `individual_reflection_viewpoint` | 評価・反省 |

0歳児（3つの視点）と 1・2歳児（5領域）の違いは section_key を分けず、フォームの placeholder と文例候補の年齢絞り込みで吸収する。キーを分けると横断集計が壊れるため。

### 記録連動の契約（拡張点の定義）

連動の仕組みは source_refs の prefix 拡張として定義する。文書のどの記述が本体のどの記録を根拠にしているかを、レコード単位で指せるようにする。

| prefix | evidence tag | 形式 | 参照先 |
| --- | --- | --- | --- |
| `individual.*` | `入力` | `individual.{form_field}` | フォーム入力 |
| `record.daily_contact` | `記録` | `record.daily_contact:{id}` | daily_contact_entries |
| `record.attendance` | `記録` | `record.attendance:{child_id}:{YYYY-MM}` | 月次出欠集計 |
| `record.health_check` | `記録` | `record.health_check:{id}` | health_check_records |

`record.{type}:{key}` は拡張可能な形式とし、type の追加（例: 将来の発達記録、ヒヤリハット）は非破壊的変更として contract 文書の表に行を足すだけで済む。

source_refs は表示タグと根拠ポインタであり、記録本文を文書へ自動転記しない。記述は職員が書き、引用はポインタとして残す。引用された記録の存在チェックは表示時に行い、削除済みなら「参照先なし」と表示する。文書側は壊さない。

参照の逆引き（「この記録を根拠にした計画の一覧」）が必要になった時点で `plan_document_references(document_id, record_type, record_key)` テーブルを追加する。Phase 3 では sections JSON 内の source_refs のみとし、テーブルは作らない。

### 対象月と参照月

個別指導計画は `target_month` の計画である。

記録参照パネルは `target_month` の前月を参照する。例: `target_month = 2026-06` の場合、記録参照パネルは `2026-05-01` から `2026-05-31` を表示する。

理由:

- `individual_children_snapshot` が「前月までの子どもの姿」であるため。
- 計画作成時点で対象月の記録はまだ揃っていないことが多いため。

健康記録は参照月末日以前の直近レコードを表示する。

### 出欠集計の定義

現行の `attendance_records` は登降園打刻レコードであり、欠席種別を直接持たない。そのため Phase 3 の月次出欠集計は次の定義で行う。

- 出席日数: 参照月内に `attendance_records` が存在し、`check_in_at` または `check_out_at` がある日数。
- 欠席日数: 参照月内に `daily_contact_entries.contact_type` が欠席系の値で登録された日数。
- 未記録日数: 園の開所日カレンダーが未整備のため Phase 3 では算出しない。

欠席系 contact_type の具体値は既存 enum に合わせる。enum に欠席を表す値がない場合は、Phase 3 の前提タスクとして日次連絡側に欠席値を追加するか、出欠集計から欠席日数を外して「出席記録日数」のみ表示する。

`record.attendance:{child_id}:{YYYY-MM}` は上記集計結果への参照を表す。個別の attendance_records ID 群は source_refs には展開しない。

### 画面と動線

| path | 内容 |
| --- | --- |
| `/plans/individual-plans/new` | 単票作成。クラス select → 在籍 0〜2歳児 select → 対象月・各セクション入力 |
| `/plans/individual-plans/bulk` | クラス一括下書き作成。クラス×対象月で在籍児全員分の draft を冪等生成 |
| `/plans/bunrei/individual` | 文例を選んで個別指導計画を作成 |
| `/plans/documents/` | 一覧に種別フィルタ individual_plan と園児フィルタを追加 |

学年齢判定:

- school_year の 4月1日時点の満年齢で判定する。
- `birth_date` から算出するユーティリティを services に置く。
- 0・1・2歳児のみ候補に出す。
- `withdrawal_date` が対象月開始日より前の園児は除外する。
- `enrollment_date` が対象月末日より後の園児は除外する。

テスト seed は実行日依存で 0〜2歳児候補が消えないよう、固定 birth_date だけに頼らず、対象 school_year に対して動的に 0〜2歳児を作る。

### 記録参照パネル

単票作成・編集画面の脇に、選択中の園児×参照月（対象月の前月）の記録を読み取り専用で表示する。

- 日次連絡: 参照月内の sleep_notes / breakfast_status / mood / condition_note / contact_type の一覧
- 出欠: 参照月の出席日数と欠席日数の集計
- 健康記録: 参照月末日以前の直近の身長・体重等

各記録行に「根拠に追加」操作を置き、編集中セクションの source_refs へ `record.*` を挿入する。Phase 3 の実装対象は日次連絡と出欠の 2 種とする。健康記録パネルは読み取りクエリまで用意し、根拠追加 UI は後続でもよい。

### 一括作成の仕様

対象クラス×対象月で、未作成の園児分のみ draft を生成する。

既存判定:

- `document_type = individual_plan`
- `child_id = 対象園児 ID`
- `target_month = 対象月`

上記に一致する文書があれば、status に関係なく既存としてスキップする。承認済み文書やアーカイブ済み文書がある場合も自動再作成しない。再作成・複製は別機能の対象とする。

生成結果には、生成 n 件 / スキップ m 件を表示する。各セクションは空本文 + `needs_confirmation: true`、source_refs に `individual.bulk_seed` を入れる。

DB 側でも `UniqueConstraint("document_type", "child_id", "target_month")` により同時実行時の重複を防ぐ。unique violation が発生した場合は再検索してスキップ扱いにする。

### 文例連携

新カテゴリは作らず、既存の月案文例を年齢で絞って候補に出す。

item → section の対応:

| 月案 item | individual section_key |
| --- | --- |
| 前月末の子どもの姿 | individual_children_snapshot |
| 養護のねらい | individual_goal_care |
| 教育のねらい | individual_goal_education |
| 健康・安全への配慮 / 食育 | individual_life_rhythm |
| 環境構成・保育者の援助 | individual_environment_support |
| 家庭との連携 | individual_family_collaboration |
| 評価・反省 | individual_reflection_viewpoint |

候補は選択 age_class（0歳児 / 1歳児 / 2歳児）で必ず絞る。園文例取り込みの `計画種別` 列に `個別指導計画`（英語値 `individual_plan`）を追加受理する。

### Phase 3 完了条件

- 0〜2歳児を選んで個別指導計画を作成・編集・承認フローに乗せられる。
- 記録参照パネル（日次連絡・出欠）が対象月の前月分を表示する。
- `record.*` の根拠引用が source_refs / evidence_tags に反映される。
- 一括下書き作成がアプリロジックと DB 制約の両方で冪等。
- 文例候補の年齢絞り込みをテストで担保する。
- integration-contract.md への追記が反映され、既存キー・値の削除/意味変更がない。

## データ永続化とコンテナ運用（Dockge）

### 背景

コンテナのファイルシステムは使い捨てであり、イメージ更新や compose 変更でコンテナを作り直すと内部に書いたファイルは消える。消えては困るファイルは volume（ホスト側に実体を持つ領域）に置き、コンテナ内のパスへマウントする必要がある。

統合後に消えては困る書き込みファイルは次の 2 つである。

| ファイル | 内容 | 対応 |
| --- | --- | --- |
| hoikuict.db | 本体の全データ + Phase 2 以降の指導計画 | `HOIKUICT_DATABASE_URL` で `/data` 配下に向ける |
| facility.sqlite | 園文例（職員が画面・CSV から追加） | `HOIKU_FACILITY_BUNREI_DB_PATH` で `/data` 配下に向ける |

`bunrei.sqlite` は共通文例シードで読み取り専用のため、イメージ同梱でよい。volume は不要。

### 仕様

原則: 書き込みが発生するファイルは全て一つのディレクトリに集め、そのディレクトリだけを volume にする。

環境変数の一覧:

| 変数 | ベアメタル既定 | コンテナ設定値 |
| --- | --- | --- |
| `HOIKUICT_DATABASE_URL` | `sqlite:///./hoikuict.db` | `sqlite:////data/hoikuict.db` |
| `HOIKU_FACILITY_BUNREI_DB_PATH` | `./data/facility.sqlite` | `/data/facility.sqlite` |
| `HOIKU_BUNREI_DB_PATH` | `./gen_bunnrei/bunrei.sqlite` | 未設定（イメージ同梱を使用） |
| `HOIKU_NURSERY_REF` | `ひかり保育園` | 園名 |

`plan_docs.runtime.ensure_runtime_files()` は次を行う。

1. `HOIKU_FACILITY_BUNREI_DB_PATH` の親ディレクトリを作成する。
2. `facility.sqlite` が存在しなければ `gen_bunnrei/facility.sqlite` からコピーする。
3. seed が存在しない場合は文例書き込み機能だけを無効化し、アプリ起動は継続する。

### Dockerfile

plan-docs の Dockerfile を本体用に書き換えて移設する。CMD は次とする。

```dockerfile
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

entrypoint で runtime file 初期化を重複実装しない。アプリ lifespan の `initialize_application()` で `ensure_runtime_files()` を呼ぶ。

### Dockge 用 compose

`deploy/dockge/compose.yaml`:

```yaml
services:
  app:
    build:
      context: ../..
      dockerfile: Dockerfile
    image: open-hoikuict:local
    pull_policy: build
    restart: unless-stopped
    environment:
      HOIKUICT_DATABASE_URL: sqlite:////data/hoikuict.db
      HOIKU_FACILITY_BUNREI_DB_PATH: /data/facility.sqlite
      HOIKU_NURSERY_REF: ${NURSERY_REF:-ひかり保育園}
    volumes:
      - hoikuict_data:/data
    ports:
      - "${APP_PORT:-8000}:8000"
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).read()"
      interval: 30s
      timeout: 5s
      retries: 3

volumes:
  hoikuict_data:
```

cloudflared を併用する場合は既存 plan-docs compose の cloudflared サービス定義をそのまま足す。

### .gitignore

`.gitignore` に次を追加する。

```
data/
hoikuict.db
```

`gen_bunnrei/bunrei.sqlite` と `gen_bunnrei/facility.sqlite` は seed としてリポジトリ管理対象にする。

### バックアップに関する注記

volume 化はコンテナ再作成への耐性であり、バックアップではない。`hoikuict.db` は園の実データになるため、TrueNAS 側で当該 dataset の snapshot 対象に volume の実体パスを含めることを運用前提とする。アプリ側のバックアップ機能は本仕様の対象外。

## 実施順序

1. Phase 1: コード移設、ルーティング、テンプレート再親付け、モック認証統合、`/healthz` 追加。
2. Phase 2: SQLite 永続化、DB パス環境変数化、runtime file 初期化、Dockerfile / compose 移設。
3. Phase 3: 個別指導計画、記録参照パネル、source_refs 拡張、一括下書き作成。

認証統合を Phase 1 に含めることで、Phase 2 の永続化時点から actor_ref が `staff:{uuid}` 形式で統一され、旧形式の互換変換が不要になる。Phase 3 は永続化に依存する。

## 主なリスクと対策

| リスク | 対策 |
| --- | --- |
| `/health` ルート衝突 | healthcheck は `/healthz` に固定する |
| テンプレートのリンク全置換漏れ | `rg` で絶対パス・HTMX 属性を検出する |
| HTMX POST 時にログイン画面が部分差し替えされる | `HX-Redirect` を使う |
| plan_docs DB モデルが import されずテーブル未作成 | `database.create_db_and_tables()` 内で import 保証する |
| 出欠の欠席日数定義が既存 DB と合わない | Phase 3 の前提として contact_type の欠席値を確認し、なければ表示を「出席記録日数」に縮退する |
| 一括作成の同時実行で重複する | アプリ側チェックと DB unique 制約を併用する |
| 固定 seed の園児が時間経過で 0〜2歳児でなくなる | Phase 3 テストでは school_year に対して動的な birth_date を作る |
| facility.sqlite seed がない環境で起動失敗する | 文例書き込みのみ無効化し、アプリ起動は継続する |

