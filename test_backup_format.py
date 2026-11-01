from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from backup_jobs import enqueue_backup, list_backup_jobs
from scripts.backup_format import configured_format, create_operational_backup
from scripts.backup_runtime import BackupConfig, BackupError, verify_backup_set
from scripts.backup_worker import BackupWorkerSettings, process_next_backup
from test_backup_support import full_databases


@pytest.fixture
def runtime(tmp_path):
    main, facility = tmp_path / "source/data/hoikuict.db", tmp_path / "source/data/facility.sqlite"
    storage = tmp_path / "source/storage"
    storage.mkdir(parents=True)
    full_databases(main, facility)
    config = BackupConfig(output_root=tmp_path / "sets", database_url=f"sqlite:///{main}",
        facility_db=facility, storage_root=storage, git_sha="a" * 40,
        app_image="sha256:" + "b" * 64, compose_sha256="c" * 64,
        cloudflared_image="sha256:" + "d" * 64, environment="test", facility_ref="synthetic",
        quiesced=True, recovery_kit_ref="test-kit", actor_ref="test-operator", baseline_ref="test-baseline")
    return SimpleNamespace(config=config, control=main.parent / "backup-control")


def test_existing_worker_continues_format_one_without_recovery_kit(runtime, monkeypatch):
    monkeypatch.delenv("HOIKUICT_BACKUP_FORMAT_VERSION", raising=False)
    assert configured_format() == 1
    enqueue_backup(requested_by_id=None, requested_by_name="試験", control_dir=runtime.control)
    config = runtime.config
    settings = BackupWorkerSettings(control_dir=runtime.control, output_root=config.output_root,
        database_url=config.database_url, facility_db=config.facility_db, storage_root=config.storage_root,
        git_sha=config.git_sha, app_image=config.app_image, compose_sha256=config.compose_sha256)
    assert process_next_backup(settings)
    job = list_backup_jobs(control_dir=runtime.control)[0]
    assert job["status"] == "succeeded"
    assert job["result"]["format_version"] == 1
    assert job["result"]["stages"]["verified"] == "unconfirmed"
    backup = config.output_root / job["result"]["backup_id"]
    assert verify_backup_set(backup)["status"] == "ok"


def test_requested_format_two_never_falls_back_when_kit_is_missing(runtime):
    config = replace(runtime.config, recovery_kit_ref="")
    with pytest.raises(BackupError, match="recovery kit"):
        create_operational_backup(config, format_version=2)
    assert not list(config.output_root.glob("*/COMPLETE"))


def test_format_two_with_prerequisites_keeps_schedule_and_verification(runtime):
    path = create_operational_backup(runtime.config, format_version=2)
    assert json.loads((path / "manifest.json").read_text())["format_version"] == 2
    assert (path / "settings/backup-schedule.json").exists()
    assert verify_backup_set(path)["stages"]["verified"] == "passed"


def test_unknown_operational_format_fails_closed(monkeypatch):
    monkeypatch.setenv("HOIKUICT_BACKUP_FORMAT_VERSION", "unexpected")
    with pytest.raises(BackupError):
        configured_format()


def test_restore_rollback_backup_keeps_legacy_format_without_kit(runtime, monkeypatch):
    from restore_data import RestorePaths, fresh_backup
    config = runtime.config
    monkeypatch.setenv("HOIKUICT_BACKUP_FORMAT_VERSION", "1")
    for key, value in {"HOIKUICT_BACKUP_GIT_SHA": config.git_sha,
        "HOIKUICT_BACKUP_APP_IMAGE": config.app_image,
        "HOIKUICT_BACKUP_COMPOSE_SHA256": config.compose_sha256}.items():
        monkeypatch.setenv(key, value)
    for key in ("HOIKUICT_BACKUP_RECOVERY_KIT_REF", "HOIKUICT_BACKUP_BASELINE_REF"):
        monkeypatch.delenv(key, raising=False)
    paths = RestorePaths(config.facility_db.parent, config.storage_root,
                         config.output_root, config.output_root.parent / "staging")
    backup_id = fresh_backup(paths, actor_ref="test-restore")
    result = verify_backup_set(paths.backups / backup_id)
    assert result["format_version"] == 1 and result["status"] == "ok"
