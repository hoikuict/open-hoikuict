"""Copy only data from an existing trial; never execute its source as administrator."""
from __future__ import annotations
from contextlib import closing

import os
from pathlib import Path
import shutil
import sqlite3

from beta_setup.core import SetupError, reject_links


def copy_database(source: Path, destination: Path) -> None:
    reject_links(source)
    reject_links(destination)
    if not source.is_file() or destination.exists():
        raise SetupError("引継ぎ元または引継ぎ先のDBを確認してください。", "migration_invalid")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as incoming:
        if incoming.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise SetupError("引継ぎ元DBの整合性を確認できませんでした。", "database_invalid")
        with closing(sqlite3.connect(destination)) as outgoing:
            incoming.backup(outgoing)
            if outgoing.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise SetupError("引継ぎ先DBの整合性を確認できませんでした。", "database_invalid")


def copy_tree(source: Path, destination: Path) -> None:
    reject_links(source)
    reject_links(destination)
    destination.mkdir(parents=True, exist_ok=False)
    if not source.exists():
        return
    if not source.is_dir():
        raise SetupError("添付の保存場所を確認してください。", "migration_invalid")
    for item in source.iterdir():
        reject_links(item)
        target = destination / item.name
        if item.is_dir():
            copy_tree(item, target)
        elif item.is_file():
            shutil.copyfile(item, target)
        else:
            raise SetupError("通常のファイル以外が含まれています。", "migration_invalid")


def legacy_keys(source: Path) -> dict:
    path = source / "app/.env.beta.local"
    reject_links(path)
    if not path.is_file() or path.stat().st_size > 65536:
        raise SetupError("試用環境の設定を確認できません。", "migration_invalid")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in values:
            raise SetupError("試用環境の設定形式が異なります。", "migration_invalid")
        values[key] = value
    if values.get("HOIKUICT_DATABASE_URL") != "sqlite:///./hoikuict-beta-auth.db":
        raise SetupError("この試用環境のデータ配置は未対応です。", "migration_invalid")
    keys = {key: values.get(key, "") for key in ("HOIKUICT_SECRET_KEY", "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY")}
    if any(len(value) < 32 for value in keys.values()):
        raise SetupError("既存の認証鍵を確認できません。作り直さず停止しました。", "migration_invalid")
    return keys


def migrate(source: Path, destination: Path) -> dict:
    keys = legacy_keys(source)
    (destination / "data").mkdir(parents=True, exist_ok=False)
    copy_database(source / "app/hoikuict-beta-auth.db", destination / "data/hoikuict.db")
    copy_database(source / "app/data/facility.sqlite", destination / "data/facility.sqlite")
    copy_tree(source / "app/storage", destination / "storage")
    return keys
