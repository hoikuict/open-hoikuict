import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from auth import Role, StaffUser
from models import (
    NotificationDeliveryChannel,
    NotificationDeliveryStatus,
    ParentAccount,
    ParentNotification,
    ParentNotificationDelivery,
    ParentNotificationKind,
    ParentPushDeliveryAttempt,
    ParentPushDeliveryAttemptResult,
    ParentPushDeliveryTarget,
    ParentPushDeliveryTargetStatus,
    ParentPushSubscription,
    ParentPushTransport,
)
from parent_push_subscription_service import endpoint_hash
from parent_push_service import SAFE_PUSH_TITLE
import routers.dev_parent_push as dev_parent_push_module
from testing_helpers import configure_test_environment


class DevParentPushDashboardTests(unittest.TestCase):
    def setUp(self):
        configure_test_environment()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        app = FastAPI()
        app.include_router(dev_parent_push_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[dev_parent_push_module.get_session] = override_get_session
        self.app = app
        self.client = TestClient(app)

    def _authenticate(self):
        self.app.dependency_overrides[dev_parent_push_module.get_current_staff_user] = (
            lambda: StaffUser(role=Role.ADMIN, name="開発担当")
        )

    def _seed_capture(self):
        endpoint = "https://push.example.test/private-endpoint"
        with Session(self.engine) as session:
            parent = ParentAccount(
                display_name="表示してはいけない保護者名",
                email="private-parent@example.com",
            )
            session.add(parent)
            session.flush()
            notification = ParentNotification(
                parent_account_id=parent.id,
                kind=ParentNotificationKind.attendance_confirmation_request,
                title="表示してはいけない元タイトル",
                body="園児の機微な通知本文",
                source_type="dashboard_test",
                source_id="capture-1",
            )
            session.add(notification)
            session.flush()
            delivery = ParentNotificationDelivery(
                notification_id=notification.id,
                channel=NotificationDeliveryChannel.push,
                status=NotificationDeliveryStatus.accepted,
            )
            subscription = ParentPushSubscription(
                parent_account_id=parent.id,
                endpoint=endpoint,
                endpoint_hash=endpoint_hash(endpoint),
                p256dh_key="private-p256dh-key",
                auth_key="private-auth-key",
                environment="development",
                device_label="テスト端末A",
            )
            session.add(delivery)
            session.add(subscription)
            session.flush()
            target = ParentPushDeliveryTarget(
                delivery_id=delivery.id,
                subscription_id=subscription.id,
                status=ParentPushDeliveryTargetStatus.accepted,
                attempt_count=1,
            )
            session.add(target)
            session.flush()
            attempt = ParentPushDeliveryAttempt(
                target_id=target.id,
                attempt_no=1,
                transport=ParentPushTransport.capture,
                result=ParentPushDeliveryAttemptResult.accepted,
                provider_request_id="capture",
            )
            session.add(attempt)
            session.commit()
        return endpoint

    def test_dashboard_requires_staff_authentication(self):
        response = self.client.get("/dev/push-notifications")

        self.assertEqual(response.status_code, 401)

    def test_dashboard_is_hidden_outside_development(self):
        self._authenticate()
        with patch.dict(os.environ, {"HOIKUICT_ENV": "production"}):
            response = self.client.get("/dev/push-notifications")

        self.assertEqual(response.status_code, 404)

    def test_dashboard_shows_capture_without_secrets_or_original_content(self):
        self._authenticate()
        endpoint = self._seed_capture()

        response = self.client.get("/dev/push-notifications")

        self.assertEqual(response.status_code, 200)
        self.assertIn("保護者 #1", response.text)
        self.assertIn("テスト端末A", response.text)
        self.assertIn("capture", response.text)
        self.assertIn(SAFE_PUSH_TITLE, response.text)
        self.assertNotIn(endpoint, response.text)
        self.assertNotIn("private-p256dh-key", response.text)
        self.assertNotIn("private-auth-key", response.text)
        self.assertNotIn("表示してはいけない保護者名", response.text)
        self.assertNotIn("園児の機微な通知本文", response.text)


if __name__ == "__main__":
    unittest.main()
