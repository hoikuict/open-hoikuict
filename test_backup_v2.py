from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
import hashlib
import json
import shutil
import sqlite3

from PIL import Image
import pytest
from sqlmodel import SQLModel, Session, create_engine

import models
from backup_evidence import operational_stages
from scripts.backup_operations import RESTORE_CHECKS, monitor, record_restore_test, replicate
from scripts.backup_recovery import prepare_restore
from scripts.backup_runtime import (
    BackupConfig, BackupError, _payload_inventory, _write_json, _write_sha256sums,
    convert_legacy, create_backup, verify_backup_set,
)
from scripts.backup_validation import CURRENT_CONTRACT, load_contract, schema_check
from test_backup_support import full_databases
from time_utils import utc_now


@pytest.fixture
def runtime(tmp_path):
    data = tmp_path / "source/data"
    data.mkdir(parents=True)
    main, facility = data / "hoikuict.db", data / "facility.sqlite"
    storage = tmp_path / "source/storage"
    storage.mkdir(parents=True)
    full_databases(main, facility)
    config = BackupConfig(output_root=tmp_path / "sets", database_url=f"sqlite:///{main}",
                          facility_db=facility, storage_root=storage, git_sha="a"*40,
                          app_image="sha256:"+"b"*64, compose_sha256="c"*64,
                          cloudflared_image="cloudflared@sha256:"+"d"*64, environment="test",
                          facility_ref="synthetic", quiesced=True, recovery_kit_ref="kit-test",
                          actor_ref="operator-test", baseline_ref="baseline-test")
    return SimpleNamespace(root=tmp_path, main=main, facility=facility, storage=storage, config=config,
                           control=data / "backup-control")


def execute(path, statement, values=()):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(statement, values)
        connection.commit()


def rows(path, statement):
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute(statement).fetchall()


def jpeg():
    stream = BytesIO()
    Image.new("RGB", (12, 12), "navy").save(stream, "JPEG")
    return stream.getvalue()


def add_photos(runtime):
    engine = create_engine(f"sqlite:///{runtime.main}")
    with Session(engine) as session:
        session.add(models.ParentAccount(id=1, family_id=1, display_name="架空保護者", email="parent@example.invalid"))
        session.add(models.Family(id=2, family_name="以前の架空家族"))
        session.commit()
        session.add(models.ProfilePhoto(id="child-photo", child_id=1, content=jpeg()))
        session.add(models.ProfilePhoto(id="old-child-photo", child_id=1, content=jpeg()))
        session.add(models.ProfilePhoto(id="guardian-photo", family_id=1, content=jpeg()))
        session.add(models.ProfilePhoto(id="historical-guardian-photo", family_id=2, content=jpeg()))
        session.add(models.ChildProfileHistory(child_id=1, snapshot={"photo_id": "old-child-photo", "g1_photo_id": "historical-guardian-photo"},
                                               changes={"photo_id": {"old": "old-child-photo", "new": "child-photo"}}))
        session.add(models.ChildProfileChangeRequest(child_id=1, parent_account_id=1, change_summary="架空申請",
                    request_data={"child_data": {"photo_id": "child-photo"}, "guardians_data": [{"photo_id": "guardian-photo"}]},
                    change_details={"photo_id": {"old": "写真あり", "new": "写真あり", "old_photo_id": "old-child-photo", "new_photo_id": "child-photo"}}))
        child = session.get(models.Child, 1)
        child.photo_id, child.sex = "child-photo", models.ChildSex.female
        family = session.get(models.Family, 1)
        family.shared_profile = {"guardians": [{"photo_id": "guardian-photo", "order": 1}]}
        session.add(child)
        session.add(family)
        session.commit()
    engine.dispose()


def document(runtime, attachments):
    engine = create_engine(f"sqlite:///{runtime.main}")
    with Session(engine) as session:
        session.add(models.DocumentReviewRequest(id=1, title="架空依頼", requested_by_name="架空職員", attachments=attachments))
        session.commit()
    engine.dispose()


def rewrite_manifest(backup, transform):
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    transform(manifest)
    _write_json(backup / "manifest.json", manifest)
    _write_sha256sums(backup)


