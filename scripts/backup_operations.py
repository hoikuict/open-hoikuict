"""Host-side copy, evidence and monitoring; never delete a retained generation."""
from __future__ import annotations

import argparse
import json
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from backup_evidence import append_receipt, operational_stages
from backup_jobs import list_backup_jobs, worker_status
from scripts.backup_runtime import (
    BackupError, _all_regular_files, _is_within, _iso_utc, _sha256, _utc_now,
    verify_backup_set,
)
from scripts.backup_validation import identifier, read_json


def replicate(backup_set: Path, destination_root: Path, *, evidence_root: Path,
              destination_ref: str, encryption_ref: str, independence_ref: str) -> dict:
    for label, value in (("複製先ID", destination_ref), ("暗号化確認記録ID", encryption_ref),
                         ("別障害系統の確認記録ID", independence_ref)):
        identifier(value, label)
    source = verify_backup_set(backup_set)
    if any(path.is_symlink() for root in (destination_root, evidence_root) for path in (root, *root.parents)):
        raise BackupError("複製先・証跡先にsymbolic linkは使えません")
    backup_set = backup_set.resolve()
    destination_root = destination_root.resolve()
    evidence_root = evidence_root.resolve()
    if (_is_within(destination_root, backup_set.parent) or _is_within(backup_set, destination_root)
            or _is_within(evidence_root, backup_set) or _is_within(evidence_root, destination_root)):
        raise BackupError("複製先・証跡先をbackup本体と分離してください")
    if source["stages"]["verified"] != "passed":
        raise BackupError("形式1は追加検査後に形式2へ変換してから複製してください")
    receipt = {"kind": "replication", "backup_id": source["backup_id"],
               "manifest_sha256": source["manifest_sha256"], "destination_ref": destination_ref,
               "encryption_ref": encryption_ref, "independence_ref": independence_ref,
               "assurance": "copy_hashes_verified; storage_properties_attested_by_operator"}
    try:
        destination_root.mkdir(parents=True, exist_ok=True, mode=stat.S_IRWXU)
        final = destination_root / backup_set.name
        if not final.exists():
            size = sum(path.stat().st_size for path in backup_set.rglob("*") if path.is_file())
            if shutil.disk_usage(destination_root).free < size * 2:
                raise BackupError("複製先の空き容量が不足しています")
            partial = destination_root / f".{backup_set.name}.{uuid4().hex}.partial"
            partial.mkdir(mode=stat.S_IRWXU)
            for relative in sorted(_all_regular_files(backup_set) - {"COMPLETE"}):
                path = partial / relative
                path.parent.mkdir(parents=True, exist_ok=True, mode=stat.S_IRWXU)
                shutil.copyfile(backup_set / relative, path)
                path.chmod(stat.S_IRUSR | stat.S_IWUSR)
            verify_backup_set(partial, _creating_id=backup_set.name)
            shutil.copyfile(backup_set / "COMPLETE", partial / "COMPLETE")
            (partial / "COMPLETE").chmod(stat.S_IRUSR | stat.S_IWUSR)
            partial.rename(final)
        result = verify_backup_set(final)
        if result["manifest_sha256"] != source["manifest_sha256"]:
            raise BackupError("複製先のmanifestが元setと一致しません")
        if _sha256(backup_set / "manifest.json") != source["manifest_sha256"]:
            raise BackupError("複製中に元setが変更されました")
        receipt.update(status="passed", files_verified=result["files_verified"])
    except Exception as exc:
        receipt.update(status="failed", error_type=type(exc).__name__)
        receipt["recorded_at_utc"] = _iso_utc(_utc_now())
        append_receipt(evidence_root, receipt)
        raise BackupError("複製に失敗しました。元setと既存世代を保持し、失敗証跡を保存しました") from exc
    receipt["recorded_at_utc"] = _iso_utc(_utc_now())
    append_receipt(evidence_root, receipt)
    return receipt


RESTORE_CHECKS = {"login", "photos", "attachments", "family_isolation", "no_external_delivery",
                  "schedule_disabled", "old_tokens_rejected", "pending_queues_cancelled", "fresh_login"}


def record_restore_test(backup_set: Path, evidence_root: Path, report: dict) -> dict:
    result = verify_backup_set(backup_set)
    if result["stages"]["verified"] != "passed":
        raise BackupError("形式1は追加検査後に形式2へ変換してください")
    if set(report) != {"test_ref", "actor_ref", "checks", "rpo_seconds", "rto_seconds"}:
        raise BackupError("復元試験報告の項目が不正です")
    identifier(report["test_ref"], "復元試験ID")
    identifier(report["actor_ref"], "確認者ID")
    if (set(report["checks"]) != RESTORE_CHECKS
            or any(type(value) is not bool for value in report["checks"].values())):
        raise BackupError("復元試験の全確認項目を真偽値で記録してください")
    if any(type(report[key]) is not int or report[key] < 0 for key in ("rpo_seconds", "rto_seconds")):
        raise BackupError("実測RPO/RTOを0以上の秒数で記録してください")
    if _is_within(evidence_root, backup_set):
        raise BackupError("復元試験証跡をbackup本体へ追加できません")
    receipt = {"kind": "restore_test", "backup_id": result["backup_id"],
               "manifest_sha256": result["manifest_sha256"], "recorded_at_utc": _iso_utc(_utc_now()),
               "status": "passed" if all(report["checks"].values()) else "failed", **report}
    append_receipt(evidence_root, receipt)
    return receipt


