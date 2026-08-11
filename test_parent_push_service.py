import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, create_engine, select

import database
from models import (
    NotificationDeliveryChannel,
    NotificationDeliveryStatus,
    ParentAccount,
    ParentNotification,
    ParentNotificationDelivery,
    ParentNotificationKind,
    ParentPushDeliveryTarget,
    ParentPushDeliveryTargetStatus,
    ParentPushPreference,
    ParentPushSubscription,
)
from parent_push_service import (
    CaptureParentPushTransport,
    WebPushParentPushTransport,
    build_push_payload,
    create_parent_push_transport,
    hash_receipt_token,
    recompute_delivery_summary,
    resolve_delivery_targets,
)


class ParentPushServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_directory.name) / "push-service.db"
        self.engine = create_engine(f"sqlite:///{database_path}")
        with patch.object(database, "engine", self.engine):
            database.create_db_and_tables()
        self.now = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.engine.dispose()
        self.temp_directory.cleanup()

    def _create_delivery(self, session: Session):
        parent = ParentAccount(display_name="テスト保護者", email="push-service@example.test")
        session.add(parent)
        session.flush()
        notification = ParentNotification(
            parent_account_id=parent.id,
            kind=ParentNotificationKind.attendance_confirmation_request,
            title="園児名を含む内部タイトル",
            body="内部本文には個別情報が含まれる可能性があります。",
            source_type="test",
            source_id="push-service-1",
        )
        session.add(notification)
        session.flush()
        delivery = ParentNotificationDelivery(
            notification_id=notification.id,
            channel=NotificationDeliveryChannel.push,
            expires_at=self.now + timedelta(hours=6),
        )
        session.add(delivery)
        session.flush()
        return parent, notification, delivery

    def _create_subscription(
        self,
        session: Session,
        parent_id: int,
        *,
        suffix: str,
        environment: str = "development",
    ):
        subscription = ParentPushSubscription(
            parent_account_id=parent_id,
            endpoint=f"https://push.example.test/{suffix}",
            endpoint_hash=f"hash-{suffix}",
            p256dh_key="p256dh",
            auth_key="auth",
            environment=environment,
            is_test_device=True,
        )
        session.add(subscription)
        session.flush()
        return subscription

    def test_target_resolution_is_environment_scoped_and_idempotent(self):
        with Session(self.engine) as session:
            parent, _, delivery = self._create_delivery(session)
            development_subscription = self._create_subscription(
                session,
                parent.id,
                suffix="development",
            )
            self._create_subscription(
                session,
                parent.id,
                suffix="production",
                environment="production",
            )

            first = resolve_delivery_targets(
                session,
                delivery,
                environment="development",
                now=self.now,
            )
            second = resolve_delivery_targets(
                session,
                delivery,
                environment="development",
                now=self.now,
            )
            session.commit()

            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 1)
            self.assertEqual(first[0].subscription_id, development_subscription.id)
            self.assertIsNotNone(delivery.targets_resolved_at)
            self.assertIsNone(delivery.completed_at)
            self.assertEqual(
                len(session.exec(select(ParentPushDeliveryTarget)).all()),
                1,
            )

    def test_disabled_preference_suppresses_delivery_without_targets(self):
        with Session(self.engine) as session:
            parent, _, delivery = self._create_delivery(session)
            self._create_subscription(session, parent.id, suffix="disabled")
            session.add(
                ParentPushPreference(
                    parent_account_id=parent.id,
                    push_enabled=False,
                )
            )

            targets = resolve_delivery_targets(
                session,
                delivery,
                environment="development",
                now=self.now,
            )

            self.assertEqual(targets, [])
            self.assertEqual(delivery.status, NotificationDeliveryStatus.suppressed)
            self.assertEqual(delivery.completed_at, self.now)

    def test_expired_delivery_does_not_create_targets(self):
        with Session(self.engine) as session:
            parent, _, delivery = self._create_delivery(session)
            self._create_subscription(session, parent.id, suffix="expired")
            delivery.expires_at = self.now - timedelta(seconds=1)

            targets = resolve_delivery_targets(
                session,
                delivery,
                environment="development",
                now=self.now,
            )

            self.assertEqual(targets, [])
            self.assertEqual(delivery.status, NotificationDeliveryStatus.expired)
            self.assertEqual(delivery.completed_at, self.now)

    def test_accepted_summary_does_not_hide_retrying_target(self):
        with Session(self.engine) as session:
            parent, _, delivery = self._create_delivery(session)
            self._create_subscription(session, parent.id, suffix="accepted")
            self._create_subscription(session, parent.id, suffix="retrying")
            targets = resolve_delivery_targets(
                session,
                delivery,
                environment="development",
                now=self.now,
            )
            targets[0].status = ParentPushDeliveryTargetStatus.accepted
            targets[0].accepted_at = self.now
            targets[1].status = ParentPushDeliveryTargetStatus.retry_wait
            targets[1].next_retry_at = self.now + timedelta(minutes=1)
            session.add_all(targets)

            recompute_delivery_summary(session, delivery, now=self.now)

            self.assertEqual(delivery.status, NotificationDeliveryStatus.accepted)
            self.assertIsNone(delivery.completed_at)

            targets[1].status = ParentPushDeliveryTargetStatus.failed
            targets[1].next_retry_at = None
            session.add(targets[1])
            recompute_delivery_summary(
                session,
                delivery,
                now=self.now + timedelta(minutes=2),
            )

            self.assertEqual(delivery.status, NotificationDeliveryStatus.accepted)
            self.assertEqual(delivery.completed_at, self.now + timedelta(minutes=2))

    def test_payload_uses_safe_copy_and_target_receipt_tokens(self):
        with Session(self.engine) as session:
            parent, notification, delivery = self._create_delivery(session)
            self._create_subscription(session, parent.id, suffix="payload")
            target = resolve_delivery_targets(
                session,
                delivery,
                environment="development",
                now=self.now,
            )[0]
            shown_token = "shown-secret"
            clicked_token = "clicked-secret"

            payload = build_push_payload(
                notification=notification,
                delivery=delivery,
                target=target,
                shown_receipt_token=shown_token,
                clicked_receipt_token=clicked_token,
            )

            self.assertEqual(payload["target_id"], target.id)
            self.assertNotIn(notification.title, payload.values())
            self.assertNotIn(notification.body, payload.values())
            self.assertEqual(payload["shown_receipt_token"], shown_token)
            self.assertEqual(payload["clicked_receipt_token"], clicked_token)
            self.assertNotEqual(hash_receipt_token(shown_token), shown_token)

    def test_capture_transport_has_no_external_dependency(self):
        transport = create_parent_push_transport("capture")
        self.assertIsInstance(transport, CaptureParentPushTransport)
        result = transport.send(subscription=None, payload={})
        self.assertEqual(result.result.value, "accepted")
        self.assertEqual(result.provider_request_id, "capture")

    def test_disabled_transport_fails_closed_and_webpush_requires_vapid(self):
        with self.assertRaisesRegex(RuntimeError, "無効"):
            create_parent_push_transport("disabled")
        with patch.dict(
            "os.environ",
            {
                "HOIKUICT_PUSH_VAPID_PRIVATE_KEY": "private-key",
                "HOIKUICT_PUSH_VAPID_SUBJECT": "mailto:developer@example.com",
            },
            clear=True,
        ):
            self.assertIsInstance(
                create_parent_push_transport("webpush"),
                WebPushParentPushTransport,
            )


if __name__ == "__main__":
    unittest.main()