def legacy(backup):
    # Match the actual format-1 wire shape; do not require v2-only fields to read it.
    (backup / "settings/backup-schedule.json").unlink()
    (backup / "settings").rmdir()
    def downgrade(value):
        for key in ("schema_contract", "verification_policy_version", "recovery_kit_ref", "actor_ref",
                    "retention_class", "settings_source", "count_comparison", "capacity", "converted_from", "facility_table_counts"):
            value.pop(key)
        value["format_version"] = 1
        value["files"] = _payload_inventory(backup)
    rewrite_manifest(backup, downgrade)


def test_contract_covers_registered_application_schema():
    import child_records.models  # noqa: F401
    import plan_docs.db_models  # noqa: F401
    contract, _ = load_contract()
    assert contract["main"] == {name: sorted(table.columns.keys()) for name, table in SQLModel.metadata.tables.items()}


def test_backup_before_staff_session_settings_keeps_recorded_contract(runtime):
    for table in ("staff_session_timeouts", "staff_session_policy_audits", "staff_session_policies"):
        execute(runtime.main, f'DROP TABLE "{table}"')
    assert schema_check(runtime.main, runtime.facility, CURRENT_CONTRACT)["status"] == "failed"

    previous_contract = "spec-changes-20260919"
    backup = create_backup(replace(runtime.config, schema_contract=previous_contract))
    result = verify_backup_set(backup)
    assert result["verification"]["schema"]["status"] == "ok"
    assert result["verification"]["schema"]["contract_id"] == previous_contract


def test_full_roundtrip_preserves_photos_history_and_disables_schedule(runtime):
    add_photos(runtime)
    engine = create_engine(f"sqlite:///{runtime.main}")
    with Session(engine) as session:
        session.add(models.AttendanceContactConfirmation(
            child_id=1, target_date=utc_now().date(), status=models.AttendanceVerificationStatus.private_absent,
            method="phone", note="架空の電話連絡", recorded_by_name="検証職員",
        ))
        session.commit()
    engine.dispose()
    folder = runtime.storage / "document_reviews"
    folder.mkdir()
    (folder / "review.pdf").write_bytes(b"review")
    document(runtime, [{"name": "架空文書.pdf", "path": "review.pdf", "size": 6}])
    runtime.control.mkdir()
    (runtime.control / "schedule.json").write_text(json.dumps({"schema_version": 1, "enabled": True,
        "frequency": "weekly", "run_time": "03:25", "weekday": 4, "updated_by": {"name": "個人名を保存しない"}}))
    (runtime.control / "requests").mkdir()
    (runtime.control / "requests/old.json").write_text("{}")
    (runtime.control / "worker.json").write_text("{}")
    backup = create_backup(runtime.config)
    result = verify_backup_set(backup)
    assert result["format_version"] == 2
    assert result["stages"] == {"acquired": "passed", "verified": "passed", "replicated": "unconfirmed", "restored": "unconfirmed"}
    saved = json.loads((backup / "settings/backup-schedule.json").read_text())
    assert saved["enabled"] is True and "updated_by" not in saved
    before = {path.relative_to(backup): path.read_bytes() for path in backup.rglob("*") if path.is_file()}
    destination = runtime.root / "restored"
    receipt = prepare_restore(backup, destination, incident_ref="test-restore", isolated=True)
    assert receipt["status"] == "prepared" and receipt["stages"]["restored"] == "unconfirmed"
    restored = destination / "runtime/data/hoikuict.db"
    assert rows(restored, "SELECT * FROM attendance_contact_confirmations") == rows(runtime.main, "SELECT * FROM attendance_contact_confirmations")
    assert rows(restored, "SELECT sex, photo_id FROM children") == [("female", "child-photo")]
    assert rows(restored, "SELECT id, content FROM profile_photos ORDER BY id") == rows(runtime.main, "SELECT id, content FROM profile_photos ORDER BY id")
    assert rows(restored, "SELECT snapshot, changes FROM child_profile_histories") == rows(runtime.main, "SELECT snapshot, changes FROM child_profile_histories")
    control = destination / "runtime/data/backup-control"
    assert [path.name for path in control.iterdir()] == ["schedule.json"]
    assert json.loads((control / "schedule.json").read_text())["enabled"] is False
    assert (destination / "runtime/storage/document_reviews/review.pdf").read_bytes() == b"review"
    assert before == {path.relative_to(backup): path.read_bytes() for path in backup.rglob("*") if path.is_file()}
    with pytest.raises(BackupError, match="新しいdirectory"):
        prepare_restore(backup, destination, incident_ref="retry-test", isolated=True)


