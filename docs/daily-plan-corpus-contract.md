# 日案文例コーパス 受け入れ仕様 v2

- 作成日: 2026-08-09
- 本体リポジトリ: `open-hoikuict`
- 推奨コーパス構築リポジトリ名: `hoiku-plan-corpus`
- 受け入れ形式: SQLite 3（読み取り専用）

## 1. 方針

過去の日案を変換・確認する作業と、日案を作成するアプリ本体を分離する。別リポジトリでは原資料の抽出、表記統一、匿名化、人による確認、SQLite生成までを担い、本体には確認済み成果物だけを取り込む。

文例は日案単位で保持し、その時系列を次の横4列の活動ブロックとして保持する。

1. 時間（活動名を補助表示できる）
2. 子どもの様子
3. 保育士の援助
4. 配慮事項

これにより、一日の流れと項目間の文脈を保ったまま一つの日案例として選択できる。選択後は全活動ブロックを下書きへコピーし、元DBと独立して編集可能とする。

## 2. 責務の境界

### 別リポジトリ `hoiku-plan-corpus`

- DOCX、XLSX、CSV、PDF等の過去資料を抽出する。
- 年齢、月、日案本文、時系列の4列を共通形式へ正規化する。
- 氏名、連絡先、病歴等の個人情報を除去・置換する。
- 原資料との対応を内部参照IDで保持する。
- 人が内容と匿名化を確認し、`approved` にする。
- 本仕様に適合するSQLiteとマニフェストを生成・検証する。

### 本体リポジトリ `open-hoikuict`

- SQLiteを読み取り専用で開く。
- 本番では内容・個人情報レビューがともに `approved` の日案例だけを検索・表示する。
- `development` では、明示設定された `2-anonymized-review` DBに限り、`rejected` でない匿名化候補を開発確認用に表示できる。
- 年齢、月、キーワードで候補を絞り込む。
- 選択した活動ブロック一式を横4列の作成フォームへコピーする。
- 保存時に文例IDと出典参照をリビジョンへ記録する。
- 元DBの内容を本体から更新しない。

## 3. SQLiteスキーマ

`hoiku-plan-corpus/schema/runtime.sql` の主要な必須スキーマを次に示す。

```sql
create table corpus_metadata (
    key text primary key,
    value text not null
);

create table daily_plan_examples (
    id text primary key,
    target_date text not null,
    month integer not null,
    school_year integer not null,
    age_class integer not null,
    class_label text not null,
    title text not null,
    main_activity_raw text not null,
    main_activity_normalized text not null,
    content_text text not null,
    timeline_text text,
    child_state_text text not null,
    support_text text not null,
    considerations_text text not null,
    reflection_text text,
    source_ref text not null,
    content_hash text not null,
    quality_score real not null,
    review_status text not null,
    pii_review_status text not null
);

create table daily_plan_activity_blocks (
    id integer primary key,
    daily_plan_id text not null references daily_plan_examples(id),
    position integer not null,
    time_label text,
    activity_name text,
    activity_text text,
    child_state_text text,
    support_text text,
    considerations_text text
);
```

### 必須メタデータ

| キー | 内容 | 例 |
|---|---|---|
| `schema_version` | 本体との互換性を表す版 | `2-runtime` |
| `corpus_version` | データ成果物の版 | `2026.08.1` |
| `generated_at` | ISO 8601の生成日時 | `2026-08-09T12:00:00+09:00` |
| `record_count` | 全レコード数 | `1240` |

### 列の規則

- `id`: 再生成しても変わらない不透明な識別子。個人情報を含めない。
- `age_class`: 0〜5の整数。本体表示時に `0歳児`〜`5歳児`へ変換する。
- `month`: 1〜12。
- `source_ref`: 原資料を直接公開せず照合できる内部参照ID。
- `review_status`: 内容レビュー状態。本番は `approved` のみ使用する。
- `pii_review_status`: 個人情報レビュー状態。本番は `approved` のみ使用する。
- 活動ブロックは `position` 順に読み、4列の下書きへコピーする。

本体は必須テーブル、必須列、`schema_version` を起動後の初回読取時に検証する。互換性がない場合は候補表示を止め、手入力での日案作成は継続可能にする。

## 4. 成果物

別リポジトリのリリース成果物は次の2ファイルとする。

- `daily_plan_examples.sqlite`
- `manifest.json`

`manifest.json` には少なくとも `schema_version`、`corpus_version`、`record_count`、SQLiteファイルのSHA-256を含める。本体への取り込み時にハッシュと件数を照合する。

本体は次の順にDBを探索する。

1. 環境変数 `HOIKU_DAILY_PLAN_EXAMPLES_DB_PATH`
2. `data/daily_plan_examples.sqlite`
3. `gen_bunnrei/daily_plan_examples.sqlite`

開発・運用環境では環境変数を推奨し、リリース同梱時のみリポジトリ内の既定位置を使う。

## 5. 個人情報と著作権

- 原資料をGitへそのまま登録しない。非公開リポジトリであっても、原資料用ディレクトリは原則 `.gitignore` 対象とする。
- 子ども、保護者、職員の氏名、連絡先、住所、識別可能な健康情報は成果物へ含めない。
- 自動マスキングだけで `approved` にせず、人による匿名化確認を必須とする。
- 外部様式や市販教材を含む場合は、二次利用権を確認し、出典と利用条件を台帳で管理する。
- `source_ref` は内部照合用とし、ローカルファイルパスや個人名を含めない。

## 6. 変換工程

```text
原資料（Git管理外）
  → 文字・表の抽出
  → 日案本文と時系列4列への対応付け
  → 年齢・月・表記の正規化
  → 個人情報の自動検出とマスキング
  → 人による内容・匿名化レビュー
  → SQLite生成
  → スキーマ・件数・重複・禁止語検査
  → 版付き成果物の公開
  → open-hoikuictへ取り込み
```

抽出不能、4列の対応が曖昧、個人情報の判断が難しいレコードは未承認のまま残し、本番成果物へは出さない。

## 7. 受け入れ基準

- 対応する `schema_version` で必須テーブル・列がすべて存在する。
- 本番候補は `review_status=approved` かつ `pii_review_status=approved` である。
- 活動ブロックを `position` 順に横4列へコピーできる。
- 年齢、月、キーワード検索が期待どおり機能する。
- 同じ `id` はコーパス更新後も同一の日案例を表す。
- SQLiteは本体から更新されない。
- 不正な版や壊れたDBがあっても、手入力の日案作成は利用できる。
