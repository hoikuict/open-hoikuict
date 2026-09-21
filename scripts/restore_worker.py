"""Unprivileged restore executor. No Docker socket, shell, network or host commands."""
from __future__ import annotations

import logging
import os
import threading
import time
from uuid import uuid4

from restore_control import (
    RestoreError, active_job, atomic_json, clear_maintenance, control_dir, ensure_root,
    exclusive_lock, heartbeat, identifier, maintenance, read_job, read_json,
    service_state, set_maintenance, update_job, verified,
)
from restore_data import (
    RestorePaths, admin_credential, apply_copy, backup_path, ensure_space, file_hash,
    fresh_backup, inspect_backup, prepare_copy, verify_payload,
)

logger = logging.getLogger("open_hoikuict.restore")


class RestoreExecutor:
    def __init__(self, paths: RestorePaths, *, timeout: float = 120, poll: float = 1):
        self.paths, self.timeout, self.poll = paths, timeout, poll

    def wait(self, predicate, message: str) -> None:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(self.poll)
        raise RestoreError(message)

    def pause(self, job_id: str) -> None:
        set_maintenance(job_id, "stop")
        def paused():
            gateway, backup = service_state("gateway"), service_state("backup")
            return (gateway["online"] and gateway.get("stopped") and gateway.get("job_id") == job_id
                    and backup["online"] and backup.get("paused") and backup.get("job_id") == job_id)
        self.wait(paused, "業務とバックアップの停止を確認できませんでした。")

    def probe(self, job_id: str) -> None:
        set_maintenance(job_id, "probe")
        def healthy():
            gateway = service_state("gateway")
            return (gateway["online"] and gateway.get("mode") == "probe"
                    and gateway.get("job_id") == job_id and gateway.get("healthy"))
        self.wait(healthy, "復元後の起動確認に失敗しました。")

    def resume(self, job_id: str) -> None:
        set_maintenance(job_id, "resume")
        self.wait(lambda: (lambda state: state["online"] and state.get("mode") == "normal" and state.get("healthy")
                          and state.get("job_id") == job_id)(service_state("gateway")),
                  "業務アプリの再開を確認できませんでした。")

    def finish(self, job_id: str, state: str, message: str) -> None:
        # Persist the point of no return BEFORE permitting new business writes.
        update_job(job_id, state="committed", phase="releasing", completion_state=state,
                   completion_message=message, message="起動確認が完了しました。利用を再開しています。")
        clear_maintenance(job_id)
        update_job(job_id, state=state, phase="complete", step=6, message=message)

    def verify_request(self, request: dict, *, allow_expired: bool = False) -> dict:
        verified(request)
        identifier(request["job_id"])
        if not allow_expired and request.get("expires", 0) < time.time():
            raise RestoreError("復元依頼の有効期限が切れました。最初から確認してください。")
        return request

    def execute(self, request: dict) -> None:
        request = self.verify_request(request)
        job_id = request["job_id"]
        job = read_job(job_id)
        if job["state"] != "queued":
            return
        try:
            result = inspect_backup(self.paths, request["backup_id"], request["actor_id"])
            for key in ("manifest_hash", "credential_fingerprint", "target_credential_fingerprint"):
                if result[key] != request[key]:
                    raise RestoreError("確認後に対象データまたは管理者情報が変わりました。確認をやり直してください。")
            ensure_space(self.paths, request["backup_id"])
            update_job(job_id, state="running", phase="quiescing", step=0, message="業務の終了を待ち、利用を一時停止しています。")
            self.pause(job_id)
            # Authentication may have changed while a previous request was draining.
            if admin_credential(self.paths.data / "hoikuict.db", request["actor_id"])["fingerprint"] != request["credential_fingerprint"]:
                raise RestoreError("管理者情報が変わったため復元を中止しました。")
            update_job(job_id, phase="saving", step=1, message="復元直前のデータを退避しています。")
            rollback_id = fresh_backup(self.paths, actor_ref=job_id)
            update_job(job_id, rollback_backup=rollback_id, phase="preparing", step=2, message="別の領域に復元データを準備しています。")
            prepared = prepare_copy(self.paths, request["backup_id"], job_id)
            update_job(job_id, phase="verifying", step=3, message="写真・添付・データを検査しています。")
            verify_payload(prepared / "data/hoikuict.db", prepared / "data/facility.sqlite", prepared / "storage")
            if file_hash(backup_path(self.paths, request["backup_id"]) / "manifest.json") != request["manifest_hash"]:
                raise RestoreError("処理中に復元元が変わったため中止しました。")
            # Persist BEFORE the first replacement. Restart recovery uses rollback_backup.
            update_job(job_id, phase="applying", step=4, message="復元データへ切り替えています。")
            apply_copy(self.paths, prepared)
            self.probe(job_id)
            update_job(job_id, phase="resuming", step=5, message="起動確認が完了しました。利用を再開しています。")
            self.resume(job_id)
            self.finish(job_id, "succeeded", "復元が完了しました。職員・保護者は再ログインしてください。")
        except Exception as exc:
            logger.error("restore job failed: %s (%s)", job_id, type(exc).__name__)
            self.recover(job_id, message=str(exc) if isinstance(exc, RestoreError) else "復元処理でエラーが発生しました。")

    def recover(self, job_id: str, *, message: str = "処理の中断を検出しました。") -> None:
        """Safe on service/container restart; a partial replacement never becomes public."""
        job = read_job(job_id)
        if job["state"] in {"succeeded", "failed", "rolled_back", "blocked"}:
            return
        if job["state"] == "committed":
            try:
                self.resume(job_id)
                self.finish(job_id, job["completion_state"], job["completion_message"])
            except Exception:
                set_maintenance(job_id, "stop")
                update_job(job_id, state="blocked", phase="blocked", message="データ切替後の利用再開を確認できません。利用停止を継続しています。作業番号を運用担当者に伝えてください。")
            return
        changed = job.get("phase") in {"applying", "resuming", "rolling_back", "rollback_probe", "rollback_resuming"}
        try:
            if not changed:
                if maintenance():
                    self.pause(job_id)
                    self.probe(job_id)
                    self.resume(job_id)
                self.finish(job_id, "failed", message + " 現在のデータは変更していません。")
                return
            update_job(job_id, state="running", phase="rolling_back", message="直前の状態へ戻しています。利用停止を継続しています。")
            self.pause(job_id)
            rollback_id = job.get("rollback_backup")
            if not rollback_id:
                raise RestoreError("直前の退避記録を確認できません。")
            prepared = prepare_copy(self.paths, rollback_id, job_id, suffix="rollback-" + uuid4().hex)
            apply_copy(self.paths, prepared)
            update_job(job_id, phase="rollback_probe", message="直前の状態で起動確認をしています。")
            self.probe(job_id)
            update_job(job_id, phase="rollback_resuming", message="直前の状態で利用を再開しています。")
            self.resume(job_id)
            self.finish(job_id, "rolled_back", "復元に失敗したため直前の状態へ戻しました。利用を再開しました。")
        except Exception as exc:
            logger.error("restore recovery blocked: %s (%s)", job_id, type(exc).__name__)
            set_maintenance(job_id, "stop")
            update_job(job_id, state="blocked", phase="blocked", message="自動復旧を完了できませんでした。利用停止を継続しています。作業番号を運用担当者に伝えてください。")


