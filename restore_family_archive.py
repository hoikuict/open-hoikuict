"""Recognize the approved additive archive and September 24/25 migrations."""

from contextlib import closing
import re
import sqlite3

from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from models import FamilyArchiveLog, GuardianHoursAudit, GuardianHoursSetting

SPEC_COLUMNS = {
    "daily_contact_replies": {"pending_draft": "JSON"},
    "attendance_verification_histories": {
        "reason": "VARCHAR", "previous_status": "VARCHAR", "actor_user_id": "CHAR(32)",
    },
}
SHARING_COLUMNS = {"child_observation_logs": {"visibility": "VARCHAR", "shared_staff_ids": "JSON"}}
MONTHLY_COLUMNS = {"monthly_sheet": "JSON", "monthly_sheet_key": "VARCHAR"}
MONTHLY_INDEXES = {
    "uq_monthly_sheet_key": "CREATE UNIQUE INDEX uq_monthly_sheet_key ON plan_documents(monthly_sheet_key) WHERE monthly_sheet_key IS NOT NULL",
    "ix_plan_documents_monthly_sheet_key": "CREATE UNIQUE INDEX ix_plan_documents_monthly_sheet_key ON plan_documents (monthly_sheet_key)",
}


def _tokens(sql):
    # Whitespace outside literals is immaterial. Preserve literal contents and constraints.
    return re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|\w+|[^\s]", sql or "")


def _archive_schema():
    table = FamilyArchiveLog.__table__
    statements = [str(CreateTable(table).compile(dialect=dialect()))]
    statements.extend(
        str(CreateIndex(index).compile(dialect=dialect())) for index in table.indexes
    )
    with closing(sqlite3.connect(":memory:")) as connection:
        for statement in statements:
            connection.execute(statement)
        rows = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
    rows.append(
        (
            "index",
            "ix_families_archived_at",
            "families",
            "CREATE INDEX ix_families_archived_at ON families (archived_at)",
        )
    )
    return {row[:3]: _tokens(row[3]) for row in rows}


def _archive_project(rows):
    expected = _archive_schema()
    additions = {row[:3]: _tokens(row[3]) for row in rows if row[:3] in expected}
    family = next(
        (row for row in rows if row[:3] == ("table", "families", "families")), None
    )
    if family is None:
        return None
    tokens = _tokens(family[3])
    archived = "archived_at" in tokens
    if archived:
        if additions != expected:
            return None
        index = tokens.index("archived_at")
        # Only this nullable column without defaults or constraints is supported.
        if tokens[index : index + 2] != ["archived_at", "DATETIME"]:
            return None
        if tokens[index + 2] == ",":
            del tokens[index : index + 3]
        elif tokens[index + 2] == ")" and tokens[index - 1] == ",":
            del tokens[index - 1 : index + 2]
        else:
            return None
    elif additions:
        return None
    remaining = {
        row[:3]: (tokens if row == family else row[3])
        for row in rows
        if row[:3] not in expected
    }
    return remaining, archived


def _spec_schema():
    with closing(sqlite3.connect(":memory:")) as connection:
        for model in (GuardianHoursSetting, GuardianHoursAudit):
            connection.execute(str(CreateTable(model.__table__).compile(dialect=dialect())))
        return {
            row[:3]: _tokens(row[3]) for row in connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
            )
        }


def _sharing_project(rows):
    normalized, found = [], set()
    for row in rows:
        if row[0] != "table" or row[1] not in SHARING_COLUMNS:
            normalized.append(row)
            continue
        tokens = _tokens(row[3])
        for name, kind in SHARING_COLUMNS[row[1]].items():
            if name not in tokens:
                continue
            index = tokens.index(name)
            end = index + 2
            if tokens.count(name) != 1 or tokens[index:end] != [name, kind] or end >= len(tokens):
                return None
            if tokens[end] == ",":
                del tokens[index:end + 1]
            elif tokens[end] == ")" and tokens[index - 1] == ",":
                del tokens[index - 1:end]
            else:
                return None
            found.add(name)
        normalized.append((*row[:3], " ".join(tokens)))
    if found and found != set(SHARING_COLUMNS["child_observation_logs"]):
        return None
    return normalized, bool(found)


