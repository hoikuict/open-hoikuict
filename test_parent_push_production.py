import base64
import os
from datetime import timedelta
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from csrf import CSRF_COOKIE_NAME, CsrfTokenMiddleware, verify_csrf
from models import (
    ParentAccount,
    ParentChildLink,
    ParentNotification,
    ParentPushDeliveryTarget,
    ParentPushSubscription,
    ParentPushSubscriptionStatus,
    PasswordCredential,
)
from parent_notification_service import notify_attendance_confirmation_needed
from parent_push_service import WebPushParentPushTransport, run_parent_push_worker_cycle
from parent_push_validation import production_push_endpoint_allowed
from security_config import validate_runtime_security
from test_guardian_account_sync import pilot as base_pilot
from test_parent_code_mail import active_account
import test_security_controls
from time_utils import utc_now, local_today
import routers.parent_auth as auth_routes
import routers.parent_push as push_routes


def public_key(key):
    return (
        base64.urlsafe_b64encode(
            key.public_key().public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
        )
        .decode()
        .rstrip("=")
    )


@pytest.fixture
def key_settings(tmp_path):
    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path / "push.pem"
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    blocklist = tmp_path / "blocklist.txt"
    blocklist.write_text("password\n", encoding="utf-8")
    return {
        **test_security_controls.SecurityControlTests._valid_production_settings(),
        "HOIKUICT_CSRF_ENFORCE": "1",
        "HOIKUICT_COOKIE_SECURE": "1",
        "HOIKUICT_PUSH_TRANSPORT": "webpush",
        "HOIKUICT_PUSH_VAPID_PUBLIC_KEY": public_key(key),
        "HOIKUICT_PUSH_VAPID_PRIVATE_KEY": str(path),
        "HOIKUICT_PUSH_VAPID_SUBJECT": "mailto:operator@example.test",
        "HOIKUICT_PUBLIC_ORIGIN": "https://parents.example.jp",
        "HOIKUICT_ALLOWED_ORIGINS": "https://parents.example.jp",
        "HOIKUICT_PASSWORD_BLOCKLIST_PATH": str(blocklist),
    }


def test_production_startup_validates_matching_keys_and_keeps_auth_requirements(
    key_settings,
):
    with patch.dict(os.environ, key_settings, clear=True):
        validate_runtime_security()
    changes = [
        {
            "HOIKUICT_PUSH_VAPID_PUBLIC_KEY": public_key(
                ec.generate_private_key(ec.SECP256R1())
            )
        },
        {"HOIKUICT_PUSH_VAPID_PRIVATE_KEY": "missing-private-key-file"},
        {"HOIKUICT_PUBLIC_ORIGIN": "http://localhost:8000"},
        {"HOIKUICT_PUBLIC_ORIGIN": "https://other.example.jp"},
        {"HOIKUICT_PARENT_AUTH_MODE": "mock"},
        {"HOIKUICT_CSRF_ENFORCE": "0"},
    ]
    for change in changes:
        with (
            patch.dict(os.environ, {**key_settings, **change}, clear=True),
            pytest.raises(RuntimeError),
        ):
            validate_runtime_security()


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://127.0.0.1/private",
        "https://10.0.0.1/private",
        "https://attacker.test/push",
        "https://fcm.googleapis.com.attacker.test/push",
        "https://fcm.googleapis.com@attacker.test/push",
        "https://fcm.googleapis.com:8443/push",
        "https://fcm.googleapis.com/push#fragment",
        "http://fcm.googleapis.com/push",
        "https://fcm.googleapis.com\\@attacker.test/push",
    ],
)
def test_private_and_non_provider_endpoints_rejected(endpoint):
    assert not production_push_endpoint_allowed(endpoint)


