import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, create_engine

import database
from models import (
    NotificationDeliveryChannel,
    ParentAccount,
    ParentNotification,
    ParentNotificationDelivery,
    ParentNotificationKind,
    ParentPushDeliveryAttempt,
    ParentPushDeliveryAttemptResult,
    ParentPushDeliveryTarget,
    ParentPushPreference,
    ParentPushSubscription,
    ParentPushTransport,
)


class ParentPushModelTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_directory.name) / "push-models.db"
        self.engine = create_engine(f"sqlite:///{database_path}")
        self.engine.connect().close()
        with patch.object(database, "engine", self.engine):
            database.create_db_and_tables()

    def tearDown(self):
        self.engine.dispose()
        self.temp_directory.cleanup()

    def _create_graph(self, session: Session):
        parent = ParentAccount(display_name="テスト保護者", email="push-parent@example.test")
        session.add(parent)
        session.flush()
        notification = ParentNotification(
            parent_account_id=parent.id,
            kind=ParentNotificationKind.attendance_confirmation_request,
            title="確認のお願い",
            body="保護者ポータルをご確認ください。",
            target_date=date(2026, 8, 12),
            source_type="test",
            source_id="push-model-1",
        )
        session.add(notification)
        session.flush()
        delivery = ParentNotificationDelivery(
            notification_id=notification.id,
            channel=NotificationDeliveryChannel.push,
        )
        subscription = ParentPushSubscription(
            parent_account_id=parent.id,
            endpoint="https://push.example.test/subscription/1",
            endpoint_hash="endpoint-hash-1",
            p256dh_key="p256dh",
            auth_key="auth",
            environment="test",
            is_test_device=True,
        )
        preference = ParentPushPreference(parent_account_id=parent.id)
        session.add(delivery)
        session.add(subscription)
        session.add(preference)
        session.flush()
        target = ParentPushDeliveryTarget(
            delivery_id=delivery.id,
            subscription_id=subscription.id,
        )
        session.add(target)
        session.flush()
        attempt = ParentPushDeliveryAttempt(
            target_id=target.id,
            attempt_no=1,
            transport=ParentPushTransport.capture,
            result=ParentPushDeliveryAttemptResult.accepted,
        )
        session.add(attempt)
        session.commit()
        return parent, delivery, subscription, preference, target, attempt

    def test_push_graph_defaults_and_foreign_keys_can_be_persisted(self):
        with Session(self.engine) as session:
            _, delivery, subscription, preference, target, attempt = self._create_graph(session)
            session.refresh(delivery)
            session.refresh(subscription)
            session.refresh(preference)
            session.refresh(target)
            session.refresh(attempt)

            self.assertEqual(delivery.status.value, "pending")
            self.assertEqual(subscription.status.value, "active")
            self.assertTrue(preference.push_enabled)
            self.assertTrue(preference.attendance_confirmation_enabled)
            self.assertEqual(target.status.value, "pending")
            self.assertEqual(attempt.result.value, "accepted")

    def test_delivery_target_is_unique_per_subscription(self):
        with Session(self.engine) as session:
            _, delivery, subscription, _, _, _ = self._create_graph(session)
            session.add(
                ParentPushDeliveryTarget(
                    delivery_id=delivery.id,
                    subscription_id=subscription.id,
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_attempt_number_is_unique_per_target(self):
        with Session(self.engine) as session:
            _, _, _, _, target, _ = self._create_graph(session)
            session.add(
                ParentPushDeliveryAttempt(
                    target_id=target.id,
                    attempt_no=1,
                    transport=ParentPushTransport.capture,
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()


if __name__ == "__main__":
    unittest.main()
