from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import sys
from contextlib import closing, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from scripts.backup_validation import (
    CURRENT_CONTRACT, POLICY_VERSION, BackupError, document_attachments, identifier,
    load_contract, photo_check, portable_schedule, read_json, read_schedule_source,
    safe_path, schema_check,
)


BACKUP_FORMAT_VERSION = 2
JST = timezone(timedelta(hours=9), name="JST")
ATTACHMENT_TABLES = {
    "notice_attachments": "notice_attachments",
    "message_attachments": "message_attachments",
}
CONTROL_FILES = {"COMPLETE", "FAILED.json", "SHA256SUMS"}
BUSINESS_COUNT_TABLES = {
    "children", "families", "guardians", "parent_accounts", "parent_child_links", "profile_photos",
    "child_profile_histories", "child_profile_change_requests", "notices", "notice_attachments",
    "messages", "message_attachments", "document_review_requests", "attendance_records",
    "daily_contact_entries", "child_observation_logs", "plan_documents", "plan_revisions",
}


@dataclass(frozen=True)
class BackupConfig:
    output_root: Path
    database_url: str
    facility_db: Path
    storage_root: Path
    git_sha: str
    app_image: str
    compose_sha256: str
    cloudflared_image: str = "unknown"
    environment: str = "production"
    facility_ref: str = ""
    quiesced: bool = False
    lock_source_writes: bool = False
    control_dir: Path | None = None
    schema_contract: str = CURRENT_CONTRACT
    recovery_kit_ref: str = ""
    actor_ref: str = ""
    retention_class: str = "daily"
    baseline_ref: str = ""
    count_change_ref: str = ""
    max_count_drop: float = 0.2
    previous_set: Path | None = None
    converted_from: dict | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _iso_jst(value: datetime) -> str:
    return value.astimezone(JST).isoformat()


def _sqlite_path_from_url(database_url: str) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise BackupError("HOIKUICT_DATABASE_URLはfile-based SQLiteである必要があります")
    raw_path = database_url[len(prefix) :].split("?", 1)[0].split("#", 1)[0]
    if not raw_path or raw_path == ":memory:" or raw_path.startswith("file:"):
        raise BackupError("memory DBまたはSQLite URIはbackup対象にできません")
    return Path(raw_path).expanduser().resolve()


