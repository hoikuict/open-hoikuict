from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from backup_jobs import backup_control_dir


BACKUP_SCHEDULE_SCHEMA_VERSION = 1
MAX_SCHEDULE_FILE_BYTES = 64 * 1024
JST = timezone(timedelta(hours=9), name="JST")
WEEKDAY_LABELS = (
    "月曜日",
    "火曜日",
    "水曜日",
    "木曜日",
    "金曜日",
    "土曜日",
    "日曜日",
)


class BackupScheduleError(RuntimeError):
    pass


def default_backup_schedule() -> dict[str, Any]:
    return {
        "schema_version": BACKUP_SCHEDULE_SCHEMA_VERSION,
        "enabled": False,
        "frequency": "daily",
        "run_time": "02:00",
        "weekday": 0,
        "updated_at_utc": None,
        "updated_at_jst": None,
        "updated_by": None,
    }


def _root(control_dir: Path | None) -> Path:
    root = (control_dir or backup_control_dir()).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(stat.S_IRWXU)
    return root


def _schedule_path(control_dir: Path | None) -> Path:
    return _root(control_dir) / "schedule.json"


def _parse_run_time(value: str) -> time:
    try:
        parsed = datetime.strptime(value.strip(), "%H:%M").time()
    except ValueError as exc:
        raise BackupScheduleError("実行時刻はHH:MM形式で指定してください") from exc
    return parsed.replace(second=0, microsecond=0)


def _validate_schedule(schedule: dict[str, Any]) -> dict[str, Any]:
    if schedule.get("schema_version") != BACKUP_SCHEDULE_SCHEMA_VERSION:
        raise BackupScheduleError("未対応の定期実行設定versionです")
    if not isinstance(schedule.get("enabled"), bool):
        raise BackupScheduleError("有効・無効の指定が不正です")
    frequency = str(schedule.get("frequency", ""))
    if frequency not in {"daily", "weekly"}:
        raise BackupScheduleError("実行頻度は毎日または毎週で指定してください")
    run_time = str(schedule.get("run_time", ""))
    parsed_run_time = _parse_run_time(run_time)
    try:
        weekday = int(schedule.get("weekday", 0))
    except (TypeError, ValueError) as exc:
        raise BackupScheduleError("曜日の指定が不正です") from exc
    if weekday not in range(7):
        raise BackupScheduleError("曜日の指定が不正です")
    validated = dict(schedule)
    validated["enabled"] = schedule["enabled"]
    validated["frequency"] = frequency
    validated["run_time"] = parsed_run_time.strftime("%H:%M")
    validated["weekday"] = weekday
    return validated


def load_backup_schedule(control_dir: Path | None = None) -> dict[str, Any]:
    path = _schedule_path(control_dir)
    if not path.exists():
        return default_backup_schedule()
    if not path.is_file() or path.is_symlink():
        raise BackupScheduleError("定期実行設定fileが通常fileではありません")
    if path.stat().st_size > MAX_SCHEDULE_FILE_BYTES:
        raise BackupScheduleError("定期実行設定fileが大きすぎます")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupScheduleError("定期実行設定を読み取れません") from exc
    if not isinstance(payload, dict):
        raise BackupScheduleError("定期実行設定の形式が不正です")
    return _validate_schedule(payload)


def save_backup_schedule(
    *,
    enabled: bool,
    frequency: str,
    run_time: str,
    weekday: int,
    updated_by_id: str | None,
    updated_by_name: str,
    control_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    schedule = _validate_schedule(
        {
            "schema_version": BACKUP_SCHEDULE_SCHEMA_VERSION,
            "enabled": enabled,
            "frequency": frequency,
            "run_time": run_time.strip(),
            "weekday": weekday,
            "updated_at_utc": current.isoformat().replace("+00:00", "Z"),
            "updated_at_jst": current.astimezone(JST).isoformat(timespec="seconds"),
            "updated_by": {
                "id": updated_by_id,
                "name": updated_by_name.strip()[:100] or "管理者",
            },
        }
    )
    path = _schedule_path(control_dir)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        temporary.write_text(
            json.dumps(schedule, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return schedule


def next_scheduled_run(
    schedule: dict[str, Any],
    *,
    now: datetime | None = None,
) -> datetime | None:
    validated = _validate_schedule(schedule)
    if not validated["enabled"]:
        return None
    current = (now or datetime.now(JST)).astimezone(JST)
    run_at = _parse_run_time(validated["run_time"])
    if validated["frequency"] == "daily":
        candidate = datetime.combine(current.date(), run_at, tzinfo=JST)
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate
    days_ahead = (validated["weekday"] - current.weekday()) % 7
    candidate = datetime.combine(
        current.date() + timedelta(days=days_ahead),
        run_at,
        tzinfo=JST,
    )
    if candidate <= current:
        candidate += timedelta(days=7)
    return candidate


def due_schedule_slot(
    schedule: dict[str, Any],
    *,
    now: datetime | None = None,
) -> str | None:
    validated = _validate_schedule(schedule)
    if not validated["enabled"]:
        return None
    current = (now or datetime.now(JST)).astimezone(JST)
    if validated["frequency"] == "weekly" and current.weekday() != validated["weekday"]:
        return None
    scheduled_at = datetime.combine(
        current.date(),
        _parse_run_time(validated["run_time"]),
        tzinfo=JST,
    )
    if current < scheduled_at:
        return None
    return (
        f"{validated['frequency']}:{current.date().isoformat()}:"
        f"{validated['run_time']}"
    )