@pytest.mark.parametrize("attachment", [
    [{"path": "missing.pdf", "size": 2}], [{"path": "../escape.pdf", "size": 2}],
    [{"path": "C:/escape.pdf", "size": 2}], [{"path": "ok.pdf", "size": True}],
    [{"path": "ok.pdf", "size": 99}], {"path": "ok.pdf", "size": 2},
])
def test_invalid_document_attachment_fails_without_complete(runtime, attachment):
    (runtime.storage / "document_reviews").mkdir()
    (runtime.storage / "document_reviews/ok.pdf").write_bytes(b"ok")
    document(runtime, attachment)
    with pytest.raises(BackupError, match="整合性検査"):
        create_backup(runtime.config)
    assert not list(runtime.config.output_root.rglob("COMPLETE"))


@pytest.mark.parametrize("statement", [
    "UPDATE children SET photo_id='missing'",
    "UPDATE profile_photos SET content=X'00' WHERE id='child-photo'",
    "UPDATE children SET photo_id='guardian-photo'",
    "UPDATE child_profile_histories SET snapshot='{bad json}'",
])
def test_invalid_photo_references_or_image_rejected(runtime, statement):
    add_photos(runtime)
    execute(runtime.main, statement)
    with pytest.raises(BackupError, match="整合性検査"):
        create_backup(runtime.config)


@pytest.mark.parametrize("database, statement", [
    ("main", "DROP TABLE attendance_contact_confirmations"),
    ("main", "DROP TABLE children"), ("main", "ALTER TABLE children DROP COLUMN sex"),
    ("facility", "DROP TABLE bunrei_facility"),
])
def test_missing_schema_rejected(runtime, database, statement):
    execute(getattr(runtime, database), statement)
    with pytest.raises(BackupError, match="schema"):
        create_backup(runtime.config)


def test_well_formed_empty_application_is_valid_but_empty_sqlite_is_not(runtime):
    execute(runtime.main, "DELETE FROM children")
    backup = create_backup(runtime.config)
    assert verify_backup_set(backup)["status"] == "ok"
    empty = runtime.main.parent / "empty.sqlite"
    with closing(sqlite3.connect(empty)):
        pass
    with pytest.raises(BackupError, match="schema"):
        create_backup(replace(runtime.config, facility_db=empty))


@pytest.mark.parametrize("change", [{"enabled": 1}, {"weekday": True}, {"run_time": "2:00"}, {"timezone": "UTC"}])
def test_invalid_schedule_is_not_silently_defaulted(runtime, change):
    runtime.control.mkdir()
    value = {"schema_version": 1, "enabled": False, "frequency": "daily", "run_time": "02:00", "weekday": 0}
    (runtime.control / "schedule.json").write_text(json.dumps({**value, **change}))
    with pytest.raises(BackupError, match="設定"):
        create_backup(runtime.config)


def test_drop_requires_approval_and_cannot_be_bypassed_by_baseline_ref(runtime):
    first = create_backup(runtime.config)
    execute(runtime.main, "DELETE FROM children")
    with pytest.raises(BackupError, match="件数減少"):
        create_backup(replace(runtime.config, baseline_ref="pretend-first-again"))
    second = create_backup(replace(runtime.config, count_change_ref="approved-deletion-test"))
    comparison = json.loads((second / "manifest.json").read_text())["count_comparison"]
    assert comparison["backup_id"] == first.name and comparison["initial"] is False
    assert verify_backup_set(second)["status"] == "ok"


@pytest.mark.parametrize("change", [{"git_sha": "0"*40}, {"app_image": "app:latest"}, {"compose_sha256": "0"*64},
                                  {"recovery_kit_ref": ""}, {"baseline_ref": ""}])
