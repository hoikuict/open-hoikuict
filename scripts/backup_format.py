"""Explicit operational format selection during the recovery-kit rollout.

CLI format-2 creation remains strict. Existing workers keep format 1 until an
operator configures format 2 and its recovery prerequisites; failures never
silently downgrade a requested format-2 backup.
"""
from dataclasses import fields
import os

from scripts.backup_runtime import BackupConfig, BackupError, create_backup


def configured_format() -> int:
    value = os.getenv("HOIKUICT_BACKUP_FORMAT_VERSION", "1")
    if value not in {"1", "2"}:
        raise BackupError("バックアップ形式は1または2を指定してください")
    return int(value)


def create_operational_backup(config: BackupConfig, *, format_version: int):
    if format_version == 2:
        return create_backup(config)
    if format_version != 1:
        raise BackupError("対応していないバックアップ形式です")
    from scripts.backup_runtime_v1 import BackupConfig as LegacyConfig
    from scripts.backup_runtime_v1 import create_backup as create_legacy
    return create_legacy(LegacyConfig(**{
        field.name: getattr(config, field.name) for field in fields(LegacyConfig)
    }))