def _validate_hex(value: str, *, label: str, minimum: int, maximum: int) -> str:
    normalized = value.strip().lower()
    if not minimum <= len(normalized) <= maximum:
        raise BackupError(f"{label}の長さが不正です")
    if any(character not in "0123456789abcdef" for character in normalized):
        raise BackupError(f"{label}は16進数で指定してください")
    return normalized


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_object:
        for chunk in iter(lambda: file_object.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _safe_relative_path(raw_path: str) -> PurePosixPath:
    return safe_path(raw_path)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _assert_safe_layout(
    *, output_root: Path, main_db: Path, facility_db: Path, storage_root: Path
) -> None:
    resolved_output = output_root.resolve()
    for source_root in {main_db.parent.resolve(), facility_db.parent.resolve(), storage_root.resolve()}:
        if _is_within(resolved_output, source_root) or _is_within(source_root, resolved_output):
            raise BackupError(
                "backup出力先をruntime DBまたはstorage配下に置くことはできません"
            )


def _copy_sqlite_database(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise BackupError(f"SQLite DBが見つかりません: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with closing(sqlite3.connect(source, timeout=15)) as source_connection:
            source_connection.execute("PRAGMA busy_timeout=15000")
            with closing(sqlite3.connect(destination)) as destination_connection:
                source_connection.backup(
                    destination_connection,
                    pages=256,
                    sleep=0.05,
                )
    except sqlite3.Error as exc:
        raise BackupError(f"SQLite backupに失敗しました: {source}: {exc}") from exc
    try:
        with closing(sqlite3.connect(destination)) as destination_connection:
            journal_mode = str(
                destination_connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            ).lower()
            if journal_mode != "delete":
                raise BackupError(
                    f"backup DBをstandalone形式へ変換できませんでした: {destination}"
                )
    except sqlite3.Error as exc:
        raise BackupError(f"backup DBのjournal正規化に失敗しました: {destination}: {exc}") from exc
    destination.chmod(stat.S_IRUSR | stat.S_IWUSR)


@contextmanager
def _lock_sqlite_source_writes(database_paths: list[Path]):
    """Hold SQLite RESERVED locks while DB files and attachments are copied."""
    connections: list[sqlite3.Connection] = []
    try:
        for database_path in sorted(set(database_paths), key=str):
            connection = sqlite3.connect(
                database_path,
                timeout=15,
                isolation_level=None,
            )
            connections.append(connection)
            connection.execute("PRAGMA busy_timeout=15000")
            connection.execute("BEGIN IMMEDIATE")
        yield
    except sqlite3.Error as exc:
        raise BackupError(f"backup用のSQLite書き込みlockを取得できません: {exc}") from exc
    finally:
        for connection in reversed(connections):
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            connection.close()


def _copy_attachment_tree(source_root: Path, destination_root: Path) -> None:
    destination_root.mkdir(parents=True, exist_ok=True)
    destination_root.chmod(stat.S_IRWXU)
    for directory_name in (*ATTACHMENT_TABLES.values(), "document_reviews"):
        attachment_directory = destination_root / directory_name
        attachment_directory.mkdir(parents=True, exist_ok=True)
        attachment_directory.chmod(stat.S_IRWXU)
    if not source_root.exists():
        raise BackupError(f"storage rootが見つかりません: {source_root}")
    if not source_root.is_dir() or source_root.is_symlink():
        raise BackupError(f"storage rootが通常directoryではありません: {source_root}")

    for source in sorted(source_root.rglob("*")):
        relative = source.relative_to(source_root)
        destination = destination_root / relative
        if source.is_symlink():
            raise BackupError(f"storage内のsymbolic linkはbackupできません: {source}")
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            destination.chmod(stat.S_IRWXU)
            continue
        if not source.is_file():
            raise BackupError(f"storage内の特殊fileはbackupできません: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _sqlite_integrity(database_path: Path, *, check_foreign_keys: bool) -> dict[str, Any]:
    try:
        with closing(
            sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
        ) as connection:
            integrity_rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
            foreign_key_rows = (
                [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
                if check_foreign_keys
                else []
            )
    except sqlite3.Error as exc:
        raise BackupError(f"SQLite検査に失敗しました: {database_path}: {exc}") from exc
    return {
        "integrity": integrity_rows,
        "foreign_key_violations": foreign_key_rows,
        "ok": integrity_rows == ["ok"] and not foreign_key_rows,
    }


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_schema "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _table_counts(database_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with closing(
        sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    ) as connection:
        for table_name in sorted(_table_names(connection)):
            escaped_name = table_name.replace('"', '""')
            counts[table_name] = int(
                connection.execute(f'SELECT COUNT(*) FROM "{escaped_name}"').fetchone()[0]
            )
    return counts


def _all_regular_files(root: Path) -> set[str]:
    paths: set[str] = set()
    if not root.exists():
        return paths
    if root.is_symlink():
        raise BackupError("backup内のdirectoryにsymbolic linkがあります")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise BackupError(f"backup set内にsymbolic linkがあります: {path}")
        if path.is_file():
            paths.add(path.relative_to(root).as_posix())
        elif not path.is_dir():
            raise BackupError(f"backup set内に特殊fileがあります: {path}")
    return paths


def _attachment_verification(database_path: Path, storage_root: Path) -> dict[str, Any]:
    results: dict[str, Any] = {}
    with closing(
        sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    ) as connection:
        tables = _table_names(connection)
        for table_name, directory_name in ATTACHMENT_TABLES.items():
            destination_root = storage_root / directory_name
            actual_files = _all_regular_files(destination_root)
            if table_name not in tables:
                results[table_name] = {
                    "status": "skipped",
                    "reason": "table_not_found",
                    "actual_files": len(actual_files),
                }
                continue

            references: set[str] = set()
            missing: list[str] = []
            size_mismatches: list[dict[str, Any]] = []
            unsafe_paths: list[str] = []
            rows = connection.execute(
                f'SELECT storage_path, file_size FROM "{table_name}"'
            ).fetchall()
            for raw_storage_path, expected_size in rows:
                try:
                    relative = _safe_relative_path(str(raw_storage_path))
                except BackupError:
                    unsafe_paths.append(str(raw_storage_path))
                    continue
                relative_text = relative.as_posix()
                references.add(relative_text)
                attachment_path = destination_root.joinpath(*relative.parts)
                if not attachment_path.is_file():
                    missing.append(relative_text)
                    continue
                actual_size = attachment_path.stat().st_size
                if type(expected_size) is not int or expected_size < 0 or actual_size != expected_size:
                    size_mismatches.append(
                        {
                            "path": relative_text,
                            "expected": expected_size,
                            "actual": actual_size,
                        }
                    )

            orphan_files = sorted(actual_files - references)
            results[table_name] = {
                "status": "ok" if not (missing or size_mismatches or unsafe_paths) else "failed",
                "database_rows": len(rows),
                "actual_files": len(actual_files),
                "missing": sorted(missing),
                "size_mismatches": size_mismatches,
                "unsafe_paths": sorted(unsafe_paths),
                "orphan_files": orphan_files,
            }
        results["document_review_requests"] = document_attachments(
            connection, storage_root / "document_reviews"
        )
    return results


def _payload_inventory(backup_root: Path) -> list[dict[str, Any]]:
    payload_paths: list[Path] = []
    for directory_name in ("db", "storage", "settings"):
        directory = backup_root / directory_name
        if directory.exists():
            payload_paths.extend(path for path in directory.rglob("*") if path.is_file())
    inventory = []
    for path in sorted(payload_paths):
        if path.is_symlink():
            raise BackupError(f"payloadにsymbolic linkがあります: {path}")
        inventory.append(
            {
                "path": path.relative_to(backup_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return inventory


def _write_sha256sums(backup_root: Path) -> None:
    files = [
        path
        for path in backup_root.rglob("*")
        if path.is_file()
        and not (path.parent == backup_root and path.name in CONTROL_FILES)
    ]
    lines = [
        f"{_sha256(path)}  {path.relative_to(backup_root).as_posix()}"
        for path in sorted(files)
    ]
    sums_path = backup_root / "SHA256SUMS"
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sums_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _read_sha256sums(backup_root: Path) -> dict[str, str]:
    sums_path = backup_root / "SHA256SUMS"
    if not sums_path.is_file():
        raise BackupError("SHA256SUMSがありません")
    entries: dict[str, str] = {}
    for line_number, line in enumerate(sums_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            continue
        if "  " not in line:
            raise BackupError(f"SHA256SUMS {line_number}行目が不正です")
        digest, raw_path = line.split("  ", 1)
        _validate_hex(digest, label="SHA-256", minimum=64, maximum=64)
        safe_path = _safe_relative_path(raw_path).as_posix()
        if safe_path in entries:
            raise BackupError(f"SHA256SUMSに重複pathがあります: {safe_path}")
        entries[safe_path] = digest
    return entries


def _verification_payload(
    main_db: Path, facility_db: Path, storage_root: Path, *, contract_id: str | None = None,
) -> dict[str, Any]:
    schema = schema_check(main_db, facility_db, contract_id) if contract_id else {
        "status": "unconfirmed", "reason": "legacy_contract_required"
    }
    if schema["status"] == "failed":
        raise BackupError("必須schemaが不足しています: " + ", ".join(schema["missing"][:12]))
    main_integrity = _sqlite_integrity(main_db, check_foreign_keys=True)
    facility_integrity = _sqlite_integrity(facility_db, check_foreign_keys=False)
    attachments = _attachment_verification(main_db, storage_root)
    attachment_failures = [
        name for name, result in attachments.items() if result.get("status") == "failed"
    ]
    warnings = [
        f"{name}: orphan attachment {len(result.get('orphan_files', []))}件"
        for name, result in attachments.items()
        if result.get("orphan_files")
    ]
    photos = photo_check(main_db) if contract_id else {"status": "unconfirmed"}
    if photos.get("orphan_photo_ids"):
        warnings.append(f"orphan photo {len(photos['orphan_photo_ids'])}件")
    if photos.get("historical_guardian_references"):
        warnings.append("過去の保護者写真は画像の所有家族を基準に検査（現在の家族とは比較しない）")
    ok = (main_integrity["ok"] and facility_integrity["ok"] and not attachment_failures
          and photos["status"] != "failed")
    return {
        "status": "ok" if ok else "failed",
        "main_database": main_integrity,
        "facility_database": facility_integrity,
        "attachments": attachments,
        "schema": schema,
        "photos": photos,
        "warnings": warnings,
    }


def _provenance(config: BackupConfig) -> dict:
    git_sha = _validate_hex(config.git_sha, label="Git SHA", minimum=40, maximum=40)
    compose = _validate_hex(config.compose_sha256, label="Compose SHA-256", minimum=64, maximum=64)
    if set(git_sha) == {"0"} or set(compose) == {"0"}:
        raise BackupError("Git SHA・Compose hashのゼロ埋めは使用できません")
    for label, value in (("app image", config.app_image), ("cloudflared image", config.cloudflared_image)):
        if not re.fullmatch(r"(?:[A-Za-z0-9_./:@-]+@)?sha256:[a-f0-9]{64}", value):
            raise BackupError(f"{label}には固定digest/IDが必要です")
        if set(value.rsplit(":", 1)[-1]) == {"0"}:
            raise BackupError(f"{label}が未設定です")
    return {"git_sha": git_sha, "app_image": config.app_image,
            "cloudflared_image": config.cloudflared_image, "compose_sha256": compose}


def _count_comparison(config: BackupConfig, counts: dict, facility_counts: dict) -> dict:
    if not 0 <= config.max_count_drop < 1:
        raise BackupError("件数減少しきい値は0以上1未満です")
    previous = config.previous_set
    if previous is None and config.output_root.exists():
        candidates = []
        for path in config.output_root.glob("open-hoikuict_*"):
            if (path / "COMPLETE").exists():
                manifest = read_json(path / "manifest.json")
                if (manifest.get("environment") == config.environment
                        and manifest.get("facility_ref") == config.facility_ref):
                    candidates.append(path)
        previous = max(candidates, key=lambda path: path.name) if candidates else None
    result = {"policy_id": f"business-count-drop-{config.max_count_drop:g}-v1",
              "max_drop": config.max_count_drop, "approval_ref": config.count_change_ref or None}
    if config.count_change_ref:
        identifier(config.count_change_ref, "件数変更承認ID")
    if previous is None:
        identifier(config.baseline_ref, "初回件数確認ID（--baseline-ref）")
        return {**result, "initial": True, "baseline_ref": config.baseline_ref}
    manifest = read_json(previous / "manifest.json")
    verify_backup_set(previous, contract_id=config.schema_contract if manifest.get("format_version") == 1 else None)
    if (manifest["environment"] != config.environment or manifest["facility_ref"] != config.facility_ref):
        raise BackupError("比較元の環境・施設が一致しません")
    old = {"main": manifest["table_counts"],
           "facility": manifest.get("facility_table_counts") or _table_counts(previous / "db/facility.sqlite")}
    result.update(initial=False, backup_id=manifest["backup_id"], manifest_sha256=_sha256(previous / "manifest.json"),
                  table_counts=old)
    _check_count_drop(result, {"main": counts, "facility": facility_counts})
    return result


def _check_count_drop(comparison: dict, counts: dict) -> None:
    if not isinstance(comparison, dict) or type(comparison.get("initial")) is not bool:
        raise BackupError("前回件数比較の記録が不正です")
    threshold = comparison.get("max_drop")
    if type(threshold) not in (int, float) or not 0 <= threshold < 1:
        raise BackupError("件数減少しきい値が不正です")
    if comparison.get("policy_id") != f"business-count-drop-{threshold:g}-v1":
        raise BackupError("件数比較基準IDが不正です")
    if comparison["initial"]:
        identifier(comparison.get("baseline_ref"), "初回件数確認ID")
        return
    identifier(comparison.get("backup_id"), "前回backup ID")
    _validate_hex(comparison.get("manifest_sha256", ""), label="前回manifest hash", minimum=64, maximum=64)
    if comparison.get("approval_ref"):
        identifier(comparison["approval_ref"], "件数変更承認ID")
    old_counts = comparison.get("table_counts")
    if not isinstance(old_counts, dict) or set(old_counts) != {"main", "facility"}:
        raise BackupError("前回件数がありません")
    for database, old in old_counts.items():
        if not isinstance(old, dict):
            raise BackupError("前回件数の形式が不正です")
        for table, value in old.items():
            if type(value) is not int or value < 0:
                raise BackupError("前回件数が不正です")
            if database == "main" and table not in BUSINESS_COUNT_TABLES:
                continue
            if value and counts[database].get(table, 0) < value * (1 - threshold) and not comparison.get("approval_ref"):
                raise BackupError(f"前回からの件数減少がしきい値を超えました: {database}.{table}")


def create_backup(config: BackupConfig) -> Path:
    if not config.quiesced and not config.lock_source_writes:
        raise BackupError(
            "DBと添付の同一時点を保証するため、app停止またはsnapshot cloneを確認し"
            " --quiesced を指定するか、専用workerの書き込みlockを使ってください"
        )
    provenance = _provenance(config)
    git_sha = provenance["git_sha"]
    identifier(config.recovery_kit_ref, "recovery kit ID（--recovery-kit-ref）")
    identifier(config.actor_ref, "実施者/job ID（--actor-ref）")
    if config.retention_class not in {"daily", "monthly", "change"}:
        raise BackupError("保持区分はdaily/monthly/changeです")
    _, contract_hash = load_contract(config.schema_contract)
    main_db = _sqlite_path_from_url(config.database_url)
    facility_db = config.facility_db.expanduser().resolve()
    storage_root = config.storage_root.expanduser().resolve()
    output_root = config.output_root.expanduser().resolve()
    _assert_safe_layout(
        output_root=output_root,
        main_db=main_db,
        facility_db=facility_db,
        storage_root=storage_root,
    )
    if not main_db.is_file():
        raise BackupError(f"main DBが見つかりません: {main_db}")
    if not facility_db.is_file():
        raise BackupError(f"facility DBが見つかりません: {facility_db}")

    started_at = _utc_now()
    backup_id = f"open-hoikuict_{started_at.strftime('%Y%m%dT%H%M%S%fZ')}_{git_sha[:12]}_{uuid4().hex[:8]}"
    output_root.mkdir(parents=True, exist_ok=True)
    output_root.chmod(stat.S_IRWXU)
    estimate = main_db.stat().st_size + facility_db.stat().st_size + 65536
    estimate += sum(path.stat().st_size for path in storage_root.rglob("*") if path.is_file())
    previous_sizes = [sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())
                      for folder in output_root.glob("open-hoikuict_*") if (folder / "COMPLETE").is_file()]
    required_free = 2 * max([estimate, *previous_sizes])
    free_bytes = shutil.disk_usage(output_root).free
    if free_bytes < required_free:
        raise BackupError("backup保存先の空き容量が不足しています（見積量/既存setの2倍が必要）")
    partial_root = output_root / f".{backup_id}.partial"
    final_root = output_root / backup_id
    if partial_root.exists() or final_root.exists():
        raise BackupError(f"同じbackup IDが既に存在します: {backup_id}")
    partial_root.mkdir(mode=stat.S_IRWXU)

    try:
        backup_main_db = partial_root / "db" / "hoikuict.db"
        backup_facility_db = partial_root / "db" / "facility.sqlite"
        backup_storage = partial_root / "storage"
        source_lock = (
            _lock_sqlite_source_writes([main_db, facility_db])
            if config.lock_source_writes
            else nullcontext()
        )
        with source_lock:
            _copy_sqlite_database(main_db, backup_main_db)
            _copy_sqlite_database(facility_db, backup_facility_db)
            _copy_attachment_tree(storage_root, backup_storage)
            schedule, settings_source = read_schedule_source(
                (config.control_dir or main_db.parent / "backup-control") / "schedule.json"
            )
            (partial_root / "settings").mkdir(mode=stat.S_IRWXU)
            _write_json(partial_root / "settings/backup-schedule.json", schedule)

        verification = _verification_payload(
            backup_main_db,
            backup_facility_db,
            backup_storage,
            contract_id=config.schema_contract,
        )
        if verification["status"] != "ok":
            _write_json(partial_root / "verification.json", verification)
            raise BackupError("DB・写真または添付の整合性検査に失敗しました")

        counts = _table_counts(backup_main_db)
        facility_counts = _table_counts(backup_facility_db)
        comparison = _count_comparison(config, counts, facility_counts)

        finished_at = _utc_now()
        manifest = {
            "format_version": BACKUP_FORMAT_VERSION,
            "backup_id": backup_id,
            "status": "complete",
            "started_at_utc": _iso_utc(started_at),
            "finished_at_utc": _iso_utc(finished_at),
            "started_at_jst": _iso_jst(started_at),
            "finished_at_jst": _iso_jst(finished_at),
            "environment": config.environment,
            "facility_ref": config.facility_ref,
            "provenance": provenance,
            "verification_policy_version": POLICY_VERSION,
            "schema_contract": {"contract_id": config.schema_contract, "sha256": contract_hash},
            "recovery_kit_ref": config.recovery_kit_ref,
            "actor_ref": config.actor_ref,
            "retention_class": config.retention_class,
            "settings_source": settings_source,
            "count_comparison": comparison,
            "capacity": {"free_bytes": free_bytes, "required_free_bytes": required_free},
            "converted_from": config.converted_from,
            "sqlite_version": sqlite3.sqlite_version,
            "source": {
                "database_path": str(main_db),
                "facility_database_path": str(facility_db),
                "storage_root": str(storage_root),
                "method": (
                    "sqlite_online_backup_with_source_write_lock"
                    if config.lock_source_writes
                    else "sqlite_online_backup_from_quiesced_source"
                ),
            },
            "table_counts": counts,
            "facility_table_counts": facility_counts,
            "files": _payload_inventory(partial_root),
        }
        manifest["attachment_totals"] = {
            "database_records": sum(value.get("database_rows", 0) for value in verification["attachments"].values()),
            "files": sum(entry["path"].startswith("storage/") for entry in manifest["files"]),
            "bytes": sum(entry["bytes"] for entry in manifest["files"] if entry["path"].startswith("storage/")),
        }
        _write_json(partial_root / "manifest.json", manifest)
        _write_json(partial_root / "verification.json", verification)
        _write_sha256sums(partial_root)
        verify_backup_set(partial_root, _creating_id=backup_id)
        (partial_root / "COMPLETE").write_text(backup_id + "\n", encoding="utf-8")
        (partial_root / "COMPLETE").chmod(stat.S_IRUSR | stat.S_IWUSR)
        partial_root.rename(final_root)
        return final_root
    except Exception as exc:
        failure = {
            "backup_id": backup_id,
            "failed_at_utc": _iso_utc(_utc_now()),
            "error": str(exc),
        }
        failure_root = partial_root if partial_root.exists() else final_root
        if failure_root.exists():
            (failure_root / "COMPLETE").unlink(missing_ok=True)
            _write_json(failure_root / "FAILED.json", failure)
        if isinstance(exc, BackupError):
            raise
        raise BackupError(f"backup作成に失敗しました: {exc}") from exc


def verify_backup_set(
    backup_root: Path, *, contract_id: str | None = None, _creating_id: str | None = None,
) -> dict[str, Any]:
    try:
        return _verify_backup_set(backup_root, contract_id=contract_id, creating_id=_creating_id)
    except BackupError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise BackupError("backup検査に失敗しました（形式・DB・fileを確認してください）") from exc


def convert_legacy(backup_set: Path, *, output_root: Path, contract_id: str,
                   recovery_kit_ref: str, actor_ref: str, baseline_ref: str) -> Path:
    result = verify_backup_set(backup_set, contract_id=contract_id)
    if result["format_version"] != 1:
        raise BackupError("変換対象は形式1に限ります")
    manifest = read_json(backup_set / "manifest.json")
    return create_backup(BackupConfig(
        output_root=output_root, database_url=f"sqlite:///{(backup_set / 'db/hoikuict.db').resolve()}",
        facility_db=backup_set / "db/facility.sqlite", storage_root=backup_set / "storage",
        **manifest["provenance"], environment=manifest["environment"], facility_ref=manifest["facility_ref"],
        schema_contract=contract_id, recovery_kit_ref=recovery_kit_ref, actor_ref=actor_ref,
        baseline_ref=baseline_ref, quiesced=True,
        converted_from={"backup_id": result["backup_id"], "manifest_sha256": result["manifest_sha256"],
                        "settings_continuity": "unconfirmed_default_disabled"},
    ))


def _verify_backup_set(backup_root: Path, *, contract_id: str | None, creating_id: str | None) -> dict:
    if backup_root.is_symlink():
        raise BackupError("backup setにsymbolic linkは使えません")
    backup_root = backup_root.expanduser().resolve()
    if not backup_root.is_dir():
        raise BackupError(f"backup setが見つかりません: {backup_root}")
    complete_path = backup_root / "COMPLETE"
    expected_id = creating_id or backup_root.name
    if not creating_id and (not complete_path.is_file() or complete_path.is_symlink()):
        raise BackupError("COMPLETE markerがない未完了backupです")
    try:
        complete_backup_id = creating_id or complete_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BackupError(f"COMPLETE markerを読み取れません: {exc}") from exc
    if complete_backup_id != expected_id:
        raise BackupError("COMPLETE markerのbackup IDがdirectory名と一致しません")

    actual_files = _all_regular_files(backup_root)
    entries = _read_sha256sums(backup_root)
    if not {"manifest.json", "verification.json", "db/hoikuict.db", "db/facility.sqlite"} <= set(entries):
        raise BackupError("必須fileがSHA256SUMSにありません")
    if set(entries) & CONTROL_FILES:
        raise BackupError("管理fileをSHA256SUMSの対象にできません")
    for relative_path, expected_digest in entries.items():
        path = backup_root.joinpath(*PurePosixPath(relative_path).parts)
        if not path.is_file() or path.is_symlink():
            raise BackupError(f"hash対象fileがありません: {relative_path}")
        actual_digest = _sha256(path)
        if actual_digest != expected_digest:
            raise BackupError(f"SHA-256が一致しません: {relative_path}")

    allowed_unhashed = {"SHA256SUMS", "COMPLETE"}
    extra_files = sorted(actual_files - set(entries) - allowed_unhashed)
    if extra_files:
        raise BackupError("SHA256SUMSにないfileがあります: " + ", ".join(extra_files))

    manifest = read_json(backup_root / "manifest.json")
    version = manifest.get("format_version")
    if type(version) is not int or version not in (1, 2):
        raise BackupError("未対応のbackup format versionです")
    if manifest.get("backup_id") != expected_id:
        raise BackupError("manifestのbackup IDがdirectory名と一致しません")

    main_db = backup_root / "db" / "hoikuict.db"
    facility_db = backup_root / "db" / "facility.sqlite"
    storage_root = backup_root / "storage"
    gaps = []
    if manifest.get("files") != _payload_inventory(backup_root):
        raise BackupError("payload一覧・size・hashがmanifestと一致しません")
    if set(entries) != {entry["path"] for entry in manifest["files"]} | {"manifest.json", "verification.json"}:
        raise BackupError("SHA256SUMSとmanifestの対象が一致しません")
    if version == 2:
        if manifest.get("status") != "complete":
            raise BackupError("manifestの完了状態が不正です")
        started = datetime.fromisoformat(manifest["started_at_utc"].replace("Z", "+00:00"))
        finished = datetime.fromisoformat(manifest["finished_at_utc"].replace("Z", "+00:00"))
        if started.tzinfo is None or finished.tzinfo is None or finished < started:
            raise BackupError("backupの取得時刻が不正です")
        if (datetime.fromisoformat(manifest["started_at_jst"]) != started
                or datetime.fromisoformat(manifest["finished_at_jst"]) != finished):
            raise BackupError("backup取得時刻のUTC/JSTが一致しません")
        contract_record = manifest["schema_contract"]
        stored_contract = contract_record["contract_id"]
        if contract_id and contract_id != stored_contract:
            raise BackupError("指定したschema契約がbackupと異なります")
        contract_id = stored_contract
        _, contract_hash = load_contract(contract_id)
        if contract_hash != contract_record["sha256"] or manifest.get("verification_policy_version") != POLICY_VERSION:
            raise BackupError("schema契約・検査基準版が一致しません")
        _provenance(BackupConfig(output_root=backup_root, database_url="", facility_db=facility_db,
                                 storage_root=storage_root, **manifest["provenance"]))
        identifier(manifest["recovery_kit_ref"], "recovery kit ID")
        identifier(manifest["actor_ref"], "実施者/job ID")
        if manifest["retention_class"] not in ("daily", "monthly", "change"):
            raise BackupError("保持区分が不正です")
        if manifest["settings_source"] not in ("default", "stored"):
            raise BackupError("設定の取得元が不正です")
        portable_schedule(read_json(backup_root / "settings/backup-schedule.json"))
        if manifest["facility_table_counts"] != _table_counts(facility_db):
            raise BackupError("施設文例table件数がmanifestと一致しません")
        _check_count_drop(manifest["count_comparison"],
                          {"main": _table_counts(main_db), "facility": _table_counts(facility_db)})
    else:
        gaps = ["schedule_not_saved", "legacy_provenance_and_baseline_require_review"]
        if not contract_id:
            gaps.append("application_schema_and_photos_not_verified")
    verification = _verification_payload(main_db, facility_db, storage_root, contract_id=contract_id)
    if verification["status"] != "ok":
        raise BackupError("再検査でDBまたは添付の不整合を検出しました")
    if version == 2 and manifest["attachment_totals"] != {
        "database_records": sum(value.get("database_rows", 0) for value in verification["attachments"].values()),
        "files": sum(entry["path"].startswith("storage/") for entry in manifest["files"]),
        "bytes": sum(entry["bytes"] for entry in manifest["files"] if entry["path"].startswith("storage/")),
    }:
        raise BackupError("添付の集計がmanifestと一致しません")
    expected_counts = manifest.get("table_counts")
    if expected_counts != _table_counts(main_db):
        raise BackupError("table件数がmanifestと一致しません")

    saved_verification = read_json(backup_root / "verification.json")
    if saved_verification.get("status") != "ok":
        raise BackupError("保存時の検査結果が合格ではありません")
    return {
        "status": "ok",
        "format_version": version,
        "backup_id": manifest["backup_id"],
        "manifest_sha256": _sha256(backup_root / "manifest.json"),
        "files_verified": len(entries),
        "verification": verification,
        "stages": {"acquired": "passed", "verified": "passed" if version == 2 else "unconfirmed",
                   "replicated": "unconfirmed", "restored": "unconfirmed"},
        "legacy_gaps": gaps,
        "consistency": manifest.get("source", {}).get("method", "unknown"),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backup-runtime",
        description="open-hoikuictのSQLite・添付backup setを作成・検証します",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="backup setを作成します")
    create_parser.add_argument("--output-root", type=Path, required=True)
    create_parser.add_argument(
        "--database-url",
        default=os.getenv("HOIKUICT_DATABASE_URL", "sqlite:///./hoikuict.db"),
    )
    create_parser.add_argument(
        "--facility-db",
        type=Path,
        default=Path(os.getenv("HOIKU_FACILITY_BUNREI_DB_PATH", "data/facility.sqlite")),
    )
    create_parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(os.getenv("HOIKUICT_STORAGE_ROOT", "storage")),
    )
    create_parser.add_argument("--git-sha", required=True)
    create_parser.add_argument("--app-image", required=True)
    create_parser.add_argument("--compose-sha256", required=True)
    create_parser.add_argument("--cloudflared-image", default="unknown")
    create_parser.add_argument("--control-dir", type=Path,
                               default=Path(os.environ["HOIKUICT_BACKUP_CONTROL_DIR"]) if os.getenv("HOIKUICT_BACKUP_CONTROL_DIR") else None)
    create_parser.add_argument("--schema-contract", default=CURRENT_CONTRACT)
    create_parser.add_argument("--recovery-kit-ref", default=os.getenv("HOIKUICT_BACKUP_RECOVERY_KIT_REF", ""))
    create_parser.add_argument("--actor-ref", required=True)
    create_parser.add_argument("--retention-class", choices=("daily", "monthly", "change"), default="daily")
    create_parser.add_argument("--baseline-ref", default=os.getenv("HOIKUICT_BACKUP_BASELINE_REF", ""))
    create_parser.add_argument("--count-change-ref", default="")
    create_parser.add_argument("--max-count-drop", type=float, default=0.2)
    create_parser.add_argument("--previous-set", type=Path)
    create_parser.add_argument(
        "--environment",
        default=os.getenv("HOIKUICT_ENV", "production"),
    )
    create_parser.add_argument(
        "--facility-ref",
        default=os.getenv("HOIKU_NURSERY_REF", ""),
    )
    create_parser.add_argument(
        "--quiesced",
        action="store_true",
        required=True,
        help="app停止またはsnapshot clone上の読取りであることを確認します",
    )

    verify_parser = subparsers.add_parser("verify", help="backup setを再検査します")
    verify_parser.add_argument("backup_set", type=Path)
    verify_parser.add_argument("--json", action="store_true", dest="as_json")
    verify_parser.add_argument("--schema-contract", help="形式1の追加検査に使う登録済み契約ID")

    restore_parser = subparsers.add_parser("prepare-restore", help="新しい隔離先だけに復元し認証・待機配送を失効します")
    restore_parser.add_argument("backup_set", type=Path)
    restore_parser.add_argument("--destination", type=Path, required=True)
    restore_parser.add_argument("--incident-ref", required=True)
    restore_parser.add_argument("--recovery-kit-ref", default="")
    restore_parser.add_argument("--schema-contract")
    restore_parser.add_argument("--isolated", action="store_true", required=True,
                                help="復元先が外部送信・公開経路から隔離されていることを確認します")
    convert_parser = subparsers.add_parser("convert-legacy", help="形式1を追加検査し新しい形式2 setへ変換します")
    convert_parser.add_argument("backup_set", type=Path)
    convert_parser.add_argument("--output-root", type=Path, required=True)
    convert_parser.add_argument("--schema-contract", required=True)
    convert_parser.add_argument("--recovery-kit-ref", required=True)
    convert_parser.add_argument("--actor-ref", required=True)
    convert_parser.add_argument("--baseline-ref", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            backup_path = create_backup(
                BackupConfig(
                    output_root=args.output_root,
                    database_url=args.database_url,
                    facility_db=args.facility_db,
                    storage_root=args.storage_root,
                    git_sha=args.git_sha,
                    app_image=args.app_image,
                    compose_sha256=args.compose_sha256,
                    cloudflared_image=args.cloudflared_image,
                    environment=args.environment,
                    facility_ref=args.facility_ref,
                    quiesced=args.quiesced,
                    control_dir=args.control_dir,
                    schema_contract=args.schema_contract,
                    recovery_kit_ref=args.recovery_kit_ref,
                    actor_ref=args.actor_ref,
                    retention_class=args.retention_class,
                    baseline_ref=args.baseline_ref,
                    count_change_ref=args.count_change_ref,
                    max_count_drop=args.max_count_drop,
                    previous_set=args.previous_set,
                )
            )
            print(f"backupを作成しました: {backup_path}")
            return 0
        if args.command == "verify":
            result = verify_backup_set(args.backup_set, contract_id=args.schema_contract)
            if args.as_json:
                print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(
                    f"backup検証OK: {result['backup_id']} "
                    f"({result['files_verified']} files)"
                )
                if result["legacy_gaps"]:
                    print("形式1の未確認項目: " + ", ".join(result["legacy_gaps"]))
                    print("基本検査の成功です。追加検査・設定再準備と複製・復元試験を確認してください。")
            return 0
        if args.command == "prepare-restore":
            from scripts.backup_recovery import prepare_restore
            result = prepare_restore(args.backup_set, args.destination, incident_ref=args.incident_ref,
                                     contract_id=args.schema_contract, recovery_kit_ref=args.recovery_kit_ref,
                                     isolated=args.isolated)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "convert-legacy":
            path = convert_legacy(args.backup_set, output_root=args.output_root, contract_id=args.schema_contract,
                                  recovery_kit_ref=args.recovery_kit_ref, actor_ref=args.actor_ref,
                                  baseline_ref=args.baseline_ref)
            print(f"新しいbackupを作成しました: {path}")
            return 0
    except BackupError as exc:
        print(f"backup error: {exc}", file=sys.stderr)
        return 1
    parser.error("未対応のコマンドです")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