def _heartbeat(stop: threading.Event) -> None:
    while not stop.is_set():
        heartbeat("worker", status="online")
        stop.wait(3)


def run() -> None:
    os.umask(0o077)
    paths = RestorePaths.from_environment()
    ensure_root()
    with exclusive_lock("worker"):
        stop = threading.Event()
        thread = threading.Thread(target=_heartbeat, args=(stop,), daemon=True)
        thread.start()
        executor = RestoreExecutor(paths)
        try:
            # A crash may happen after a queue file is durable but before active.json.
            job = active_job()
            if job and job["state"] not in {"queued", "blocked"}:
                executor.recover(job["job_id"])
            while True:
                try:
                    with exclusive_lock():
                        requests = sorted((control_dir() / "requests").glob("*.json"))
                        request = read_json(requests[0]) if requests else None
                        if request:
                            executor.verify_request(request, allow_expired=True)
                            job_id = identifier(request["job_id"])
                            if requests[0].stem != job_id:
                                raise RestoreError("復元依頼の作業番号が一致しません。")
                            current = active_job()
                            if current and current["job_id"] != job_id:
                                request = None
                            elif read_job(job_id)["state"] != "queued":
                                requests[0].unlink()
                                request = None
                            else:
                                atomic_json(control_dir() / "active.json", {"job_id": job_id})
                except RestoreError:
                    time.sleep(1)
                    continue
                if request:
                    try:
                        executor.execute(request)
                    except RestoreError as exc:
                        update_job(job_id, state="failed", phase="complete", message=str(exc))
                    (control_dir() / "requests" / (job_id + ".json")).unlink(missing_ok=True)
                time.sleep(1)
        finally:
            stop.set()
            thread.join(timeout=5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
