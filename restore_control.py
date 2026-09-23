"""Private, bounded file protocol shared by the app, supervisor and restore worker.

The protocol contains no command, host path or password supplied by a browser.
It lives outside the data being restored. Requests are authenticated and single use.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
from uuid import UUID, uuid4

JST = timezone(timedelta(hours=9))
TERMINAL = {"succeeded", "failed", "rolled_back", "blocked"}
STEPS = ("利用を一時停止", "直前のデータを退避", "復元データを準備",
         "写真・添付・データを検査", "データを切り替えて起動確認", "利用再開・再ログイン")


class RestoreError(RuntimeError):
    """Message is suitable for the administrator; never embed private raw errors."""


def enabled() -> bool:
    return os.getenv("HOIKUICT_RESTORE_ENABLED") == "1"


def control_dir() -> Path:
    path = Path(os.getenv("HOIKUICT_RESTORE_CONTROL_DIR", "data/restore-control")).absolute()
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise RestoreError("復元サービスの保存先にリンクは使えません。")
    return path.resolve()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def as_jst(value: str) -> str:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(JST).strftime("%Y年%m月%d日 %H:%M")


def identifier(value: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RestoreError("作業番号が不正です。") from exc


def backup_identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"open-hoikuict_[0-9]{8}T[0-9]{6}Z_[0-9a-f]{12}", value):
        raise RestoreError("バックアップの指定が不正です。")
    return value


def ensure_root(root: Path | None = None) -> Path:
    root = root or control_dir()
    if root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise RestoreError("復元サービスの保存先を確認してください。")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in ("tickets", "requests", "jobs", "audit", "viewers"):
        path = root / name
        if path.is_symlink():
            raise RestoreError("復元サービスの保存先を確認してください。")
        path.mkdir(mode=0o700, exist_ok=True)
    return root


def read_json(path: Path, *, limit: int = 2_000_000) -> dict:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
            raise ValueError("invalid file")
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate key")
                result[key] = value
            return result
        result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)
        if not isinstance(result, dict):
            raise ValueError("invalid object")
        return result
    except (OSError, ValueError, UnicodeError) as exc:
        raise RestoreError("復元処理の記録を読み取れません。運用担当者に確認してください。") from exc


def atomic_json(path: Path, value: dict) -> None:
    from atomic_file import replace_file
    if path.is_symlink() or path.parent.is_symlink():
        raise RestoreError("復元処理の保存先が不正です。")
    temporary = path.parent / ("." + path.name + "." + uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8") as output:
            os.chmod(temporary, 0o600)
            json.dump(value, output, ensure_ascii=False, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        replace_file(temporary, path)
        if os.name != "nt":
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def exclusive_lock(name: str = "queue", root: Path | None = None):
    root = ensure_root(root)
    path = root / (name + ".lock")
    if path.is_symlink():
        raise RestoreError("復元処理のロックが不正です。")
    with path.open("a+b") as stream:
        os.chmod(path, 0o600)
        if path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RestoreError("別の処理が進行中です。少し待って確認してください。") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def signing_key() -> bytes:
    path = Path(os.getenv("HOIKUICT_RESTORE_SIGNING_KEY_FILE", "/run/secrets/restore-signing-key"))
    if path.is_symlink() or not path.is_file() or path.stat().st_size != 32:
        raise RestoreError("復元サービスの認証設定を確認してください。")
    return path.read_bytes()


def signed(value: dict) -> dict:
    payload = {k: v for k, v in value.items() if k != "signature"}
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    return {**payload, "signature": hmac.new(signing_key(), serialized, hashlib.sha256).hexdigest()}


def verified(value: dict) -> dict:
    if not hmac.compare_digest(str(value.get("signature", "")), signed(value)["signature"]):
        raise RestoreError("復元依頼の認証に失敗しました。最初から確認してください。")
    return value


def heartbeat(name: str, **fields) -> None:
    root = ensure_root()
    atomic_json(root / (name + ".json"), {"seen": time.time(), **fields})


def service_state(name: str) -> dict:
    path = control_dir() / (name + ".json")
    if not path.exists():
        return {"online": False}
    result = read_json(path)
    return {**result, "online": -5 <= time.time() - float(result.get("seen", 0)) <= 20}


def maintenance() -> dict | None:
    path = control_dir() / "maintenance.json"
    return read_json(path) if path.exists() else None


def set_maintenance(job_id: str, mode: str) -> None:
    if mode not in {"stop", "probe", "resume"}:
        raise RestoreError("復元処理の状態が不正です。")
    atomic_json(ensure_root() / "maintenance.json", {"job_id": identifier(job_id), "mode": mode})


def clear_maintenance(job_id: str) -> None:
    value = maintenance()
    if value and value.get("job_id") != identifier(job_id):
        raise RestoreError("別の復元処理が利用を停止しています。")
    (control_dir() / "maintenance.json").unlink(missing_ok=True)
    if os.name != "nt":
        descriptor = os.open(control_dir(), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def job_path(job_id: str) -> Path:
    return control_dir() / "jobs" / (identifier(job_id) + ".json")


def read_job(job_id: str) -> dict:
    return read_json(job_path(job_id))


def update_job(job_id: str, **values) -> dict:
    path = job_path(job_id)
    value = {**read_json(path), **values, "updated_at": now_iso()}
    atomic_json(path, value)
    return value


def active_job() -> dict | None:
    path = control_dir() / "active.json"
    if not path.exists():
        return None
    job = read_job(read_json(path)["job_id"])
    return job if job["state"] not in TERMINAL or job["state"] == "blocked" else None


def recent_jobs() -> list[dict]:
    directory = control_dir() / "jobs"
    if not directory.exists():
        return []
    jobs = [read_json(p) for p in directory.glob("*.json")]
    return sorted(jobs, key=lambda item: item["created_at"], reverse=True)[:30]


def issue_ticket(payload: dict) -> dict:
    root = ensure_root()
    value = signed({**payload, "ticket_id": str(uuid4()), "expires": time.time() + 900, "confirmed": False})
    atomic_json(root / "tickets" / (value["ticket_id"] + ".json"), value)
    return value


def load_ticket(ticket_id: str, actor_id: str) -> dict:
    value = verified(read_json(ensure_root() / "tickets" / (identifier(ticket_id) + ".json")))
    if value.get("actor_id") != actor_id or value.get("expires", 0) < time.time() or value.get("consumed"):
        raise RestoreError("確認の有効期限が切れています。復元元の選択からやり直してください。")
    return value


def confirm_ticket(ticket_id: str, actor_id: str) -> dict:
    with exclusive_lock():
        value = signed({**load_ticket(ticket_id, actor_id), "confirmed": True})
        atomic_json(control_dir() / "tickets" / (identifier(ticket_id) + ".json"), value)
        return value


def queue_restore(ticket_id: str, actor_id: str) -> tuple[dict, str]:
    with exclusive_lock():
        if active_job() or maintenance() or any((ensure_root() / "requests").glob("*.json")):
            raise RestoreError("復元処理が進行中です。進行状況を確認してください。")
        from backup_jobs import list_backup_jobs
        if any(job.get("status") in {"queued", "running"} for job in list_backup_jobs()):
            raise RestoreError("バックアップの作成が進行中です。完了後に実行してください。")
        value = load_ticket(ticket_id, actor_id)
        if not value.get("confirmed"):
            raise RestoreError("戻す日時と影響を確認してください。")
        if not all(service_state(name)["online"] for name in ("worker", "gateway", "backup")):
            raise RestoreError("復元サービスが停止中です。運用担当者に確認してください。")
        job_id, token = str(uuid4()), secrets.token_urlsafe(32)
        request = signed({"job_id": job_id, "backup_id": backup_identifier(value["backup_id"]),
                          "manifest_hash": value["manifest_hash"], "actor_id": actor_id,
                          "actor_name": value["actor_name"], "credential_fingerprint": value["credential_fingerprint"],
                          "target_credential_fingerprint": value["target_credential_fingerprint"],
                          "reason": value["reason"], "created_at": now_iso(), "expires": time.time() + 900})
        job = {"job_id": job_id, "backup_id": request["backup_id"], "backup_date": value["backup_date"],
               "actor_id": actor_id, "actor_name": value["actor_name"], "reason": value["reason"],
               "state": "queued", "phase": "queued", "step": 0, "created_at": request["created_at"],
               "updated_at": request["created_at"], "viewer_hash": hashlib.sha256(token.encode()).hexdigest(),
               "viewer_expires": time.time() + 86400, "message": "復元の実行を受け付けました。"}
        root = control_dir()
        atomic_json(job_path(job_id), job)
        atomic_json(root / "requests" / (job_id + ".json"), request)
        atomic_json(root / "active.json", {"job_id": job_id})
        atomic_json(root / "tickets" / (value["ticket_id"] + ".json"), signed({**value, "consumed": True}))
        return job, token


def viewer_allowed(job: dict, token: str | None) -> bool:
    renewed = control_dir() / "viewers" / (identifier(job["job_id"]) + ".json")
    if renewed.exists():
        job = read_json(renewed)
    return bool(token and len(token) <= 128 and job.get("viewer_expires", 0) >= time.time()
                and hmac.compare_digest(job.get("viewer_hash", ""), hashlib.sha256(token.encode()).hexdigest()))


def viewer_cookie(job_id: str) -> str:
    return "restore_view_" + UUID(identifier(job_id)).hex


def grant_viewer(job_id: str) -> str:
    token = secrets.token_urlsafe(32)
    with exclusive_lock():
        read_job(job_id)
        atomic_json(ensure_root() / "viewers" / (identifier(job_id) + ".json"),
                    {"viewer_hash": hashlib.sha256(token.encode()).hexdigest(), "viewer_expires": time.time() + 86400})
    return token