def _monthly_project(rows):
    """Accept exactly the nullable sheet columns and approved uniqueness indexes."""
    normalized, found, indexes = [], set(), set()
    for row in rows:
        if row[0] == "index" and row[1] in MONTHLY_INDEXES:
            if row[2] != "plan_documents" or _tokens(row[3]) != _tokens(MONTHLY_INDEXES[row[1]]):
                return None
            indexes.add(row[1])
            continue
        if row[:3] != ("table", "plan_documents", "plan_documents"):
            normalized.append(row)
            continue
        tokens = _tokens(row[3])
        for name, kind in MONTHLY_COLUMNS.items():
            if name not in tokens:
                continue
            index = tokens.index(name)
            end = index + 2
            if tokens.count(name) != 1 or tokens[index:end] != [name, kind] or end >= len(tokens):
                return None
            if tokens[end] == ",":
                del tokens[index:end + 1]
            elif tokens[end] == ")" and tokens[index - 1] == ",":
                del tokens[index - 1:end]
            else:
                return None
            found.add(name)
        normalized.append((*row[:3], " ".join(tokens)))
    if found or indexes:
        if found != set(MONTHLY_COLUMNS) or not indexes:
            return None
    return normalized, bool(found)


def _project(rows):
    monthly = _monthly_project(rows)
    if monthly is None:
        return None
    rows, has_monthly = monthly
    sharing = _sharing_project(rows)
    if sharing is None:
        return None
    rows, has_sharing = sharing
    expected = _spec_schema()
    additions = {row[:3]: _tokens(row[3]) for row in rows if row[:3] in expected}
    found = set()
    normalized = []
    for row in rows:
        if row[:3] in expected:
            continue
        if row[0] != "table" or row[1] not in SPEC_COLUMNS:
            normalized.append(row)
            continue
        tokens = _tokens(row[3])
        for name, kind in SPEC_COLUMNS[row[1]].items():
            if name not in tokens:
                continue
            declaration = [name, *_tokens(kind)]
            index = tokens.index(name)
            end = index + len(declaration)
            if tokens.count(name) != 1 or tokens[index:end] != declaration or end >= len(tokens):
                return None
            if tokens[end] == ",":
                del tokens[index:end + 1]
            elif tokens[end] == ")" and tokens[index - 1] == ",":
                del tokens[index - 1:end]
            else:
                return None
            found.add((row[1], name))
        normalized.append((*row[:3], " ".join(tokens)))
    has_spec = bool(additions or found)
    if has_spec and (additions != expected or found != {
        (table, name) for table, fields in SPEC_COLUMNS.items() for name in fields
    }):
        return None
    archive = _archive_project(normalized)
    if archive is None:
        return None
    return archive[0], ({"archive"} if archive[1] else set()) | ({"spec24"} if has_spec else set()) | ({"spec25"} if has_sharing else set()) | ({"monthly27"} if has_monthly else set())


def compatible(source_rows, current_rows):
    source, current = _project(source_rows), _project(current_rows)
    return bool(
        source and current and source[0] == current[0] and source[1] <= current[1]
    )


def upgrade_copy(database, current_rows):
    """Only call on the isolated restore copy; never rewrite the original backup."""
    with closing(sqlite3.connect(database)) as connection:
        rows = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        if rows == current_rows:
            return
        if not compatible(rows, current_rows):
            raise ValueError("Unsupported restore schema")
        missing = _project(current_rows)[1] - _project(rows)[1]
        with connection:
            connection.execute("BEGIN")
            expected = {}
            if "archive" in missing:
                connection.execute("ALTER TABLE families ADD COLUMN archived_at DATETIME")
                expected.update(_archive_schema())
            if "spec24" in missing:
                for table, fields in SPEC_COLUMNS.items():
                    for name, kind in fields.items():
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
                expected.update(_spec_schema())
            if "spec25" in missing:
                for table, fields in SHARING_COLUMNS.items():
                    for name, kind in fields.items():
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
            if "monthly27" in missing:
                for name, kind in MONTHLY_COLUMNS.items():
                    connection.execute(f"ALTER TABLE plan_documents ADD COLUMN {name} {kind}")
                for row in current_rows:
                    if row[0] == "index" and row[1] in MONTHLY_INDEXES:
                        connection.execute(row[3])
            for row in sorted(current_rows, key=lambda row: row[0] != "table"):
                if row[:3] in expected:
                    connection.execute(row[3])
            upgraded = connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            ).fetchall()
            if _project(upgraded) != _project(current_rows):
                raise ValueError("Restore migration did not reach the approved schema")
