"""Validate and stage a whole-nursery restore. Never stop or switch the live app here."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3

from backup_schedule import default_backup_schedule, load_backup_schedule
from restore_control import RestoreError, as_jst, atomic_json, backup_identifier, read_json
from restore_validation import document_attachments, photo_check
from scripts.backup_runtime import (
    BackupConfig, BackupError, _copy_attachment_tree, _copy_sqlite_database,
    _sqlite_path_from_url, _table_counts, _verification_payload, create_backup,
    verify_backup_set,
)


@dataclass(frozen=True)
class RestorePaths:
    data: Path
    storage: Path
    backups: Path
    staging: Path

    @classmethod
    def from_environment(cls):
        database = _sqlite_path_from_url(os.getenv("HOIKUICT_DATABASE_URL", "sqlite:////data/hoikuict.db"))
        facility = Path(os.getenv("HOIKU_FACILITY_BUNREI_DB_PATH", "/data/facility.sqlite")).resolve()
        if database.name != "hoikuict.db" or facility != database.parent / "facility.sqlite":
            raise RestoreError("この配置では画面からの復元を利用できません。")
        result = cls(database.parent, Path(os.getenv("HOIKUICT_STORAGE_ROOT", "storage")).resolve(),
                     Path(os.getenv("HOIKUICT_RESTORE_BACKUP_ROOT", "/backup")).resolve(),
                     Path(os.getenv("HOIKUICT_RESTORE_STAGING_ROOT", "/restore-staging")).resolve())
        paths = (result.data, result.storage, result.backups, result.staging)
        for a in paths:
            if a.is_symlink() or any(p.is_symlink() for p in a.parents):
                raise RestoreError("復元用の保存先にリンクは使えません。")
            for b in paths:
                if a != b and (a.is_relative_to(b) or b.is_relative_to(a)):
                    raise RestoreError("復元用の保存先が業務データと重なっています。")
        if len(set(paths)) != 4:
            raise RestoreError("復元用の保存先を分離してください。")
        return result


def file_hash(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def no_links(root: Path) -> None:
    if root.is_symlink() or not root.is_dir():
        raise RestoreError("復元するファイルの保存先が不正です。")
    for p in root.rglob("*"):
        if p.is_symlink() or (not p.is_file() and not p.is_dir()):
            raise RestoreError("通常のファイル以外が含まれるため復元できません。")


def backup_path(paths: RestorePaths, backup_id: str) -> Path:
    root = paths.backups / backup_identifier(backup_id)
    no_links(root)
    if root.resolve().parent != paths.backups:
        raise RestoreError("バックアップの保存先が不正です。")
    return root


def schema(path: Path) -> list:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        return connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()


def schema_compatible(source: Path, current: Path) -> bool:
    # This release supports exactly the deployed schema, including nursery-specific tables.
    return schema(source) == schema(current)


def admin_credential(database: Path, actor_id: str) -> dict:
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("""SELECT c.login_id_normalized,c.password_hash,c.credential_version,
            c.password_changed_at,c.must_change_password,c.disabled_at,c.hash_scheme,u.is_active,u.staff_role
            FROM password_credentials c JOIN users u ON u.id=c.staff_user_id
            WHERE c.principal_type='staff' AND replace(c.staff_user_id,'-','')=?""",
            (actor_id.replace("-", ""),)).fetchone()
        if not row or not row["is_active"] or row["staff_role"] != "admin" or row["disabled_at"] \
                or row["must_change_password"] or not row["password_hash"] or row["hash_scheme"] != "argon2id":
            raise RestoreError("復元後にこの管理者でログインできないため、画面から復元できません。")
        result = dict(row)
        result["fingerprint"] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        return result


def summary_counts(database: Path, storage: Path) -> dict:
    counts = _table_counts(database)
    record_tables = ("daily_contact_entries", "daily_contact_replies", "attendance_verifications",
                     "institutional_records", "document_review_requests", "meeting_notes", "notices", "messages")
    return {"children": counts.get("children", 0), "records": sum(counts.get(t, 0) for t in record_tables),
            "files": sum(1 for p in storage.rglob("*") if p.is_file()), "photos": counts.get("profile_photos", 0)}


def verify_payload(database: Path, facility: Path, storage: Path) -> None:
    try:
        no_links(storage)
        result = _verification_payload(database, facility, storage)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            documents = document_attachments(connection, storage / "document_reviews")
        photos = photo_check(database)
        if result["status"] != "ok" or documents["status"] != "ok" or photos["status"] != "ok":
            raise RestoreError("データ・写真・添付の検査に通りませんでした。このバックアップからは復元できません。")
    except (sqlite3.Error, OSError, ValueError, BackupError) as exc:
        raise RestoreError("データ・写真・添付の検査に通りませんでした。運用担当者に確認してください。") from exc


def inspect_backup(paths: RestorePaths, backup_id: str, actor_id: str) -> dict:
    try:
        root = backup_path(paths, backup_id)
        result = verify_backup_set(root)
        manifest = read_json(root / "manifest.json")
        if manifest.get("format_version") != 1:
            raise RestoreError("このバックアップ形式は現在の本番版に対応していません。")
        allowed = set(os.getenv("HOIKUICT_RESTORE_COMPATIBLE_GIT_SHAS", "").split(","))
        allowed.discard("")
        if manifest.get("provenance", {}).get("git_sha") not in allowed:
            raise RestoreError("このアプリ版のバックアップは画面からの復元に未対応です。")
        if manifest.get("facility_ref", "") != os.getenv("HOIKU_NURSERY_REF", ""):
            raise RestoreError("この園のバックアップではありません。")
        for backup_name, live_name in (("hoikuict.db", "hoikuict.db"), ("facility.sqlite", "facility.sqlite")):
            if not schema_compatible(root / "db" / backup_name, paths.data / live_name):
                raise RestoreError("データ構造が現在のアプリ版と異なるため、画面から復元できません。")
        source_credential = admin_credential(root / "db/hoikuict.db", actor_id)
        current_credential = admin_credential(paths.data / "hoikuict.db", actor_id)
        verify_payload(root / "db/hoikuict.db", root / "db/facility.sqlite", root / "storage")
        return {"backup_id": backup_id, "backup_date": as_jst(manifest["finished_at_jst"]),
                "manifest_hash": file_hash(root / "manifest.json"), "files_verified": result["files_verified"],
                "credential_fingerprint": current_credential["fingerprint"],
                "target_credential_fingerprint": source_credential["fingerprint"],
                "before": summary_counts(paths.data / "hoikuict.db", paths.storage),
                "after": summary_counts(root / "db/hoikuict.db", root / "storage")}
    except RestoreError:
        raise
    except (OSError, ValueError, KeyError, sqlite3.Error, BackupError) as exc:
        raise RestoreError("バックアップの検査に通りませんでした。現在のデータは変更していません。") from exc


def list_backups(paths: RestorePaths) -> list[dict]:
    result = []
    if not paths.backups.is_dir():
        return result
    allowed = set(os.getenv("HOIKUICT_RESTORE_COMPATIBLE_GIT_SHAS", "").split(","))
    for root in sorted(paths.backups.glob("open-hoikuict_*"), reverse=True):
        try:
            backup_identifier(root.name)
            if root.is_symlink() or not (root / "COMPLETE").is_file():
                continue
            manifest = read_json(root / "manifest.json")
            if manifest.get("facility_ref", "") != os.getenv("HOIKU_NURSERY_REF", ""):
                continue
            eligible = manifest.get("format_version") == 1 and manifest.get("provenance", {}).get("git_sha") in allowed
            result.append({"backup_id": root.name, "date": as_jst(manifest["finished_at_jst"]),
                           "children": manifest.get("table_counts", {}).get("children", 0),
                           "eligible": eligible, "reason": "実行前に整合性を再検査します。" if eligible else "このアプリ版・形式には未対応です。"})
        except (RestoreError, KeyError, ValueError, OSError):
            continue
        if len(result) == 100:
            break
    return result


def invalidate(database: Path, job_id: str) -> dict:
    """Retire all bearer grants and queued delivery on the isolated copy only."""
    from datetime import UTC, datetime
    now = datetime.now(UTC).isoformat()
    statements = {
        "sessions": ("UPDATE auth_sessions SET revoked_at=?,revoke_reason='backup_restore' WHERE revoked_at IS NULL", (now,)),
        "tokens": ("UPDATE credential_action_tokens SET revoked_at=? WHERE revoked_at IS NULL AND consumed_at IS NULL", (now,)),
        "recoveries": ("UPDATE staff_password_recoveries SET consumed_at=? WHERE consumed_at IS NULL", (now,)),
        "registrations": ("UPDATE parent_registration_sessions SET consumed_at=? WHERE consumed_at IS NULL", (now,)),
        "invitations": ("UPDATE parent_registration_requests SET invitation_token_hash=NULL,completion_token_hash=NULL,invitation_expires_at=NULL,completion_expires_at=NULL,updated_at=? WHERE invitation_token_hash IS NOT NULL OR completion_token_hash IS NOT NULL", (now,)),
        "parent_mail": ("UPDATE parent_mail_deliveries SET status='cancelled',body='',failure_code='backup_restore',processing_started_at=NULL,lease_expires_at=NULL,next_retry_at=NULL WHERE status IN ('pending','processing')", ()),
        "staff_mail": ("UPDATE staff_mail_deliveries SET status='cancelled',body='',failure_code='backup_restore',lease_expires_at=NULL,next_retry_at=NULL WHERE status IN ('pending','processing')", ()),
        "push": ("UPDATE parent_push_delivery_targets SET status='suppressed',next_retry_at=NULL,lease_expires_at=NULL,processing_started_at=NULL,last_error_code='backup_restore',updated_at=? WHERE status IN ('pending','processing','retry_wait')", (now,)),
        "push_delivery": ("UPDATE parent_notification_deliveries SET status='suppressed',planning_lease_expires_at=NULL,completed_at=?,updated_at=?,error_message='backup_restore' WHERE channel='push' AND status IN ('pending','processing')", (now, now)),
        "receipts": ("UPDATE parent_push_delivery_targets SET shown_receipt_token_hash=NULL,clicked_receipt_token_hash=NULL WHERE shown_receipt_token_hash IS NOT NULL OR clicked_receipt_token_hash IS NOT NULL", ()),
        "calendar": ("UPDATE notification_jobs SET status='cancelled',updated_at=? WHERE status IN ('pending','processing')", (now,)),
    }
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with connection:
            result = {key: connection.execute(sql, args).rowcount for key, (sql, args) in statements.items()}
            connection.execute("INSERT INTO authentication_events(event_type,result,reason_code,principal_type,request_id,occurred_at) VALUES ('backup_restore','success','restore_invalidation','system',?,?)", (job_id, now))
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise RestoreError("復元後の関連データ検査に失敗しました。")
    return result


def prepare_copy(paths: RestorePaths, backup_id: str, job_id: str, *, suffix: str = "target") -> Path:
    root = backup_path(paths, backup_id)
    verify_backup_set(root)
    destination = paths.staging / (job_id + "-" + suffix)
    if destination.exists() or destination.is_symlink():
        raise RestoreError("復元準備先が既に存在します。作業記録を確認してください。")
    destination.mkdir(mode=0o700, parents=True)
    data = destination / "data"
    data.mkdir(mode=0o700)
    _copy_sqlite_database(root / "db/hoikuict.db", data / "hoikuict.db")
    _copy_sqlite_database(root / "db/facility.sqlite", data / "facility.sqlite")
    _copy_attachment_tree(root / "storage", destination / "storage")
    invalidate(data / "hoikuict.db", job_id)
    verify_payload(data / "hoikuict.db", data / "facility.sqlite", destination / "storage")
    return destination


def fresh_backup(paths: RestorePaths) -> str:
    config = BackupConfig(output_root=paths.backups, database_url="sqlite:///" + (paths.data / "hoikuict.db").as_posix(),
                          facility_db=paths.data / "facility.sqlite", storage_root=paths.storage,
                          git_sha=os.environ["HOIKUICT_BACKUP_GIT_SHA"], app_image=os.environ["HOIKUICT_BACKUP_APP_IMAGE"],
                          compose_sha256=os.environ["HOIKUICT_BACKUP_COMPOSE_SHA256"],
                          environment=os.getenv("HOIKUICT_ENV", "production"), facility_ref=os.getenv("HOIKU_NURSERY_REF", ""),
                          quiesced=True)
    result = create_backup(config)
    verify_backup_set(result)
    verify_payload(result / "db/hoikuict.db", result / "db/facility.sqlite", result / "storage")
    return result.name


def ensure_space(paths: RestorePaths, backup_id: str) -> None:
    root = backup_path(paths, backup_id)
    source_bytes = sum(p.stat().st_size for folder in (paths.data, paths.storage, root) for p in folder.rglob("*") if p.is_file())
    for folder in (paths.staging, paths.backups, paths.data, paths.storage):
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        if shutil.disk_usage(folder).free < source_bytes * 3 + 256 * 1024 * 1024:
            raise RestoreError("復元と直前データの退避に必要な空き容量が不足しています。")


def _replace_file(source: Path, target: Path) -> None:
    temporary = target.parent / ("." + target.name + ".restore-tmp")
    if target.is_symlink() or temporary.is_symlink():
        raise RestoreError("復元先に不正なリンクがあります。")
    shutil.copyfile(source, temporary)
    temporary.chmod(0o600)
    with temporary.open("r+b") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, target)
    if os.name != "nt":
        descriptor = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def apply_copy(paths: RestorePaths, prepared: Path) -> None:
    """Called only while both application and backup worker have acknowledged pause.

    Preserve mount-root inodes. The durable job journal precedes this non-atomic
    multi-file phase, and recovery always restores the saved pre-operation copy.
    """
    if prepared.parent != paths.staging or prepared.is_symlink():
        raise RestoreError("復元準備先が不正です。")
    no_links(prepared)
    no_links(paths.data)
    no_links(paths.storage)
    for name in ("hoikuict.db", "facility.sqlite"):
        for suffix in ("-wal", "-shm", "-journal"):
            (paths.data / (name + suffix)).unlink(missing_ok=True)
        _replace_file(prepared / "data" / name, paths.data / name)
    source = prepared / "storage"
    wanted = {p.relative_to(source) for p in source.rglob("*") if p.is_file()}
    for relative in wanted:
        target = paths.storage / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _replace_file(source / relative, target)
    for target in paths.storage.rglob("*"):
        if target.is_file() and target.relative_to(paths.storage) not in wanted:
            target.unlink()
    for target in sorted((p for p in paths.storage.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(target.iterdir()):
            target.rmdir()
    control = paths.data / "backup-control"
    control.mkdir(mode=0o700, exist_ok=True)
    try:
        schedule = load_backup_schedule(control)
    except Exception:
        schedule = default_backup_schedule()
    atomic_json(control / "schedule.json", {**schedule, "enabled": False})
    verify_payload(paths.data / "hoikuict.db", paths.data / "facility.sqlite", paths.storage)
