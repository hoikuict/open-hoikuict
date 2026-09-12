from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import sys
from contextlib import closing, contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any


BACKUP_FORMAT_VERSION = 1
JST = timezone(timedelta(hours=9), name="JST")
ATTACHMENT_TABLES = {
    "notice_attachments": "notice_attachments",
    "message_attachments": "message_attachments",
}
CONTROL_FILES = {"COMPLETE", "FAILED.json", "SHA256SUMS"}


class BackupError(RuntimeError):
    pass


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
    path = PurePosixPath(raw_path.replace("\\", "/"))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise BackupError(f"安全でない相対pathです: {raw_path}")
    if any(part in {"", "."} for part in path.parts):
        raise BackupError(f"不正な相対pathです: {raw_path}")
    return path


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
    for directory_name in ATTACHMENT_TABLES.values():
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
                if expected_size is not None and actual_size != int(expected_size):
                    size_mismatches.append(
                        {
                            "path": relative_text,
                            "expected": int(expected_size),
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
    return results


def _payload_inventory(backup_root: Path) -> list[dict[str, Any]]:
    payload_paths: list[Path] = []
    for directory_name in ("db", "storage"):
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


def _verification_payload(main_db: Path, facility_db: Path, storage_root: Path) -> dict[str, Any]:
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
    ok = main_integrity["ok"] and facility_integrity["ok"] and not attachment_failures
    return {
        "status": "ok" if ok else "failed",
        "main_database": main_integrity,
        "facility_database": facility_integrity,
        "attachments": attachments,
        "warnings": warnings,
    }


def create_backup(config: BackupConfig) -> Path:
    if not config.quiesced and not config.lock_source_writes:
        raise BackupError(
            "DBと添付の同一時点を保証するため、app停止またはsnapshot cloneを確認し"
            " --quiesced を指定するか、専用workerの書き込みlockを使ってください"
        )
    git_sha = _validate_hex(config.git_sha, label="Git SHA", minimum=7, maximum=64)
    compose_sha256 = _validate_hex(
        config.compose_sha256,
        label="Compose SHA-256",
        minimum=64,
        maximum=64,
    )
    if not config.app_image.strip():
        raise BackupError("app image IDまたはdigestが必要です")
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
    backup_id = f"open-hoikuict_{started_at.strftime('%Y%m%dT%H%M%SZ')}_{git_sha[:12]}"
    output_root.mkdir(parents=True, exist_ok=True)
    output_root.chmod(stat.S_IRWXU)
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

        verification = _verification_payload(
            backup_main_db,
            backup_facility_db,
            backup_storage,
        )
        if verification["status"] != "ok":
            raise BackupError("DBまたは添付の整合性検査に失敗しました")

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
            "provenance": {
                "git_sha": git_sha,
                "app_image": config.app_image,
                "cloudflared_image": config.cloudflared_image,
                "compose_sha256": compose_sha256,
            },
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
            "table_counts": _table_counts(backup_main_db),
            "files": _payload_inventory(partial_root),
        }
        _write_json(partial_root / "manifest.json", manifest)
        _write_json(partial_root / "verification.json", verification)
        _write_sha256sums(partial_root)
        (partial_root / "COMPLETE").write_text(backup_id + "\n", encoding="utf-8")
        (partial_root / "COMPLETE").chmod(stat.S_IRUSR | stat.S_IWUSR)
        partial_root.rename(final_root)
        verify_backup_set(final_root)
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


def verify_backup_set(backup_root: Path) -> dict[str, Any]:
    backup_root = backup_root.expanduser().resolve()
    if not backup_root.is_dir():
        raise BackupError(f"backup setが見つかりません: {backup_root}")
    complete_path = backup_root / "COMPLETE"
    if not complete_path.is_file() or complete_path.is_symlink():
        raise BackupError("COMPLETE markerがない未完了backupです")
    try:
        complete_backup_id = complete_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BackupError(f"COMPLETE markerを読み取れません: {exc}") from exc
    if complete_backup_id != backup_root.name:
        raise BackupError("COMPLETE markerのbackup IDがdirectory名と一致しません")

    entries = _read_sha256sums(backup_root)
    for relative_path, expected_digest in entries.items():
        path = backup_root.joinpath(*PurePosixPath(relative_path).parts)
        if not path.is_file() or path.is_symlink():
            raise BackupError(f"hash対象fileがありません: {relative_path}")
        actual_digest = _sha256(path)
        if actual_digest != expected_digest:
            raise BackupError(f"SHA-256が一致しません: {relative_path}")

    allowed_unhashed = {"SHA256SUMS", "COMPLETE"}
    actual_files = _all_regular_files(backup_root)
    extra_files = sorted(actual_files - set(entries) - allowed_unhashed)
    if extra_files:
        raise BackupError("SHA256SUMSにないfileがあります: " + ", ".join(extra_files))

    manifest_path = backup_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError(f"manifestを読み取れません: {exc}") from exc
    if manifest.get("format_version") != BACKUP_FORMAT_VERSION:
        raise BackupError("未対応のbackup format versionです")
    if manifest.get("backup_id") != backup_root.name:
        raise BackupError("manifestのbackup IDがdirectory名と一致しません")

    main_db = backup_root / "db" / "hoikuict.db"
    facility_db = backup_root / "db" / "facility.sqlite"
    storage_root = backup_root / "storage"
    verification = _verification_payload(main_db, facility_db, storage_root)
    if verification["status"] != "ok":
        raise BackupError("再検査でDBまたは添付の不整合を検出しました")
    expected_counts = manifest.get("table_counts")
    if expected_counts != _table_counts(main_db):
        raise BackupError("table件数がmanifestと一致しません")

    return {
        "status": "ok",
        "backup_id": manifest["backup_id"],
        "files_verified": len(entries),
        "verification": verification,
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
                )
            )
            print(f"backupを作成しました: {backup_path}")
            return 0
        if args.command == "verify":
            result = verify_backup_set(args.backup_set)
            if args.as_json:
                print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                print(
                    f"backup検証OK: {result['backup_id']} "
                    f"({result['files_verified']} files)"
                )
            return 0
    except BackupError as exc:
        print(f"backup error: {exc}", file=sys.stderr)
        return 1
    parser.error("未対応のコマンドです")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
