import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from models import (
    ParentAccount,
    ParentPushPreference,
    ParentPushSubscription,
    ParentPushSubscriptionStatus,
)
from auth import MOCK_PARENT_ACCOUNT_COOKIE
import routers.parent_portal as parent_portal_module
import routers.parent_push as parent_push_module
from testing_helpers import configure_test_environment


class ParentPushApiTests(unittest.TestCase):
    def setUp(self):
        configure_test_environment()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        app = FastAPI()
        app.include_router(parent_portal_module.router)
        app.include_router(parent_portal_module.mock_login_router)
        app.include_router(parent_push_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[parent_portal_module.get_session] = override_get_session
        app.dependency_overrides[parent_push_module.get_session] = override_get_session
        self.client = TestClient(app)

        with Session(self.engine) as session:
            first = ParentAccount(
                display_name="保護者A",
                email="parent-a@example.com",
            )
            second = ParentAccount(
                display_name="保護者B",
                email="parent-b@example.com",
            )
            session.add(first)
            session.add(second)
            session.commit()
            session.refresh(first)
            session.refresh(second)
            self.first_parent_id = first.id
            self.second_parent_id = second.id

        self.endpoint = "https://push.example.test/subscriptions/device-a"

    def _login(self, parent_account_id: int) -> None:
        response = self.client.post(
            "/parent-portal/login",
            data={"parent_account_id": parent_account_id},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def _subscription_payload(self, **overrides):
        payload = {
            "endpoint": self.endpoint,
            "keys": {"p256dh": "p256dh-key", "auth": "auth-key"},
            "device_label": "保護者スマートフォン",
        }
        payload.update(overrides)
        return payload

    def test_registration_requires_parent_authentication(self):
        response = self.client.post(
            "/parent-portal/push/subscriptions",
            json=self._subscription_payload(),
        )

        self.assertEqual(response.status_code, 401)

    def test_registration_persists_without_returning_endpoint_or_keys(self):
        self._login(self.first_parent_id)

        response = self.client.post(
            "/parent-portal/push/subscriptions",
            json=self._subscription_payload(),
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "active")
        self.assertEqual(body["device_label"], "保護者スマートフォン")
        self.assertNotIn("endpoint", body)
        self.assertNotIn("p256dh", body)
        self.assertNotIn("auth", body)
        self.assertIn("parent_push_device", self.client.cookies)

        with Session(self.engine) as session:
            subscription = session.exec(select(ParentPushSubscription)).one()
            self.assertEqual(subscription.parent_account_id, self.first_parent_id)
            self.assertEqual(subscription.endpoint, self.endpoint)
            self.assertEqual(subscription.p256dh_key, "p256dh-key")
            self.assertEqual(subscription.auth_key, "auth-key")
            self.assertEqual(subscription.environment, "development")

    def test_reregistering_same_endpoint_is_idempotent(self):
        self._login(self.first_parent_id)
        self.client.post(
            "/parent-portal/push/subscriptions",
            json=self._subscription_payload(),
        )

        response = self.client.post(
            "/parent-portal/push/subscriptions",
            json=self._subscription_payload(
                keys={"p256dh": "new-p256dh", "auth": "new-auth"}
            ),
        )

        self.assertEqual(response.status_code, 200)
        with Session(self.engine) as session:
            subscriptions = session.exec(select(ParentPushSubscription)).all()
            self.assertEqual(len(subscriptions), 1)
            self.assertEqual(subscriptions[0].p256dh_key, "new-p256dh")
            self.assertEqual(subscriptions[0].auth_key, "new-auth")

    def test_endpoint_cannot_be_claimed_by_another_parent(self):
        self._login(self.first_parent_id)
        self.client.post(
            "/parent-portal/push/subscriptions",
            json=self._subscription_payload(),
        )
        self.client.cookies.clear()
        self._login(self.second_parent_id)

        response = self.client.post(
            "/parent-portal/push/subscriptions",
            json=self._subscription_payload(),
        )

        self.assertEqual(response.status_code, 409)
        with Session(self.engine) as session:
            subscription = session.exec(select(ParentPushSubscription)).one()
            self.assertEqual(subscription.parent_account_id, self.first_parent_id)

    def test_preferences_default_without_creating_row_then_can_be_saved(self):
        self._login(self.first_parent_id)

        response = self.client.get("/parent-portal/push/preferences")

        self.assertEqual(
            response.json(),
            {"push_enabled": True, "attendance_confirmation_enabled": True},
        )
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(ParentPushPreference)).all(), [])

        response = self.client.post(
            "/parent-portal/push/preferences",
            json={
                "push_enabled": False,
                "attendance_confirmation_enabled": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["push_enabled"])
        with Session(self.engine) as session:
            preference = session.exec(select(ParentPushPreference)).one()
            self.assertEqual(preference.parent_account_id, self.first_parent_id)
            self.assertFalse(preference.push_enabled)

    def test_current_subscription_can_be_revoked(self):
        self._login(self.first_parent_id)
        self.client.post(
            "/parent-portal/push/subscriptions",
            json=self._subscription_payload(),
        )

        response = self.client.request(
            "DELETE",
            "/parent-portal/push/subscriptions/current",
            json={"endpoint": self.endpoint},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "revoked"})
        self.assertNotIn("parent_push_device", self.client.cookies)
        with Session(self.engine) as session:
            subscription = session.exec(select(ParentPushSubscription)).one()
            self.assertEqual(subscription.status, ParentPushSubscriptionStatus.revoked)
            self.assertEqual(subscription.disabled_reason, "parent_unsubscribed")

    def test_endpoint_must_use_https(self):
        self._login(self.first_parent_id)

        response = self.client.post(
            "/parent-portal/push/subscriptions",
            json=self._subscription_payload(endpoint="http://push.example.test/device"),
        )

        self.assertEqual(response.status_code, 422)

    def test_explicit_logout_revokes_only_this_browser_subscription(self):
        self._login(self.first_parent_id)
        registration = self.client.post(
            "/parent-portal/push/subscriptions",
            json=self._subscription_payload(),
        )
        current_subscription_id = registration.json()["id"]
        with Session(self.engine) as session:
            other_device = ParentPushSubscription(
                parent_account_id=self.first_parent_id,
                endpoint="https://push.example.test/subscriptions/device-b",
                endpoint_hash=parent_push_module.endpoint_hash(
                    "https://push.example.test/subscriptions/device-b"
                ),
                p256dh_key="other-p256dh",
                auth_key="other-auth",
                environment="development",
            )
            session.add(other_device)
            session.commit()
            session.refresh(other_device)
            other_subscription_id = other_device.id

        response = self.client.post(
            "/parent-portal/logout",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertNotIn(MOCK_PARENT_ACCOUNT_COOKIE, self.client.cookies)
        self.assertNotIn("parent_push_device", self.client.cookies)
        with Session(self.engine) as session:
            current = session.get(ParentPushSubscription, current_subscription_id)
            other = session.get(ParentPushSubscription, other_subscription_id)
            self.assertEqual(current.status, ParentPushSubscriptionStatus.revoked)
            self.assertEqual(current.disabled_reason, "explicit_logout")
            self.assertEqual(other.status, ParentPushSubscriptionStatus.active)

    def test_session_expiry_does_not_revoke_subscription(self):
        self._login(self.first_parent_id)
        registration = self.client.post(
            "/parent-portal/push/subscriptions",
            json=self._subscription_payload(),
        )
        subscription_id = registration.json()["id"]

        self.client.cookies.delete(MOCK_PARENT_ACCOUNT_COOKIE)
        response = self.client.get("/parent-portal/push/preferences")

        self.assertEqual(response.status_code, 401)
        with Session(self.engine) as session:
            subscription = session.get(ParentPushSubscription, subscription_id)
            self.assertEqual(subscription.status, ParentPushSubscriptionStatus.active)
            self.assertIsNone(subscription.disabled_at)


if __name__ == "__main__":
    unittest.main()
