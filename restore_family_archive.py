"""Recognize only the additive family archive schema when restoring old backups."""

from contextlib import closing
import re
import sqlite3

from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

from models import FamilyArchiveLog


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


def _project(rows):
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


def compatible(source_rows, current_rows):
    source, current = _project(source_rows), _project(current_rows)
    return bool(
        source and current and source[0] == current[0] and (current[1] or not source[1])
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
        if _project(rows)[1] or not _project(current_rows)[1]:
            return
        expected = _archive_schema()
        with connection:
            connection.execute("ALTER TABLE families ADD COLUMN archived_at DATETIME")
            for row in sorted(current_rows, key=lambda row: row[0] != "table"):
                if row[:3] in expected:
                    connection.execute(row[3])
