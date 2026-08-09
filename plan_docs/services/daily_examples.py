from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATHS = (
    REPO_ROOT / "data" / "daily_plan_examples.sqlite",
    REPO_ROOT / "gen_bunnrei" / "daily_plan_examples.sqlite",
)
SUPPORTED_SCHEMA_VERSIONS = {
    "1",
    "2",
    "2-runtime",
    "2-anonymized-review",
}
REQUIRED_EXAMPLE_COLUMNS = {
    "id",
    "month",
    "age_class",
    "title",
    "main_activity_raw",
    "main_activity_normalized",
    "content_text",
    "child_state_text",
    "support_text",
    "considerations_text",
    "source_ref",
    "quality_score",
    "review_status",
    "pii_review_status",
}
REQUIRED_ACTIVITY_COLUMNS = {
    "daily_plan_id",
    "position",
    "time_label",
    "activity_name",
    "activity_text",
    "child_state_text",
    "support_text",
    "considerations_text",
}


class DailyExampleCorpusError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DailyPlanActivityBlock:
    position: int
    time_label: str
    activity_name: str
    activity_text: str
    child_state: str
    support: str
    considerations: str

    @property
    def time_and_activity(self) -> str:
        return "\n".join(
            value for value in (self.time_label, self.activity_name) if value
        )


@dataclass(frozen=True, slots=True)
class DailyPlanExample:
    id: str
    age_class: str
    month: int
    title: str
    main_activity: str
    aims: tuple[str, ...]
    content: str
    child_state: str
    support: str
    considerations: str
    source_ref: str
    quality_score: float
    review_pending: bool
    activity_blocks: tuple[DailyPlanActivityBlock, ...]


def daily_examples_db_path() -> Path | None:
    configured = (os.getenv("HOIKU_DAILY_PLAN_EXAMPLES_DB_PATH") or "").strip()
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = REPO_ROOT / path
        return path.resolve() if path.exists() else None
    return next((path for path in DEFAULT_DB_PATHS if path.exists()), None)


def corpus_metadata() -> dict[str, str]:
    path = daily_examples_db_path()
    if path is None:
        return {}
    try:
        with closing(_connect_readonly(path)) as connection:
            metadata = _validate_schema(connection)
            if _allows_pending_review(metadata):
                metadata["development_review_data"] = "1"
            return metadata
    except sqlite3.Error as exc:
        raise DailyExampleCorpusError("日案文例DBを読み込めません") from exc


def list_daily_plan_examples(
    *,
    age_class: str | None = None,
    month: int | None = None,
    query: str | None = None,
    limit: int = 30,
) -> list[DailyPlanExample]:
    path = daily_examples_db_path()
    if path is None:
        return []
    try:
        with closing(_connect_readonly(path)) as connection:
            metadata = _validate_schema(connection)
            clauses = [_review_clause(_allows_pending_review(metadata))]
            params: list[object] = []
            normalized_age = _age_number(age_class)
            if normalized_age is not None:
                clauses.append("example.age_class = ?")
                params.append(normalized_age)
            if month is not None:
                clauses.append("example.month = ?")
                params.append(month)
            cleaned_query = (query or "").strip()
            if cleaned_query:
                token = f"%{cleaned_query}%"
                clauses.append(
                    """
                    (
                        example.title like ?
                        or example.main_activity_raw like ?
                        or example.main_activity_normalized like ?
                        or example.content_text like ?
                        or example.child_state_text like ?
                        or example.support_text like ?
                        or example.considerations_text like ?
                        or exists (
                            select 1 from daily_plan_activity_blocks block
                            where block.daily_plan_id = example.id
                              and (
                                block.time_label like ? or block.activity_name like ?
                                or block.activity_text like ? or block.child_state_text like ?
                                or block.support_text like ? or block.considerations_text like ?
                              )
                        )
                    )
                    """
                )
                params.extend([token] * 13)
            params.append(max(1, min(limit, 100)))
            rows = connection.execute(
                f"""
                select example.*
                from daily_plan_examples example
                where {' and '.join(clauses)}
                order by example.quality_score desc, example.month, example.age_class, example.id
                limit ?
                """,
                params,
            ).fetchall()
            return [_example_from_row(connection, row) for row in rows]
    except sqlite3.Error as exc:
        raise DailyExampleCorpusError("日案文例DBを検索できません") from exc


def get_daily_plan_example(example_id: str) -> DailyPlanExample | None:
    path = daily_examples_db_path()
    if path is None:
        return None
    try:
        with closing(_connect_readonly(path)) as connection:
            metadata = _validate_schema(connection)
            row = connection.execute(
                f"""
                select example.*
                from daily_plan_examples example
                where example.id = ? and {_review_clause(_allows_pending_review(metadata))}
                """,
                (example_id,),
            ).fetchone()
            return _example_from_row(connection, row) if row is not None else None
    except sqlite3.Error as exc:
        raise DailyExampleCorpusError("日案文例DBから候補を取得できません") from exc