@pytest.fixture
def pilot(monkeypatch, key_settings):
    fixture = base_pilot.__wrapped__(monkeypatch)
    context = next(fixture)
    _, engine, ids, _ = context
    account_id = active_account(context)
    for name, value in key_settings.items():
        monkeypatch.setenv(name, value)
    app = FastAPI(dependencies=[Depends(verify_csrf)])
    app.add_middleware(CsrfTokenMiddleware)
    for router in (auth_routes.router, push_routes.router, push_routes.settings_router):
        app.include_router(router)

    def get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[push_routes.get_session] = get_session
    try:
        with TestClient(app, base_url="https://parents.example.jp") as client:
            client.get("/parent-portal/push-settings")
            response = client.post(
                "/parent-portal/login",
                data={
                    "login_id": "parent@example.test",
                    "password": "River!7892Long-Phrase",
                    "csrf_token": client.cookies.get(CSRF_COOKIE_NAME),
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            page = client.get("/parent-portal/push-settings")
            assert page.status_code == 200 and "この端末へテスト通知を送る" in page.text
            client.headers["X-CSRF-Token"] = client.cookies.get(CSRF_COOKIE_NAME)
            yield client, engine, {**ids, "account": account_id}
    finally:
        fixture.close()


def subscription_payload(suffix="one"):
    return {
        "endpoint": "https://fcm.googleapis.com/fcm/send/synthetic-" + suffix,
        "keys": {
            "p256dh": public_key(ec.generate_private_key(ec.SECP256R1())),
            "auth": base64.urlsafe_b64encode(b"synthetic-key-12").decode().rstrip("="),
        },
        "is_test_device": True,
        "device_label": "Synthetic device",
    }


def register(pilot, suffix="one"):
    response = pilot[0].post(
        "/parent-portal/push/subscriptions", json=subscription_payload(suffix)
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def transport(calls):
    def sender(**values):
        calls.append(values)
        return type("Response", (), {"status_code": 201, "headers": {}})()

    return WebPushParentPushTransport(
        vapid_private_key="synthetic",
        vapid_subject="mailto:operator@example.test",
        sender=sender,
    )


def test_real_auth_current_device_test_and_receipts_without_external_send(pilot):
    client, engine, ids = pilot
    first_id = register(pilot)
    second_id = register(pilot, "two")
    # Preserve a second registered device for this same parent.
    with Session(engine) as session:
        first = session.get(ParentPushSubscription, first_id)
        first.status = ParentPushSubscriptionStatus.active
        session.add(first)
        session.commit()
    response = client.post("/parent-portal/push/test")
    assert response.status_code == 200
    notification_id = response.json()["notification_id"]
    assert client.post("/parent-portal/push/test").status_code == 429
    calls = []
    with Session(engine) as session:
        subscriptions = session.exec(select(ParentPushSubscription)).all()
        assert all(
            s.environment == "production" and not s.is_test_device
            for s in subscriptions
        )
        targets = session.exec(select(ParentPushDeliveryTarget)).all()
        assert len(targets) == 1 and targets[0].subscription_id == second_id
        assert (
            run_parent_push_worker_cycle(
                session, transport=transport(calls), environment="production"
            )
            == 1
        )
    assert len(calls) == 1 and calls[0]["subscription_info"]["endpoint"].endswith(
        "synthetic-two"
    )
    assert (
        client.get(f"/parent-portal/push/test/{notification_id}").json()["status"]
        == "accepted"
    )
    import json

    payload = json.loads(calls[0]["data"])
    assert payload["title"] == "通知のテスト" and "検証" not in payload["body"]
    for event in ("shown", "clicked"):
        assert (
            client.post(
                f"/parent-portal/push/receipts/{payload['target_id']}/{event}",
                json={"token": payload[f"{event}_receipt_token"]},
            ).status_code
            == 200
        )
    assert (
        client.get(f"/parent-portal/push/test/{notification_id}").json()["status"]
        == "clicked"
    )
    client.cookies.clear()
    assert client.post("/parent-portal/push/test").status_code in {401, 403}
    assert client.get(f"/parent-portal/push/test/{notification_id}").status_code == 401


def test_preferences_csrf_and_malformed_subscription(pilot):
    client, engine, _ = pilot
    register(pilot)
    assert (
        client.post(
            "/parent-portal/push/test", headers={"X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/parent-portal/push/preferences",
            json={"push_enabled": False, "attendance_confirmation_enabled": True},
        ).status_code
        == 200
    )
    assert client.post("/parent-portal/push/test").status_code == 409
    for change in [
        {"endpoint": "https://127.0.0.1/internal"},
        {"keys": {"p256dh": "bad", "auth": "bad"}},
    ]:
        assert (
            client.post(
                "/parent-portal/push/subscriptions",
                json={**subscription_payload(), **change},
            ).status_code
            == 400
        )
    with Session(engine) as session:
        assert not session.exec(select(ParentNotification)).first()


@pytest.mark.parametrize(
    "revoke", [None, "link", "credential", "account", "subscription", "expired"]
)
def test_production_rechecks_recipient_and_expiry_before_delivery(pilot, revoke):
    client, engine, ids = pilot
    subscription_id = register(pilot)
    calls = []
    with Session(engine) as session:
        from models import Child, ParentAccountStatus, ParentNotificationDelivery

        child = session.get(Child, ids["child"])
        notify_attendance_confirmation_needed(
            session,
            child=child,
            target_date=local_today(),
            source_id="synthetic",
            created_by_name="Synthetic",
        )
        session.commit()
        from parent_push_service import plan_pending_deliveries

        plan_pending_deliveries(session, environment="production")
        if revoke == "link":
            session.delete(session.exec(select(ParentChildLink)).one())
        elif revoke == "credential":
            row = session.exec(select(PasswordCredential)).one()
            row.disabled_at = utc_now()
            session.add(row)
        elif revoke == "account":
            row = session.get(ParentAccount, ids["account"])
            row.status = ParentAccountStatus.inactive
            session.add(row)
        elif revoke == "subscription":
            row = session.get(ParentPushSubscription, subscription_id)
            row.status = ParentPushSubscriptionStatus.revoked
            session.add(row)
        elif revoke == "expired":
            for row in session.exec(select(ParentNotificationDelivery)).all():
                row.expires_at = utc_now() - timedelta(seconds=1)
                session.add(row)
        session.commit()
        run_parent_push_worker_cycle(
            session, transport=transport(calls), environment="production"
        )
    assert len(calls) == (1 if revoke is None else 0)
