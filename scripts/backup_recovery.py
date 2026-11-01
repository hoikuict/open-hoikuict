"""Prepare an isolated restore without ever editing the original backup or a live DB."""
from __future__ import annotations

import sqlite3
import stat
from contextlib import closing
from pathlib import Path

from scripts.backup_runtime import (
    BackupError, _copy_attachment_tree, _copy_sqlite_database, _is_within,
    _iso_utc, _utc_now, _verification_payload, _write_json, verify_backup_set,
)
from scripts.backup_validation import identifier, portable_schedule, read_json, read_schedule_source


def _invalidate(connection: sqlite3.Connection, incident_ref: str) -> dict:
    """Single transaction: preserve credentials/audit history, retire all old bearer grants."""
    now = _iso_utc(_utc_now())
    counts = {}
    updates = {
        "sessions": ("UPDATE auth_sessions SET revoked_at=?, revoke_reason='backup_restore' WHERE revoked_at IS NULL", (now,)),
        "action_tokens": ("UPDATE credential_action_tokens SET revoked_at=? WHERE revoked_at IS NULL AND consumed_at IS NULL", (now,)),
        "staff_recoveries": ("UPDATE staff_password_recoveries SET consumed_at=? WHERE consumed_at IS NULL", (now,)),
        "registration_sessions": ("UPDATE parent_registration_sessions SET consumed_at=? WHERE consumed_at IS NULL", (now,)),
        "invitations": ("UPDATE parent_registration_requests SET invitation_token_hash=NULL, completion_token_hash=NULL, invitation_expires_at=NULL, completion_expires_at=NULL, updated_at=? WHERE invitation_token_hash IS NOT NULL OR completion_token_hash IS NOT NULL", (now,)),
        "parent_mail": ("UPDATE parent_mail_deliveries SET status='cancelled', body='', failure_code='backup_restore', processing_started_at=NULL, lease_expires_at=NULL, next_retry_at=NULL WHERE status IN ('pending','processing')", ()),
        "staff_mail": ("UPDATE staff_mail_deliveries SET status='cancelled', body='', failure_code='backup_restore', lease_expires_at=NULL, next_retry_at=NULL WHERE status IN ('pending','processing')", ()),
        "push_targets": ("UPDATE parent_push_delivery_targets SET status='suppressed', next_retry_at=NULL, lease_expires_at=NULL, processing_started_at=NULL, last_error_code='backup_restore', updated_at=? WHERE status IN ('pending','processing','retry_wait')", (now,)),
        "push_deliveries": ("UPDATE parent_notification_deliveries SET status='suppressed', planning_lease_expires_at=NULL, completed_at=?, updated_at=?, error_message='backup_restore' WHERE channel='push' AND status IN ('pending','processing')", (now, now)),
        "push_receipts": ("UPDATE parent_push_delivery_targets SET shown_receipt_token_hash=NULL, clicked_receipt_token_hash=NULL WHERE shown_receipt_token_hash IS NOT NULL OR clicked_receipt_token_hash IS NOT NULL", ()),
        "calendar_jobs": ("UPDATE notification_jobs SET status='cancelled', updated_at=? WHERE status IN ('pending','processing')", (now,)),
    }
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN IMMEDIATE")
    try:
        for key, (statement, values) in updates.items():
            counts[key] = connection.execute(statement, values).rowcount
        connection.execute(
            "INSERT INTO authentication_events(event_type,result,reason_code,principal_type,request_id,occurred_at) VALUES ('backup_restore','success','restore_invalidation','system',?,?)",
            (incident_ref, now),
        )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise BackupError("復元後の外部キー検査に失敗しました")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return counts


def prepare_restore(
    backup_set: Path, destination: Path, *, incident_ref: str,
    contract_id: str | None = None, recovery_kit_ref: str = "", isolated: bool = False,
) -> dict:
    if not isolated:
        raise BackupError("--isolatedで外部送信・公開経路の隔離を確認してください")
    identifier(incident_ref, "復元作業ID")
    if destination.exists() or destination.is_symlink() or any(path.is_symlink() for path in destination.parents):
        raise BackupError("復元先は未作成の新しいdirectoryに限ります")
    result = verify_backup_set(backup_set, contract_id=contract_id)
    backup_set = backup_set.resolve()
    destination = destination.resolve()
    if _is_within(destination, backup_set.parent) or _is_within(backup_set, destination):
        raise BackupError("backup保存領域へ復元できません")
    manifest = read_json(backup_set / "manifest.json")
    contract_id = manifest.get("schema_contract", {}).get("contract_id") or contract_id
    if not contract_id:
        raise BackupError("形式1の復元には--schema-contractによる追加検査が必要です")
    kit = manifest.get("recovery_kit_ref") or recovery_kit_ref
    identifier(kit, "復元用recovery kit ID")
    # Validate all inputs before creating the destination. A failure leaves an explicit
    # FAILED receipt and never a RESTORE_READY marker; no existing directory is replaced.
    destination.mkdir(parents=True, mode=stat.S_IRWXU)
    try:
        runtime = destination / "runtime"
        data = runtime / "data"
        data.mkdir(parents=True, mode=stat.S_IRWXU)
        _copy_sqlite_database(backup_set / "db/hoikuict.db", data / "hoikuict.db")
        _copy_sqlite_database(backup_set / "db/facility.sqlite", data / "facility.sqlite")
        _copy_attachment_tree(backup_set / "storage", runtime / "storage")
        if manifest["format_version"] == 2:
            schedule = portable_schedule(read_json(backup_set / "settings/backup-schedule.json"))
        else:
            schedule, _ = read_schedule_source(data / "backup-control/schedule.json")
        schedule["enabled"] = False
        control = data / "backup-control"
        control.mkdir(mode=stat.S_IRWXU)
        _write_json(control / "schedule.json", schedule)
        # No requests/running/history/rejected/heartbeat are imported from any source.
        with closing(sqlite3.connect(data / "hoikuict.db")) as connection:
            invalidated = _invalidate(connection, incident_ref)
        verification = _verification_payload(data / "hoikuict.db", data / "facility.sqlite",
                                             runtime / "storage", contract_id=contract_id)
        if verification["status"] != "ok":
            raise BackupError("復元先の検査に失敗しました")
        if verify_backup_set(backup_set, contract_id=contract_id)["manifest_sha256"] != result["manifest_sha256"]:
            raise BackupError("処理中に復元元が変更されました")
        receipt = {"status": "prepared", "backup_id": result["backup_id"],
                   "manifest_sha256": result["manifest_sha256"], "incident_ref": incident_ref,
                   "prepared_at_utc": _iso_utc(_utc_now()), "recovery_kit_ref": kit,
                   "schema_contract": contract_id, "legacy_gaps": result["legacy_gaps"],
                   "invalidated": invalidated, "schedule_enabled": False,
                   "verification": verification, "stages": {**result["stages"], "restored": "unconfirmed"},
                   "next_step": "隔離HTTPSでログイン・写真・添付・家庭分離を確認し、切替用は新しいdirectoryへ再準備する"}
        _write_json(destination / "restore-receipt.json", receipt)
        _write_json(destination / "RESTORE_READY", {"backup_id": result["backup_id"], "incident_ref": incident_ref})
        return receipt
    except Exception as exc:
        _write_json(destination / "RESTORE_FAILED.json", {"incident_ref": incident_ref, "error_type": type(exc).__name__})
        if isinstance(exc, BackupError):
            raise
        raise BackupError("隔離先の復元準備に失敗しました") from exc
