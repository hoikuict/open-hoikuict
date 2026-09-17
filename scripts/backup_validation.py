"""Read-only application contracts used by backup and isolated recovery."""
from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import warnings
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image


CURRENT_CONTRACT = "spec-changes-20260917"
POLICY_VERSION = 2
SCHEDULE_KEYS = {"schema_version", "enabled", "frequency", "run_time", "weekday", "timezone"}


class BackupError(RuntimeError):
    pass


def safe_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise BackupError("不正な相対pathです")
    parts = value.split("/")
    if any(part in {"", ".", ".."} or ":" in part for part in parts):
        raise BackupError("安全でない相対pathです")
    if any(ord(char) < 32 for char in value):
        raise BackupError("不正な相対pathです")
    return PurePosixPath(value)


def read_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise BackupError(f"通常のJSON fileではありません: {path.name}")
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
    except (OSError, ValueError, UnicodeError) as exc:
        raise BackupError(f"JSONを読み取れません: {path.name}") from exc


def identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        raise BackupError(f"{label}には個人情報を含まない運用記録IDが必要です")
    return value


def load_contract(contract_id: str = CURRENT_CONTRACT) -> tuple[dict, str]:
    identifier(contract_id, "schema契約ID")
    path = Path(__file__).parent / "backup_contracts" / f"{contract_id}.json"
    contract = read_json(path)
    if contract.get("contract_id") != contract_id:
        raise BackupError("schema契約IDが一致しません")
    return contract, hashlib.sha256(path.read_bytes()).hexdigest()


def schema_check(main_db: Path, facility_db: Path, contract_id: str) -> dict:
    contract, digest = load_contract(contract_id)
    missing = []
    for name, path in (("main", main_db), ("facility", facility_db)):
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            for table, columns in contract[name].items():
                if table not in tables:
                    missing.append(f"{name}.{table}")
                    continue
                quoted = table.replace('"', '""')
                actual = {row[1] for row in connection.execute(f'PRAGMA table_info("{quoted}")')}
                missing.extend(f"{name}.{table}.{column}" for column in columns if column not in actual)
    return {"status": "failed" if missing else "ok", "contract_id": contract_id,
            "sha256": digest, "missing": missing}


def portable_schedule(value: Any, *, stored: bool = False) -> dict:
    if not isinstance(value, dict):
        raise BackupError("定期実行設定の形式が不正です")
    if not stored and set(value) != SCHEDULE_KEYS:
        raise BackupError("定期実行設定の保存項目が不正です")
    schedule = {key: value.get(key) for key in SCHEDULE_KEYS}
    if stored:
        schedule["timezone"] = value.get("timezone", "Asia/Tokyo")
    if (type(schedule["schema_version"]) is not int or schedule["schema_version"] != 1
            or type(schedule["enabled"]) is not bool
            or schedule["frequency"] not in ("daily", "weekly")
            or not isinstance(schedule["run_time"], str)
            or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", schedule["run_time"])
            or type(schedule["weekday"]) is not int or schedule["weekday"] not in range(7)
            or schedule["timezone"] != "Asia/Tokyo"):
        raise BackupError("定期実行設定の値・型・timezoneが不正です")
    return schedule


def read_schedule_source(path: Path) -> tuple[dict, str]:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise BackupError("定期実行設定にsymbolic linkは使えません")
    if not path.exists():
        return {"schema_version": 1, "enabled": False, "frequency": "daily",
                "run_time": "02:00", "weekday": 0, "timezone": "Asia/Tokyo"}, "default"
    if path.stat().st_size > 64 * 1024:
        raise BackupError("定期実行設定fileが大きすぎます")
    return portable_schedule(read_json(path), stored=True), "stored"


def document_attachments(connection: sqlite3.Connection, root: Path) -> dict:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    if "document_review_requests" not in tables:
        return {"status": "skipped", "reason": "table_not_found"}
    errors, references = [], set()
    rows = connection.execute("SELECT id, attachments FROM document_review_requests").fetchall()
    for row_id, raw in rows:
        try:
            values = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(values, list):
                raise ValueError("attachment list")
            for item in values:
                if not isinstance(item, dict) or type(item.get("size")) is not int or item["size"] < 0:
                    raise ValueError("attachment entry")
                relative = safe_path(item.get("path"))
                references.add(relative.as_posix())
                path = root.joinpath(*relative.parts)
                if (not path.is_file() or path.is_symlink()
                        or path.stat().st_size != item["size"]):
                    raise ValueError("missing/size")
        except (ValueError, TypeError, BackupError):
            errors.append(row_id)
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    return {"status": "failed" if errors else "ok", "database_rows": len(rows),
            "actual_files": len(actual), "invalid_request_ids": errors,
            "orphan_files": sorted(actual - references)}