def test_unknown_provenance_and_missing_baseline_fail(runtime, change):
    with pytest.raises(BackupError):
        create_backup(replace(runtime.config, **change))


def test_capacity_check_prevents_creation(runtime, monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage", lambda path: SimpleNamespace(total=100, used=100, free=0))
    with pytest.raises(BackupError, match="空き容量"):
        create_backup(runtime.config)
    assert not list(runtime.config.output_root.rglob("COMPLETE"))


def test_legacy_read_additional_validation_and_conversion(runtime):
    add_photos(runtime)
    backup = create_backup(runtime.config)
    legacy(backup)
    before = hashlib.sha256((backup / "manifest.json").read_bytes()).hexdigest()
    basic = verify_backup_set(backup)
    assert basic["stages"]["verified"] == "unconfirmed"
    assert "application_schema_and_photos_not_verified" in basic["legacy_gaps"]
    extra = verify_backup_set(backup, contract_id=CURRENT_CONTRACT)
    assert extra["verification"]["photos"]["status"] == "ok"
    converted = convert_legacy(backup, output_root=runtime.root / "converted", contract_id=CURRENT_CONTRACT,
                               recovery_kit_ref="legacy-kit", actor_ref="operator-test", baseline_ref="legacy-baseline")
    manifest = json.loads((converted / "manifest.json").read_text())
    assert manifest["converted_from"]["manifest_sha256"] == before
    assert manifest["settings_source"] == "default"
    assert hashlib.sha256((backup / "manifest.json").read_bytes()).hexdigest() == before
    assert verify_backup_set(converted)["format_version"] == 2


@pytest.mark.parametrize("mutation", ["unknown_version", "inventory", "unhashed", "marker", "contract"])
def test_semantic_tampering_is_rejected_even_with_recomputed_checksums(runtime, mutation):
    backup = create_backup(runtime.config)
    if mutation == "unhashed":
        (backup / "extra.txt").write_text("not in manifest")
        _write_sha256sums(backup)
    elif mutation == "marker":
        (backup / "COMPLETE").write_text("other")
    else:
        def edit(value):
            if mutation == "unknown_version":
                value["format_version"] = 99
            elif mutation == "inventory":
                value["files"] = []
            else:
                value["schema_contract"]["sha256"] = "0" * 64
        rewrite_manifest(backup, edit)
    with pytest.raises(BackupError):
        verify_backup_set(backup)
    assert (backup / "COMPLETE").is_file()  # verification never rewrites a published set


def test_replication_receipts_failures_and_monitoring(runtime):
    backup = create_backup(runtime.config)
    evidence = runtime.root / "evidence"
    result = verify_backup_set(backup)
    source_hash = result["manifest_sha256"]
    for target in ("local", "offsite"):
        replicate(backup, runtime.root / target, evidence_root=evidence, destination_ref=target,
                  encryption_ref="test-encryption-audit", independence_ref="test-storage-audit")
    stages = operational_stages(backup.name, source_hash, root=evidence, required_destinations=["local", "offsite"])
    assert stages == {"replicated": "passed", "restored": "unconfirmed"}
    report = {"test_ref": "restore-test", "actor_ref": "operator-test", "rpo_seconds": 60,
              "rto_seconds": 300, "checks": {key: True for key in RESTORE_CHECKS}}
    record_restore_test(backup, evidence, report)
    assert monitor(runtime.config.output_root, evidence, facility_ref="synthetic", required_destinations=["local", "offsite"])["status"] == "ok"
    (runtime.root / "offsite" / backup.name / "db/hoikuict.db").write_bytes(b"corrupt")
    with pytest.raises(BackupError, match="複製に失敗"):
        replicate(backup, runtime.root / "offsite", evidence_root=evidence, destination_ref="offsite",
                  encryption_ref="test-encryption-audit", independence_ref="test-storage-audit")
    assert verify_backup_set(backup)["manifest_sha256"] == source_hash
    stages = operational_stages(backup.name, source_hash, root=evidence, required_destinations=["local", "offsite"])
    assert stages["replicated"] == "failed" and stages["restored"] == "passed"
    expired = monitor(runtime.config.output_root, evidence, facility_ref="synthetic", required_destinations=["local", "offsite"], now=utc_now() + timedelta(days=36))
    assert {"daily_backup_overdue", "restore_test_overdue", "replication_missing_or_failed"} <= set(expired["problems"])


def test_restore_requires_isolation_and_does_not_overwrite(runtime):
    backup = create_backup(runtime.config)
    with pytest.raises(BackupError, match="isolated"):
        prepare_restore(backup, runtime.root / "restore", incident_ref="test")
    with pytest.raises(BackupError):
        prepare_restore(backup, backup / "restore", incident_ref="test", isolated=True)


def test_final_verification_failure_never_publishes_complete(runtime, monkeypatch):
    import scripts.backup_runtime as module
    def fail(*args, **kwargs):
        raise BackupError("synthetic final verification failure")
    monkeypatch.setattr(module, "verify_backup_set", fail)
    with pytest.raises(BackupError):
        create_backup(runtime.config)
    assert not list(runtime.config.output_root.rglob("COMPLETE"))
    assert len(list(runtime.config.output_root.glob(".*.partial/FAILED.json"))) == 1


def test_before_photo_format1_remains_readable_and_convertible(runtime):
    execute(runtime.main, "DROP TABLE profile_photos")
    execute(runtime.main, "ALTER TABLE children DROP COLUMN photo_id")
    execute(runtime.main, "ALTER TABLE children DROP COLUMN sex")
    execute(runtime.main, "ALTER TABLE guardians DROP COLUMN photo_id")
    old_contract = "before-profile-photos-20260914"
    backup = create_backup(replace(runtime.config, schema_contract=old_contract))
    legacy(backup)
    assert verify_backup_set(backup, contract_id=old_contract)["verification"]["photos"]["status"] == "skipped"
    converted = convert_legacy(backup, output_root=runtime.root / "converted-old", contract_id=old_contract,
                               recovery_kit_ref="old-kit", actor_ref="operator-test", baseline_ref="old-baseline")
    assert verify_backup_set(converted)["status"] == "ok"
    with pytest.raises(BackupError, match="schema"):
        verify_backup_set(backup, contract_id=CURRENT_CONTRACT)


def test_failure_monitor_catches_missing_jobs(runtime):
    result = monitor(runtime.config.output_root, runtime.root / "evidence", facility_ref="synthetic",
                     required_destinations=["local", "offsite"], control_dir=runtime.control)
    assert result["status"] == "failed"
    assert {"verified_backup_missing", "worker_offline", "restore_test_overdue"} <= set(result["problems"])


def test_recovery_revokes_old_grants_cancels_mail_and_push_and_allows_fresh_login(runtime, monkeypatch):
    from local_auth import (AuthenticationFailed, authenticate_staff, get_staff_activation_details,
                            hash_password, resolve_staff_session)
    from parent_auth import resolve_parent_session
    monkeypatch.setenv("HOIKUICT_ENV", "development")
    monkeypatch.setenv("HOIKUICT_LOGIN_THROTTLE_HMAC_KEY", "synthetic-test-key-" + "z" * 40)
    engine = create_engine(f"sqlite:///{runtime.main}")
    password = "Synthetic-recovery-password-42"
    expiry = utc_now() + timedelta(days=1)
    digest = lambda token: hashlib.sha256(token.encode()).hexdigest()
    with Session(engine) as session:
        user = models.User(email="staff@example.invalid", display_name="架空職員")
        parent = models.ParentAccount(id=1, family_id=1, display_name="架空保護者", email="parent@example.invalid")
        session.add(user)
        session.add(parent)
        session.commit()
        credential = models.PasswordCredential(principal_type="staff", staff_user_id=user.id,
                        login_id="recovery-staff", login_id_normalized="recovery-staff", password_hash=hash_password(password))
        parent_credential = models.PasswordCredential(principal_type="parent", parent_account_id=1,
                        login_id="parent@example.invalid", login_id_normalized="parent@example.invalid", password_hash=hash_password(password))
        session.add(credential)
        session.add(parent_credential)
        session.commit()
        for token, principal, target in (("old-staff-session", "staff", credential), ("old-parent-session", "parent", parent_credential)):
            session.add(models.AuthSession(token_hash=digest(token), principal_type=principal, credential_id=target.id,
                        staff_user_id=user.id if principal == "staff" else None,
                        parent_account_id=1 if principal == "parent" else None,
                        credential_version=1, idle_expires_at=expiry, absolute_expires_at=expiry))
        session.add(models.CredentialActionToken(token_hash=digest("ABCD1234"), credential_id=credential.id, action="activate", expires_at=expiry))
        session.add(models.StaffPasswordRecovery(token_hash=digest("old-recovery"), staff_user_id=user.id,
                    credential_id=credential.id, credential_version=1, recipient=user.email, expires_at=expiry))
        registration = models.ParentRegistrationRequest(parent_account_id=1, email_normalized_snapshot=parent.email,
                        invitation_token_hash=digest("old-invite"), invitation_expires_at=expiry,
                        completion_token_hash=digest("old-complete"), completion_expires_at=expiry)
        session.add(registration)
        session.commit()
        session.add(models.ParentRegistrationSession(token_hash=digest("old-registration"), parent_account_id=1,
                    registration_request_id=registration.id, purpose="invitation", expires_at=expiry))
        session.add(models.ParentMailDelivery(parent_account_id=1, message_type="invitation", recipient=parent.email,
                    subject="架空", body="old invitation payload", status="pending"))
        session.add(models.StaffMailDelivery(staff_user_id=user.id, message_type="recovery", recipient=user.email,
                    subject="架空", body="old recovery payload", status="processing", expires_at=expiry))
        notification = models.ParentNotification(parent_account_id=1, kind=next(iter(models.ParentNotificationKind)),
                        title="架空", body="架空", source_type="test", source_id="1")
        subscription = models.ParentPushSubscription(parent_account_id=1, endpoint="https://push.example.invalid/1",
                        endpoint_hash=digest("endpoint"), p256dh_key="synthetic", auth_key="synthetic", environment="development")
        session.add(notification)
        session.add(subscription)
        session.commit()
        delivery = models.ParentNotificationDelivery(notification_id=notification.id, channel=models.NotificationDeliveryChannel.push)
        session.add(delivery)
        session.commit()
        session.add(models.ParentPushDeliveryTarget(delivery_id=delivery.id, subscription_id=subscription.id,
                    status=models.ParentPushDeliveryTargetStatus.retry_wait, shown_receipt_token_hash=digest("old-receipt")))
        session.commit()
        assert resolve_staff_session(session, "old-staff-session") is not None
        assert resolve_parent_session(session, "old-parent-session") is not None
    engine.dispose()
    backup = create_backup(runtime.config)
    destination = runtime.root / "auth-restore"
    receipt = prepare_restore(backup, destination, incident_ref="restore-auth-test", isolated=True)
    assert receipt["invalidated"]["sessions"] == 2
    database = destination / "runtime/data/hoikuict.db"
    assert rows(database, "SELECT status,body FROM parent_mail_deliveries") == [("cancelled", "")]
    assert rows(database, "SELECT status,body FROM staff_mail_deliveries") == [("cancelled", "")]
    assert rows(database, "SELECT status,shown_receipt_token_hash FROM parent_push_delivery_targets") == [("suppressed", None)]
    assert rows(database, "SELECT status FROM parent_notification_deliveries") == [("suppressed",)]
    assert rows(database, "SELECT invitation_token_hash,completion_token_hash FROM parent_registration_requests") == [(None, None)]
    assert all(row[0] is not None for row in rows(database, "SELECT consumed_at FROM parent_registration_sessions"))
    assert all(row[0] is not None for row in rows(database, "SELECT consumed_at FROM staff_password_recoveries"))
    restored_engine = create_engine(f"sqlite:///{database}")
    with Session(restored_engine) as session:
        assert resolve_staff_session(session, "old-staff-session") is None
        assert resolve_parent_session(session, "old-parent-session") is None
        with pytest.raises(AuthenticationFailed):
            get_staff_activation_details(session, activation_code="ABCD1234")
        login = authenticate_staff(session, login_id="recovery-staff", password=password)
        assert resolve_staff_session(session, login.session_token) is not None
    restored_engine.dispose()
    assert rows(runtime.main, "SELECT revoked_at FROM auth_sessions") == [(None,), (None,)]
