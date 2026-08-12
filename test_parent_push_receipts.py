import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from csrf import CsrfTokenMiddleware, verify_csrf
from models import (
    NotificationDeliveryChannel,
    NotificationDeliveryStatus,
    ParentAccount,
    ParentNotification,
    ParentNotificationDelivery,
    ParentNotificationKind,
    ParentPushDeliveryTarget,
    ParentPushDeliveryTargetStatus,
    ParentPushSubscription,
)
from parent_push_service import hash_receipt_token
from parent_push_subscription_service import endpoint_hash
import routers.parent_push as parent_push_module
from testing_helpers import configure_test_environment
from time_utils import utc_now


class ParentPushReceiptApiTests(unittest.TestCase):
    def setUp(self):
        configure_test_environment()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        app = FastAPI(dependencies=[Depends(verify_csrf)])
        app.add_middleware(CsrfTokenMiddleware)
        app.include_router(parent_push_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[parent_push_module.get_session] = override_get_session
        self.client = TestClient(app)
        self.shown_token = "shown-token-012345678901234567890"
        self.clicked_token = "clicked-token-01234567890123456789"
        self.target_id, self.delivery_id = self._seed_accepted_target()

    def _seed_accepted_target(self):
        now = utc_now()
        endpoint = "https://push.example.test/receipt-device"
        with Session(self.engine) as session:
            parent = ParentAccount(
                display_name="Receipt保護者",
                email="receipt-parent@example.com",
            )
            session.add(parent)
            session.flush()
            notification = ParentNotification(
                parent_account_id=parent.id,
                kind=ParentNotificationKind.attendance_confirmation_request,
                title="内部タイトル",
                body="内部本文",
                source_type="receipt_test",
                source_id="receipt-1",
            )
            session.add(notification)
            session.flush()
            delivery = ParentNotificationDelivery(
                notification_id=notification.id,
                channel=NotificationDeliveryChannel.push,
                status=NotificationDeliveryStatus.accepted,
                expires_at=now + timedelta(hours=1),
                targets_resolved_at=now,
                accepted_at=now,
            )
            subscription = ParentPushSubscription(
                parent_account_id=parent.id,
                endpoint=endpoint,
                endpoint_hash=endpoint_hash(endpoint),
                p256dh_key="private-p256dh",
                auth_key="private-auth",
                environment="development",
                is_test_device=True,
            )
            session.add(delivery)
            session.add(subscription)
            session.flush()
            target = ParentPushDeliveryTarget(
                delivery_id=delivery.id,
                subscription_id=subscription.id,
                status=ParentPushDeliveryTargetStatus.accepted,
                accepted_at=now,
                shown_receipt_token_hash=hash_receipt_token(self.shown_token),
                clicked_receipt_token_hash=hash_receipt_token(self.clicked_token),
            )
            session.add(target)
            session.commit()
            session.refresh(target)
            return target.id, delivery.id

    def _post_receipt(self, event, token):
        with patch.dict(os.environ, {"HOIKUICT_CSRF_ENFORCE": "1"}):
            return self.client.post(
                f"/parent-portal/push/receipts/{self.target_id}/{event}",
                json={"token": token},
            )

    def test_shown_receipt_is_csrf_exempt_and_updates_target_and_delivery(self):
        response = self._post_receipt("shown", self.shown_token)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "recorded", "event": "shown"})
        with Session(self.engine) as session:
            target = session.get(ParentPushDeliveryTarget, self.target_id)
            delivery = session.get(ParentNotificationDelivery, self.delivery_id)
            self.assertEqual(target.status, ParentPushDeliveryTargetStatus.shown)
            self.assertIsNotNone(target.shown_at)
            self.assertEqual(delivery.status, NotificationDeliveryStatus.shown)
            self.assertEqual(delivery.shown_at, target.shown_at)

    def test_receipt_retry_is_idempotent(self):
        first = self._post_receipt("shown", self.shown_token)
        with Session(self.engine) as session:
            first_shown_at = session.get(
                ParentPushDeliveryTarget,
                self.target_id,
            ).shown_at

        second = self._post_receipt("shown", self.shown_token)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        with Session(self.engine) as session:
            target = session.get(ParentPushDeliveryTarget, self.target_id)
            self.assertEqual(target.shown_at, first_shown_at)

    def test_clicked_receipt_uses_clicked_token_and_preserves_shown_time(self):
        self._post_receipt("shown", self.shown_token)
        with Session(self.engine) as session:
            shown_at = session.get(ParentPushDeliveryTarget, self.target_id).shown_at

        wrong_token = self._post_receipt("clicked", self.shown_token)
        clicked = self._post_receipt("clicked", self.clicked_token)

        self.assertEqual(wrong_token.status_code, 404)
        self.assertEqual(clicked.status_code, 200)
        with Session(self.engine) as session:
            target = session.get(ParentPushDeliveryTarget, self.target_id)
            delivery = session.get(ParentNotificationDelivery, self.delivery_id)
            self.assertEqual(target.status, ParentPushDeliveryTargetStatus.clicked)
            self.assertEqual(target.shown_at, shown_at)
            self.assertIsNotNone(target.clicked_at)
            self.assertEqual(delivery.status, NotificationDeliveryStatus.clicked)
            self.assertEqual(delivery.clicked_at, target.clicked_at)

    def test_invalid_token_does_not_reveal_target(self):
        response = self._post_receipt(
            "shown",
            "invalid-token-01234567890123456789",
        )

        self.assertEqual(response.status_code, 404)
        with Session(self.engine) as session:
            target = session.get(ParentPushDeliveryTarget, self.target_id)
            self.assertEqual(target.status, ParentPushDeliveryTargetStatus.accepted)
            self.assertIsNone(target.shown_at)

    def test_expired_receipt_is_rejected(self):
        with Session(self.engine) as session:
            delivery = session.get(ParentNotificationDelivery, self.delivery_id)
            delivery.expires_at = utc_now() - timedelta(seconds=1)
            session.add(delivery)
            session.commit()

        response = self._post_receipt("shown", self.shown_token)

        self.assertEqual(response.status_code, 410)

    def test_valid_token_is_rejected_for_non_accepted_target(self):
        with Session(self.engine) as session:
            target = session.get(ParentPushDeliveryTarget, self.target_id)
            target.status = ParentPushDeliveryTargetStatus.pending
            session.add(target)
            session.commit()

        response = self._post_receipt("shown", self.shown_token)

        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
