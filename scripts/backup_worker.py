from __future__ import annotations

import argparse
import hashlib
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, Thread

from backup_jobs import (
    BackupJobConflict,
    backup_control_dir,
    claim_next_backup,
    enqueue_backup,
    finish_backup_job,
    list_backup_jobs,
    recover_interrupted_jobs,
    write_worker_heartbeat,
)
from backup_schedule import BackupScheduleError, due_schedule_slot, load_backup_schedule
from scripts.backup_runtime import BackupConfig, create_backup, verify_backup_set


logger = logging.getLogger("open_hoikuict.backup_worker")
UNCONFIGURED_GIT_SHA = "0" * 40
UNCONFIGURED_COMPOSE_SHA256 = "0" * 64


@dataclass(frozen=True)
class BackupWorkerSettings:
    control_dir: Path
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_object:
        for chunk in iter(lambda: file_object.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compose_sha_from_environment() -> str:
    configured = os.getenv("HOIKUICT_BACKUP_COMPOSE_SHA256", "").strip()
    if configured:
        return configured
    compose_path = Path(
        os.getenv("HOIKUICT_BACKUP_COMPOSE_FILE", "deploy/dockge/compose.yaml")
    )
    if compose_path.is_file():
        return _sha256(compose_path)
    return UNCONFIGURED_COMPOSE_SHA256


def settings_from_environment() -> BackupWorkerSettings:
    return BackupWorkerSettings(
        control_dir=backup_control_dir(),
        output_root=Path(os.getenv("HOIKUICT_BACKUP_OUTPUT_ROOT", "/backup")),
        database_url=os.getenv("HOIKUICT_DATABASE_URL", "sqlite:///./hoikuict.db"),
        facility_db=Path(
            os.getenv("HOIKU_FACILITY_BUNREI_DB_PATH", "data/facility.sqlite")
        ),
        storage_root=Path(os.getenv("HOIKUICT_STORAGE_ROOT", "storage")),
        git_sha=os.getenv("HOIKUICT_BACKUP_GIT_SHA", UNCONFIGURED_GIT_SHA),
        app_image=os.getenv("HOIKUICT_BACKUP_APP_IMAGE", "open-hoikuict:unconfigured"),
        compose_sha256=_compose_sha_from_environment(),
        cloudflared_image=os.getenv("HOIKUICT_BACKUP_CLOUDFLARED_IMAGE", "unknown"),
        environment=os.getenv("HOIKUICT_ENV", "production"),
        facility_ref=os.getenv("HOIKU_NURSERY_REF", ""),
    )


def process_next_backup(settings: BackupWorkerSettings) -> bool:
    job = claim_next_backup(settings.control_dir)
    if job is None:
        return False
    logger.info("backup job started: %s", job["job_id"])
    try:
        backup_path = create_backup(
            BackupConfig(
                output_root=settings.output_root,
                database_url=settings.database_url,
                facility_db=settings.facility_db,
                storage_root=settings.storage_root,
                git_sha=settings.git_sha,
                app_image=settings.app_image,
                compose_sha256=settings.compose_sha256,
                cloudflared_image=settings.cloudflared_image,
                environment=settings.environment,
                facility_ref=settings.facility_ref,
                lock_source_writes=True,
            )
        )
        verification = verify_backup_set(backup_path)
        provenance_warnings: list[str] = []
        if settings.git_sha == UNCONFIGURED_GIT_SHA:
            provenance_warnings.append("Git SHAが未設定です")
        if settings.compose_sha256 == UNCONFIGURED_COMPOSE_SHA256:
            provenance_warnings.append("Compose SHA-256が未設定です")
        result = {
            "backup_id": backup_path.name,
            "files_verified": verification["files_verified"],
            "verification_status": verification["status"],
            "warnings": list(verification["verification"].get("warnings", []))
            + provenance_warnings,
        }
        finish_backup_job(
            job,
            status="succeeded",
            result=result,
            control_dir=settings.control_dir,
        )
        logger.info("backup job succeeded: %s -> %s", job["job_id"], backup_path.name)
    except Exception as exc:
        finish_backup_job(
            job,
            status="failed",
            error=str(exc),
            control_dir=settings.control_dir,
        )
        logger.exception("backup job failed: %s", job["job_id"])
    return True


def enqueue_due_scheduled_backup(
    settings: BackupWorkerSettings,
    *,
    now: datetime | None = None,
) -> bool:
    try:
        schedule = load_backup_schedule(settings.control_dir)
        slot = due_schedule_slot(schedule, now=now)
    except BackupScheduleError:
        logger.exception("backup schedule is invalid")
        return False
    if slot is None:
        return False
    if any(
        job.get("trigger") == "scheduled" and job.get("scheduled_slot") == slot
        for job in list_backup_jobs(control_dir=settings.control_dir, limit=100)
    ):
        return False
    try:
        enqueue_backup(
            requested_by_id=None,
            requested_by_name="定期実行",
            trigger="scheduled",
            scheduled_slot=slot,
            control_dir=settings.control_dir,
        )
    except BackupJobConflict:
        return False
    logger.info("scheduled backup enqueued: %s", slot)
    return True


def _heartbeat_loop(control_dir: Path, stop_event: Event, interval_seconds: float) -> None:
    while not stop_event.is_set():
        try:
            write_worker_heartbeat(control_dir)
        except Exception:
            logger.exception("backup worker heartbeat failed")
        stop_event.wait(interval_seconds)


def run_worker(
    settings: BackupWorkerSettings,
    *,
    once: bool = False,
    poll_seconds: float = 5.0,
) -> int:
    recover_interrupted_jobs(settings.control_dir)
    stop_event = Event()
    heartbeat_thread = Thread(
        target=_heartbeat_loop,
        args=(settings.control_dir, stop_event, min(10.0, max(1.0, poll_seconds))),
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        if once:
            enqueue_due_scheduled_backup(settings)
            process_next_backup(settings)
            return 0
        while True:
            enqueue_due_scheduled_backup(settings)
            processed = process_next_backup(settings)
            if not processed:
                time.sleep(max(0.25, poll_seconds))
    except KeyboardInterrupt:
        logger.info("backup worker stopped")
        return 0
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=2)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="backup-worker",
        description="管理画面からのbackup依頼を実行します",
    )
    parser.add_argument("--once", action="store_true", help="待機中の1件を処理して終了します")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("HOIKUICT_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _build_parser().parse_args(argv)
    return run_worker(
        settings_from_environment(),
        once=args.once,
        poll_seconds=args.poll_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