def monitor(output_root: Path, evidence_root: Path, *, facility_ref: str, required_destinations: list[str],
            control_dir: Path | None = None, now: datetime | None = None, max_age_hours: float = 26) -> dict:
    current = now or _utc_now()
    problems, latest = [], None
    for path in sorted(output_root.glob("open-hoikuict_*"), reverse=True):
        if not (path / "COMPLETE").is_file():
            continue
        try:
            manifest = read_json(path / "manifest.json")
            if manifest.get("facility_ref") != facility_ref:
                continue
            result = verify_backup_set(path)
            if result["stages"]["verified"] != "passed":
                problems.append("legacy_backup_requires_additional_verification")
                continue
            latest = manifest, result
            break
        except BackupError:
            problems.append("backup_verification_failed")
    if latest is None:
        problems.append("verified_backup_missing")
    else:
        manifest, result = latest
        finished = datetime.fromisoformat(manifest["finished_at_utc"].replace("Z", "+00:00"))
        if current - finished > timedelta(hours=max_age_hours):
            problems.append("daily_backup_overdue")
        stages = operational_stages(result["backup_id"], result["manifest_sha256"],
                                    root=evidence_root, required_destinations=required_destinations)
        if stages["replicated"] != "passed":
            problems.append("replication_missing_or_failed")
    for partial in output_root.glob(".*.partial"):
        failure_file = partial / "FAILED.json"
        if failure_file.is_file():
            try:
                failure = read_json(failure_file)
                failed_at = datetime.fromisoformat(failure["failed_at_utc"].replace("Z", "+00:00"))
                if latest is None or failed_at > finished:
                    problems.append("latest_backup_creation_failed")
            except (BackupError, ValueError, KeyError):
                problems.append("invalid_backup_failure_record")
        elif current.timestamp() - partial.stat().st_mtime > 2 * 3600:
            problems.append("partial_backup_stalled")
    if control_dir is not None:
        if worker_status(control_dir=control_dir).get("status") != "online":
            problems.append("worker_offline")
        jobs = list_backup_jobs(control_dir=control_dir, limit=100)
        if jobs and jobs[0].get("status") == "failed":
            problems.append("latest_job_failed")
    for label, path in (("backup", output_root),):
        if path.exists():
            usage = shutil.disk_usage(path)
            if usage.used / usage.total >= 0.8:
                problems.append(f"{label}_capacity_above_80_percent")
    tested = []
    for path in evidence_root.glob("*.json"):
        try:
            receipt = read_json(path)
            if receipt.get("kind") == "restore_test" and receipt.get("status") == "passed":
                identifier(receipt["backup_id"], "backup ID")
                # Only receipts linked to this nursery's retained backup count.
                set_manifest = output_root / receipt["backup_id"] / "manifest.json"
                if (set_manifest.is_file() and _sha256(set_manifest) == receipt["manifest_sha256"]
                        and read_json(set_manifest).get("facility_ref") == facility_ref):
                    tested.append(datetime.fromisoformat(receipt["recorded_at_utc"].replace("Z", "+00:00")))
        except (BackupError, KeyError, ValueError):
            continue
    if not tested or current - max(tested) > timedelta(days=35):
        problems.append("restore_test_overdue")
    return {"status": "failed" if problems else "ok", "checked_at_utc": _iso_utc(current),
            "problems": sorted(set(problems)), "backup_id": latest[1]["backup_id"] if latest else None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="バックアップ複製・運用証跡・外部監視")
    commands = parser.add_subparsers(dest="command", required=True)
    copy = commands.add_parser("replicate")
    copy.add_argument("backup_set", type=Path)
    copy.add_argument("--destination-root", type=Path, required=True)
    for name in ("destination-ref", "encryption-ref", "independence-ref"):
        copy.add_argument(f"--{name}", required=True)
    restore = commands.add_parser("record-restore-test")
    restore.add_argument("backup_set", type=Path)
    restore.add_argument("--report", type=Path, required=True)
    watch = commands.add_parser("monitor")
    watch.add_argument("--output-root", type=Path, required=True)
    watch.add_argument("--facility-ref", required=True)
    watch.add_argument("--required-destinations", required=True, help="確認する複製先IDのカンマ区切り")
    watch.add_argument("--control-dir", type=Path)
    watch.add_argument("--max-age-hours", type=float, default=26)
    watch.add_argument("--notify-command-file", type=Path,
                       help="異常時だけ起動するコマンド引数配列JSON。shellを使わず、結果JSONを標準入力へ渡す")
    for subparser in (copy, restore, watch):
        subparser.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "replicate":
            result = replicate(args.backup_set, args.destination_root, evidence_root=args.evidence_root,
                               destination_ref=args.destination_ref, encryption_ref=args.encryption_ref,
                               independence_ref=args.independence_ref)
        elif args.command == "record-restore-test":
            result = record_restore_test(args.backup_set, args.evidence_root, read_json(args.report))
        else:
            if not 0 < args.max_age_hours <= 48:
                raise BackupError("監視間隔の許容値は0超48時間以内です")
            targets = [identifier(value.strip(), "複製先ID") for value in args.required_destinations.split(",")]
            result = monitor(args.output_root, args.evidence_root, facility_ref=args.facility_ref,
                             required_destinations=targets, control_dir=args.control_dir, max_age_hours=args.max_age_hours)
            if result["status"] != "ok" and args.notify_command_file:
                command = read_json(args.notify_command_file)
                if not isinstance(command, list) or not command or any(not isinstance(arg, str) for arg in command):
                    raise BackupError("通知コマンドは空でない文字列配列JSONが必要です")
                completed = subprocess.run(command, input=json.dumps(result), text=True, capture_output=True,
                                           shell=False, timeout=30, check=False)
                if completed.returncode:
                    raise BackupError("監視異常を検出し、外部通知コマンドも失敗しました")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"ok", "passed"} else 1
    except (BackupError, OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
        print(f"backup operation error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