def _connect_readonly(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(
            f"file:{path.resolve().as_posix()}?mode=ro", uri=True
        )
    except sqlite3.Error as exc:
        raise DailyExampleCorpusError("日案文例DBを読み取り専用で開けません") from exc
    connection.row_factory = sqlite3.Row
    return connection


def _validate_schema(connection: sqlite3.Connection) -> dict[str, str]:
    tables = {
        str(row[0])
        for row in connection.execute(
            "select name from sqlite_master where type = 'table'"
        )
    }
    required_tables = {
        "corpus_metadata",
        "daily_plan_examples",
        "daily_plan_aims",
        "daily_plan_activity_blocks",
    }
    missing_tables = required_tables - tables
    if missing_tables:
        raise DailyExampleCorpusError(
            f"日案文例DBに必要なテーブルがありません: {', '.join(sorted(missing_tables))}"
        )
    example_columns = _table_columns(connection, "daily_plan_examples")
    missing_example_columns = REQUIRED_EXAMPLE_COLUMNS - example_columns
    if missing_example_columns:
        raise DailyExampleCorpusError(
            "日案文例DBに必要な列がありません: "
            + ", ".join(sorted(missing_example_columns))
        )
    activity_columns = _table_columns(connection, "daily_plan_activity_blocks")
    missing_activity_columns = REQUIRED_ACTIVITY_COLUMNS - activity_columns
    if missing_activity_columns:
        raise DailyExampleCorpusError(
            "日案文例DBの活動ブロックに必要な列がありません: "
            + ", ".join(sorted(missing_activity_columns))
        )
    metadata = {
        str(row["key"]): str(row["value"])
        for row in connection.execute("select key, value from corpus_metadata")
    }
    schema_version = metadata.get("schema_version", "")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise DailyExampleCorpusError(
            f"日案文例DBのschema_version {schema_version or '未設定'} は未対応です"
        )
    return metadata


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"pragma table_info({table})")}


def _allows_pending_review(metadata: dict[str, str]) -> bool:
    environment = (os.getenv("HOIKUICT_ENV") or "production").strip().lower()
    return (
        environment == "development"
        and metadata.get("schema_version") == "2-anonymized-review"
    )


def _review_clause(allow_pending: bool) -> str:
    if allow_pending:
        return "example.review_status != 'rejected' and example.pii_review_status != 'rejected'"
    return "example.review_status = 'approved' and example.pii_review_status = 'approved'"


def _age_number(age_class: str | None) -> int | None:
    value = (age_class or "").strip()
    if not value:
        return None
    leading = value.split("歳", 1)[0]
    try:
        age = int(leading)
    except ValueError:
        return None
    return age if 0 <= age <= 5 else None


def _example_from_row(
    connection: sqlite3.Connection, row: sqlite3.Row
) -> DailyPlanExample:
    aims = tuple(
        str(item["aim_text"] or "")
        for item in connection.execute(
            """
            select aim_text
            from daily_plan_aims
            where daily_plan_id = ?
            order by position
            """,
            (row["id"],),
        )
        if item["aim_text"]
    )
    blocks = tuple(
        DailyPlanActivityBlock(
            position=int(block["position"]),
            time_label=str(block["time_label"] or ""),
            activity_name=str(block["activity_name"] or ""),
            activity_text=str(block["activity_text"] or ""),
            child_state=str(block["child_state_text"] or ""),
            support=str(block["support_text"] or ""),
            considerations=str(block["considerations_text"] or ""),
        )
        for block in connection.execute(
            """
            select position, time_label, activity_name, activity_text,
                   child_state_text, support_text, considerations_text
            from daily_plan_activity_blocks
            where daily_plan_id = ?
            order by position
            """,
            (row["id"],),
        )
    )
    if not blocks:
        blocks = (
            DailyPlanActivityBlock(
                position=0,
                time_label=str(row["timeline_text"] or ""),
                activity_name=str(row["main_activity_normalized"] or ""),
                activity_text=str(row["content_text"] or ""),
                child_state=str(row["child_state_text"] or ""),
                support=str(row["support_text"] or ""),
                considerations=str(row["considerations_text"] or ""),
            ),
        )
    return DailyPlanExample(
        id=str(row["id"]),
        age_class=f"{int(row['age_class'])}歳児",
        month=int(row["month"]),
        title=str(row["title"] or "日案例"),
        main_activity=str(
            row["main_activity_normalized"] or row["main_activity_raw"] or ""
        ),
        aims=aims,
        content=str(row["content_text"] or ""),
        child_state=str(row["child_state_text"] or ""),
        support=str(row["support_text"] or ""),
        considerations=str(row["considerations_text"] or ""),
        source_ref=str(row["source_ref"]),
        quality_score=float(row["quality_score"] or 0),
        review_pending=(
            row["review_status"] != "approved"
            or row["pii_review_status"] != "approved"
        ),
        activity_blocks=blocks,
    )