def photo_check(database: Path) -> dict:
    errors, referenced, historical = [], set(), 0
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        if "profile_photos" not in tables:
            return {"status": "skipped", "reason": "table_not_found"}
        # Read one BLOB at a time; a photo-rich nursery DB must not be loaded into RAM.
        owners = {}
        for row in connection.execute("SELECT id, child_id, family_id, content FROM profile_photos"):
            owners[row["id"]] = (row["child_id"], row["family_id"])
            try:
                if (row["child_id"] is None) == (row["family_id"] is None):
                    raise ValueError("owner")
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(row["content"])) as image:
                        image.verify()
                    with Image.open(io.BytesIO(row["content"])) as image:
                        image.load()
            except (OSError, ValueError, TypeError, Image.DecompressionBombWarning, Image.DecompressionBombError):
                errors.append({"source": "profile_photos", "id": row["id"], "reason": "invalid_image_or_owner"})

        children = {row["id"]: row["family_id"] for row in connection.execute("SELECT id, family_id FROM children")}

        def reference(value, source, row_id, child_id=None, family_id=None, historical_guardian=False):
            nonlocal historical
            if value in (None, ""):
                return
            if not isinstance(value, str) or value not in owners:
                errors.append({"source": source, "id": row_id, "reason": "missing_photo"})
                return
            referenced.add(value)
            owner_child, owner_family = owners[value]
            valid = owner_child == child_id and owner_family is None if child_id is not None else (
                owner_child is None and owner_family is not None
                and (historical_guardian or owner_family == family_id)
            )
            if historical_guardian:
                historical += 1
            if not valid:
                errors.append({"source": source, "id": row_id, "reason": "wrong_photo_owner"})

        def scan(value, source, row_id, child_id, family_id, historical_guardian=False, field=""):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in ("photo_id", "g1_photo_id", "g2_photo_id"):
                        guardian = key != "photo_id" or field in ("guardians", "guardians_data")
                        if isinstance(child, dict):
                            parts = ("old_photo_id", "new_photo_id") if (
                                "old_photo_id" in child or "new_photo_id" in child
                            ) else ("old", "new")
                            for part in parts:
                                reference(child.get(part), source, row_id,
                                          child_id=None if guardian else child_id, family_id=family_id,
                                          historical_guardian=guardian and historical_guardian)
                        else:
                            reference(child, source, row_id, child_id=None if guardian else child_id,
                                      family_id=family_id, historical_guardian=guardian and historical_guardian)
                    elif isinstance(child, (dict, list)):
                        scan(child, source, row_id, child_id, family_id, historical_guardian, key)
            elif isinstance(value, list):
                for child in value:
                    scan(child, source, row_id, child_id, family_id, historical_guardian, field)

        def parse(raw, source, row_id):
            try:
                value = json.loads(raw) if isinstance(raw, str) else raw
                if value is not None and not isinstance(value, dict):
                    raise ValueError("profile object")
                return value
            except ValueError:
                errors.append({"source": source, "id": row_id, "reason": "invalid_json"})
                return None

        for row in connection.execute("SELECT id, photo_id FROM children"):
            reference(row["photo_id"], "children", row["id"], child_id=row["id"])
        for row in connection.execute("SELECT id, child_id, photo_id FROM guardians"):
            reference(row["photo_id"], "guardians", row["id"], family_id=children.get(row["child_id"]))
        for row in connection.execute("SELECT id, shared_profile FROM families"):
            scan(parse(row["shared_profile"], "families", row["id"]), "families", row["id"], None, row["id"])
        for table, fields in (("child_profile_histories", ("snapshot", "changes")),
                              ("child_profile_change_requests", ("request_data", "change_details"))):
            for row in connection.execute(f'SELECT * FROM "{table}"'):
                for field in fields:
                    scan(parse(row[field], table, row["id"]), table, row["id"], row["child_id"],
                         children.get(row["child_id"]), True)
    return {"status": "failed" if errors else "ok", "images": len(owners), "errors": errors,
            "orphan_photo_ids": sorted(set(owners) - referenced),
            "historical_guardian_references": historical,
            "historical_ownership_basis": "stored_photo_family_owner"}
