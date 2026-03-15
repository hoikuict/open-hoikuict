from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

from sqlalchemy.engine import Engine
from sqlmodel import create_engine

DEMO_SESSION_COOKIE_NAME = "demo_session_id"
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SESSION_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


@dataclass(frozen=True)
class DemoSettings:
    enabled: bool
    runtime_dir: Path
    base_db_path: Path
    sessions_dir: Path
    session_ttl_seconds: int
    session_input_limit_bytes: int
    max_request_body_bytes: int
    secure_cookies: bool
    cleanup_interval_seconds: int


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def load_demo_settings() -> DemoSettings:
    runtime_dir = Path(os.getenv("DEMO_RUNTIME_DIR", "./runtime")).resolve()
    session_ttl_minutes = max(int(os.getenv("DEMO_SESSION_TTL_MINUTES", "120")), 1)
    return DemoSettings(
        enabled=_env_flag("PUBLIC_DEMO_MODE", default=False),
        runtime_dir=runtime_dir,
        base_db_path=runtime_dir / "demo-template.sqlite3",
        sessions_dir=runtime_dir / "sessions",
        session_ttl_seconds=session_ttl_minutes * 60,
        session_input_limit_bytes=max(int(os.getenv("DEMO_SESSION_INPUT_LIMIT_BYTES", "65536")), 1024),
        max_request_body_bytes=max(int(os.getenv("DEMO_MAX_REQUEST_BODY_BYTES", "16384")), 1024),
        secure_cookies=_env_flag("DEMO_SECURE_COOKIES", default=False),
        cleanup_interval_seconds=max(int(os.getenv("DEMO_CLEANUP_INTERVAL_SECONDS", "300")), 30),
    )


def is_public_demo_enabled() -> bool:
    return load_demo_settings().enabled


@lru_cache(maxsize=1)
def get_demo_session_manager() -> "DemoSessionManager":
    return DemoSessionManager(load_demo_settings())


def reset_demo_runtime_cache() -> None:
    try:
        get_demo_session_manager.cache_clear()
    except AttributeError:
        pass


class DemoSessionManager:
    def __init__(self, settings: DemoSettings):
        self.settings = settings
        self._lock = threading.Lock()
        self._engines: dict[str, Engine] = {}
        self._last_cleanup_at = 0.0

    def prepare_base_database(self, builder: Callable[[Path], None]) -> None:
        self.settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.settings.base_db_path.with_name(f"{self.settings.base_db_path.stem}.build.sqlite3")
        if tmp_path.exists():
            tmp_path.unlink()
        if self.settings.base_db_path.exists():
            self.settings.base_db_path.unlink()
        builder(tmp_path)
        tmp_path.replace(self.settings.base_db_path)
        self._reset_session_storage()

    def ensure_session_id(self, raw_session_id: str | None) -> tuple[str, bool]:
        if raw_session_id and SESSION_ID_PATTERN.fullmatch(raw_session_id):
            return raw_session_id, False
        return secrets.token_hex(16), True

    def ensure_session_database(self, session_id: str) -> Path:
        with self._lock:
            session_dir = self._session_dir(session_id)
            db_path = self._db_path(session_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            if not db_path.exists():
                shutil.copy2(self.settings.base_db_path, db_path)
                self._write_usage(session_id, 0)
            self._touch_locked(session_id)
            return db_path

    def get_engine(self, session_id: str) -> Engine:
        db_path = self.ensure_session_database(session_id)
        with self._lock:
            cached = self._engines.get(session_id)
            if cached is not None:
                return cached
            engine = create_engine(
                f"sqlite:///{db_path.resolve().as_posix()}",
                echo=False,
                connect_args={"check_same_thread": False},
            )
            self._engines[session_id] = engine
            return engine

    def touch_session(self, session_id: str) -> None:
        with self._lock:
            self._touch_locked(session_id)

    def cleanup_expired_sessions(self, force: bool = False) -> None:
        if not self.settings.sessions_dir.exists():
            return

        now = time.time()
        with self._lock:
            if not force and now - self._last_cleanup_at < self.settings.cleanup_interval_seconds:
                return
            self._last_cleanup_at = now

            for session_dir in self.settings.sessions_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                touch_path = session_dir / ".last_seen"
                if not touch_path.exists():
                    touch_path = session_dir / "quota.json"
                if not touch_path.exists():
                    continue
                try:
                    age_seconds = now - touch_path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age_seconds <= self.settings.session_ttl_seconds:
                    continue

                session_id = session_dir.name
                engine = self._engines.pop(session_id, None)
                if engine is not None:
                    engine.dispose()
                shutil.rmtree(session_dir, ignore_errors=True)

    def reserve_input_budget(self, session_id: str, payload_bytes: int) -> tuple[bool, int]:
        if payload_bytes <= 0:
            return True, self.get_input_usage(session_id)

        self.ensure_session_database(session_id)
        with self._lock:
            used = self._read_usage(session_id)
            proposed = used + payload_bytes
            if proposed > self.settings.session_input_limit_bytes:
                self._touch_locked(session_id)
                return False, used

            self._write_usage(session_id, proposed)
            self._touch_locked(session_id)
            return True, proposed

    def get_input_usage(self, session_id: str) -> int:
        self.ensure_session_database(session_id)
        with self._lock:
            return self._read_usage(session_id)

    def close(self) -> None:
        self._reset_session_storage()
        if self.settings.base_db_path.exists():
            try:
                self.settings.base_db_path.unlink()
            except OSError:
                pass

    def _reset_session_storage(self) -> None:
        with self._lock:
            for engine in self._engines.values():
                engine.dispose()
            self._engines.clear()
            if self.settings.sessions_dir.exists():
                shutil.rmtree(self.settings.sessions_dir, ignore_errors=True)
            self.settings.sessions_dir.mkdir(parents=True, exist_ok=True)
            self._last_cleanup_at = 0.0

    def _session_dir(self, session_id: str) -> Path:
        return self.settings.sessions_dir / session_id

    def _db_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "app.sqlite3"

    def _touch_locked(self, session_id: str) -> None:
        session_dir = self._session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        touch_path = session_dir / ".last_seen"
        touch_path.touch(exist_ok=True)

    def _usage_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "quota.json"

    def _read_usage(self, session_id: str) -> int:
        usage_path = self._usage_path(session_id)
        if not usage_path.exists():
            return 0
        try:
            data = json.loads(usage_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return 0
        return max(int(data.get("input_bytes_used", 0)), 0)

    def _write_usage(self, session_id: str, used: int) -> None:
        usage_path = self._usage_path(session_id)
        tmp_path = usage_path.with_suffix(".tmp")
        payload = {"input_bytes_used": max(int(used), 0)}
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(usage_path)
