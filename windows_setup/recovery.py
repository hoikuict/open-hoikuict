"""Use the application's backup format for an isolated, non-destructive drill."""
from __future__ import annotations
from contextlib import closing

import os
from pathlib import Path
import shutil
import sqlite3
import time
from uuid import uuid4

from beta_setup.core import reject_links
from restore_data import verify_payload
from scripts.backup_runtime import (
    BackupConfig, _copy_attachment_tree, _copy_sqlite_database, create_backup,
    verify_backup_set,
)


def recovery_drill(root: Path) -> dict:
    destination = root / "restore-drills" / uuid4().hex
    reject_links(destination)
    configuration = BackupConfig(
        output_root=Path(os.environ["HOIKUICT_BACKUP_OUTPUT_ROOT"]),
        database_url=os.environ["HOIKUICT_DATABASE_URL"],
        facility_db=Path(os.environ["HOIKU_FACILITY_BUNREI_DB_PATH"]),
        storage_root=Path(os.environ["HOIKUICT_STORAGE_ROOT"]),
        git_sha=os.environ["HOIKUICT_BACKUP_GIT_SHA"],
        app_image=os.environ["HOIKUICT_BACKUP_APP_IMAGE"],
        compose_sha256=os.environ["HOIKUICT_BACKUP_COMPOSE_SHA256"],
        environment="production", facility_ref=os.environ["HOIKU_NURSERY_REF"],
        lock_source_writes=True,
    )
    backup = create_backup(configuration)
    verify_backup_set(backup)
    destination.mkdir(parents=True)
    try:
        _copy_sqlite_database(backup / "db/hoikuict.db", destination / "hoikuict.db")
        _copy_sqlite_database(backup / "db/facility.sqlite", destination / "facility.sqlite")
        _copy_attachment_tree(backup / "storage", destination / "storage")
        verify_payload(destination / "hoikuict.db", destination / "facility.sqlite", destination / "storage")
        with closing(sqlite3.connect(destination / "hoikuict.db")) as connection:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("database_integrity")
            tables = connection.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        return {"backup": backup.name, "tables_checked": tables,
                "completed_at": time.time(), "message": "別の場所への復元・DB・添付の整合性を確認しました。"}
    finally:
        reject_links(destination)
        if destination.parent == root / "restore-drills" and len(destination.name) == 32:
            shutil.rmtree(destination)
