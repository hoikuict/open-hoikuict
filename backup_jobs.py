from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


BACKUP_JOB_SCHEMA_VERSION = 1
MAX_JOB_FILE_BYTES = 256 * 1024
JST = timezone(timedelta(hours=9), name="JST")
JOB_DIRECTORIES = ("requests", "running", "history", "rejected")


class BackupJobError(RuntimeError):
    pass


class BackupJobConflict(BackupJobError):
    pass


def backup_control_dir() -> Path:
    configured = os.getenv("HOIKUICT_BACKUP_CONTROL_DIR", "data/backup-control")
    return Path(configured).expanduser().resolve()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _iso_jst(value: datetime) -> str:
    return value.astimezone(JST).isoformat(timespec="seconds")


def _ensure_control_directories(control_dir: Path) -> None:
    control_dir.mkdir(parents=True, exist_ok=True)
    control_dir.chmod(stat.S_IRWXU)
    for name in JOB_DIRECTORIES:
        directory = control_dir / name
        directory.mkdir(exist_ok=True)
        directory.chmod(stat.S_IRWXU)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_job(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise BackupJobError(f"job fileが通常fileではありません: {path.name}")
    if path.stat().st_size > MAX_JOB_FILE_BYTES:
        raise BackupJobError(f"job fileが大きすぎます: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupJobError(f"job fileを読み取れません: {path.name}") from exc
    if not isinstance(payload, dict):
        raise BackupJobError(f"job fileの形式が不正です: {path.name}")
    if payload.get("schema_version") != BACKUP_JOB_SCHEMA_VERSION:
        raise BackupJobError(f"job schema versionが不正です: {path.name}")
    try:
        job_id = str(UUID(str(payload.get("job_id"))))
    except (TypeError, ValueError) as exc:
        raise BackupJobError(f"job IDが不正です: {path.name}") from exc
    if job_id != path.stem and path.parent.name != "history":
        raise BackupJobError(f"job IDとfile名が一致しません: {path.name}")
    payload["job_id"] = job_id
    return payload


def _active_job_paths(control_dir: Path) -> list[Path]:
    return sorted(
        list((control_dir / "requests").glob("*.json"))
        + list((control_dir / "running").glob("*.json"))
    )


def enqueue_backup(
    *,
    requested_by_id: str | None,
    requested_by_name: str,
    trigger: str = "manual",
    scheduled_slot: str | None = None,
    control_dir: Path | None = None,
) -> dict[str, Any]:
    root = (control_dir or backup_control_dir()).resolve()
    _ensure_control_directories(root)
    if _active_job_paths(root):
        raise BackupJobConflict("実行中または待機中のバックアップがあります")
    if trigger not in {"manual", "scheduled"}:
        raise BackupJobError("未対応のバックアップ起動方法です")
    if trigger == "scheduled" and not scheduled_slot:
        raise BackupJobError("定期実行の予定枠が必要です")

    now = _utc_now()
    job_id = str(uuid4())
    job = {
        "schema_version": BACKUP_JOB_SCHEMA_VERSION,
        "job_id": job_id,
        "status": "queued",
        "trigger": trigger,
        "scheduled_slot": scheduled_slot if trigger == "scheduled" else None,
        "requested_at_utc": _iso_utc(now),
        "requested_at_jst": _iso_jst(now),
        "requested_by": {
            "id": str(requested_by_id) if requested_by_id else None,
            "name": requested_by_name.strip()[:100] or "管理者",
        },
    }
    _write_json_atomic(root / "requests" / f"{job_id}.json", job)
    return job


def claim_next_backup(control_dir: Path | None = None) -> dict[str, Any] | None:
    root = (control_dir or backup_control_dir()).resolve()
    _ensure_control_directories(root)
    for request_path in sorted((root / "requests").glob("*.json")):
        running_path = root / "running" / request_path.name
        try:
            os.replace(request_path, running_path)
        except FileNotFoundError:
            continue
        try:
            job = _load_job(running_path)
        except BackupJobError:
            rejected_name = f"{_utc_now().strftime('%Y%m%dT%H%M%S%fZ')}_{running_path.name}"
            os.replace(running_path, root / "rejected" / rejected_name)
            continue
        now = _utc_now()
        job["status"] = "running"
        job["started_at_utc"] = _iso_utc(now)
        job["started_at_jst"] = _iso_jst(now)
        _write_json_atomic(running_path, job)
        return job
    return None


def finish_backup_job(
    job: dict[str, Any],
    *,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    control_dir: Path | None = None,
) -> dict[str, Any]:
    if status not in {"succeeded", "failed"}:
        raise BackupJobError(f"未対応のjob statusです: {status}")
    root = (control_dir or backup_control_dir()).resolve()
    _ensure_control_directories(root)
    job_id = str(UUID(str(job.get("job_id"))))
    now = _utc_now()
    completed = dict(job)
    completed["status"] = status
    completed["finished_at_utc"] = _iso_utc(now)
    completed["finished_at_jst"] = _iso_jst(now)
    if result is not None:
        completed["result"] = result
    if error:
        completed["error"] = str(error)[:2000]
    history_name = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}_{job_id}.json"
    _write_json_atomic(root / "history" / history_name, completed)
    (root / "running" / f"{job_id}.json").unlink(missing_ok=True)
    (root / "requests" / f"{job_id}.json").unlink(missing_ok=True)
    return completed


def recover_interrupted_jobs(control_dir: Path | None = None) -> int:
    root = (control_dir or backup_control_dir()).resolve()
    _ensure_control_directories(root)
    recovered = 0
    for running_path in sorted((root / "running").glob("*.json")):
        try:
            job = _load_job(running_path)
        except BackupJobError:
            rejected_name = f"{_utc_now().strftime('%Y%m%dT%H%M%S%fZ')}_{running_path.name}"
            os.replace(running_path, root / "rejected" / rejected_name)
            continue
        finish_backup_job(
            job,
            status="failed",
            error="バックアップ実行サービスの停止を検出したため、この実行は未完了です",
            control_dir=root,
        )
        recovered += 1
    return recovered


def list_backup_jobs(
    *,
    control_dir: Path | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    root = (control_dir or backup_control_dir()).resolve()
    _ensure_control_directories(root)
    candidates = (
        list((root / "history").glob("*.json"))
        + list((root / "running").glob("*.json"))
        + list((root / "requests").glob("*.json"))
    )
    priority = {"queued": 1, "running": 2, "succeeded": 3, "failed": 3}
    jobs_by_id: dict[str, dict[str, Any]] = {}
    for path in candidates:
        try:
            job = _load_job(path)
        except BackupJobError:
            continue
        existing = jobs_by_id.get(job["job_id"])
        if existing is None or priority.get(job.get("status"), 0) >= priority.get(
            existing.get("status"), 0
        ):
            jobs_by_id[job["job_id"]] = job
    jobs = sorted(
        jobs_by_id.values(),
        key=lambda item: str(item.get("requested_at_utc", "")),
        reverse=True,
    )
    return jobs[: max(1, min(limit, 100))]


def write_worker_heartbeat(control_dir: Path | None = None) -> dict[str, Any]:
    root = (control_dir or backup_control_dir()).resolve()
    _ensure_control_directories(root)
    now = _utc_now()
    heartbeat = {
        "schema_version": BACKUP_JOB_SCHEMA_VERSION,
        "status": "online",
        "pid": os.getpid(),
        "seen_at_utc": _iso_utc(now),
        "seen_at_jst": _iso_jst(now),
    }
    _write_json_atomic(root / "worker-heartbeat.json", heartbeat)
    return heartbeat


def worker_status(
    *,
    control_dir: Path | None = None,
    stale_after_seconds: int = 30,
) -> dict[str, Any]:
    root = (control_dir or backup_control_dir()).resolve()
    heartbeat_path = root / "worker-heartbeat.json"
    if not heartbeat_path.is_file() or heartbeat_path.is_symlink():
        return {"status": "offline", "reason": "not_started"}
    try:
        payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        seen_at = datetime.fromisoformat(str(payload["seen_at_utc"]).replace("Z", "+00:00"))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return {"status": "offline", "reason": "invalid_heartbeat"}
    age_seconds = max(0, (_utc_now() - seen_at.astimezone(UTC)).total_seconds())
    return {
        "status": "online" if age_seconds <= stale_after_seconds else "offline",
        "reason": None if age_seconds <= stale_after_seconds else "stale",
        "seen_at_jst": payload.get("seen_at_jst"),
        "age_seconds": int(age_seconds),
    }
