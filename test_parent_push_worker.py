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
    ParentPushDeliveryAttempt,
    ParentPushDeliveryAttemptResult,
    ParentPushDeliveryTarget,
    ParentPushDeliveryTargetStatus,
    ParentPushSubscription,
    ParentPushSubscriptionStatus,
    ParentPushTransport,
)
from parent_push_service import (
    CaptureParentPushTransport,
    ParentPushSendResult,
    claim_next_delivery_target,
    plan_pending_deliveries,
    process_claimed_target,
    run_parent_push_worker_cycle,
)
from time_utils import ensure_utc


class ScriptedTransport:
    def __init__(
        self,
        results: list[ParentPushSendResult],
        *,
        name: ParentPushTransport = ParentPushTransport.capture,
    ):
        self.name = name
        self.results = list(results)
        self.payloads: list[dict[str, object]] = []

    def send(self, *, subscription, payload):
        del subscription
        self.payloads.append(payload)
        return self.results.pop(0)


class ParentPushWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_directory.name) / "push-worker.db"
        self.engine = create_engine(f"sqlite:///{database_path}", connect_args={"timeout": 15})
        with patch.object(database, "engine", self.engine):
            database.create_db_and_tables()
        self.now = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.engine.dispose()
        self.temp_directory.cleanup()

    def _create_delivery(self, session: Session, *, subscription_count: int = 1):
        parent = ParentAccount(display_name="テスト保護者", email="push-worker@example.test")
        session.add(parent)
        session.flush()
        notification = ParentNotification(
            parent_account_id=parent.id,
            kind=ParentNotificationKind.attendance_confirmation_request,
            title="内部タイトル",
            body="内部本文",
            source_type="test",
            source_id="push-worker-1",
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
        for index in range(subscription_count):
            session.add(
                ParentPushSubscription(
                    parent_account_id=parent.id,
                    endpoint=f"https://push.example.test/worker-{index}",
                    endpoint_hash=f"worker-hash-{index}",
                    p256dh_key="p256dh",
                    auth_key="auth",
                    environment="development",
                    is_test_device=True,
                )
            )
        session.commit()
        return delivery.id

    def test_worker_cycle_plans_targets_and_captures_delivery(self):
        with Session(self.engine) as session:
            delivery_id = self._create_delivery(session, subscription_count=2)
            processed = run_parent_push_worker_cycle(
                session,
                transport=CaptureParentPushTransport(),
                environment="development",
                now=self.now,
            )

            delivery = session.get(ParentNotificationDelivery, delivery_id)
            targets = session.exec(select(ParentPushDeliveryTarget)).all()
            attempts = session.exec(select(ParentPushDeliveryAttempt)).all()
            self.assertEqual(processed, 2)
            self.assertEqual(len(targets), 2)
            self.assertTrue(
                all(target.status == ParentPushDeliveryTargetStatus.accepted for target in targets)
            )
            self.assertEqual(len(attempts), 2)
            self.assertEqual(delivery.status, NotificationDeliveryStatus.accepted)
            self.assertEqual(ensure_utc(delivery.completed_at), self.now)

    def test_accepted_aggregate_does_not_block_retry_wait_target(self):
        retryable = ParentPushSendResult(
            result=ParentPushDeliveryAttemptResult.retryable_failed,
            error_code="temporary_failure",
        )
        with Session(self.engine) as session:
            delivery_id = self._create_delivery(session, subscription_count=2)
            plan_pending_deliveries(
                session,
                environment="development",
                now=self.now,
            )
            first = claim_next_delivery_target(session, now=self.now)
            process_claimed_target(
                session,
                first,
                transport=CaptureParentPushTransport(),
                environment="development",
                now=self.now,
            )
            second = claim_next_delivery_target(session, now=self.now)
            process_claimed_target(
                session,
                second,
                transport=ScriptedTransport([retryable]),
                environment="development",
                now=self.now,
            )

            delivery = session.get(ParentNotificationDelivery, delivery_id)
            self.assertEqual(delivery.status, NotificationDeliveryStatus.accepted)
            self.assertIsNone(delivery.completed_at)
            self.assertIsNone(
                claim_next_delivery_target(
                    session,
                    now=self.now + timedelta(seconds=29),
                )
            )

            retried = claim_next_delivery_target(
                session,
                now=self.now + timedelta(seconds=31),
            )
            self.assertEqual(retried.id, second.id)
            process_claimed_target(
                session,
                retried,
                transport=CaptureParentPushTransport(),
                environment="development",
                now=self.now + timedelta(seconds=31),
            )

            session.refresh(delivery)
            self.assertEqual(delivery.status, NotificationDeliveryStatus.accepted)
            self.assertEqual(
                ensure_utc(delivery.completed_at),
                self.now + timedelta(seconds=31),
            )

    def test_target_lease_prevents_duplicate_claim_and_recovers_after_expiry(self):
        with Session(self.engine) as setup_session:
            self._create_delivery(setup_session)
            plan_pending_deliveries(
                setup_session,
                environment="development",
                now=self.now,
            )

        with Session(self.engine) as first_session, Session(self.engine) as second_session:
            claimed = claim_next_delivery_target(
                first_session,
                now=self.now,
                lease_seconds=60,
            )
            self.assertIsNotNone(claimed)
            self.assertIsNone(
                claim_next_delivery_target(
                    second_session,
                    now=self.now + timedelta(seconds=30),
                    lease_seconds=60,
                )
            )
            recovered = claim_next_delivery_target(
                second_session,
                now=self.now + timedelta(seconds=61),
                lease_seconds=60,
            )
            self.assertEqual(recovered.id, claimed.id)

    def test_retry_limit_creates_attempt_history_and_finishes_failed(self):
        retryable = ParentPushSendResult(
            result=ParentPushDeliveryAttemptResult.retryable_failed,
            error_code="temporary_failure",
        )
        transport = ScriptedTransport([retryable, retryable])
        with Session(self.engine) as session:
            delivery_id = self._create_delivery(session)
            plan_pending_deliveries(
                session,
                environment="development",
                now=self.now,
            )
            target = claim_next_delivery_target(session, now=self.now)
            process_claimed_target(
                session,
                target,
                transport=transport,
                environment="development",
                now=self.now,
                max_attempts=2,
            )
            target = claim_next_delivery_target(
                session,
                now=self.now + timedelta(seconds=31),
            )
            process_claimed_target(
                session,
                target,
                transport=transport,
                environment="development",
                now=self.now + timedelta(seconds=31),
                max_attempts=2,
            )

            delivery = session.get(ParentNotificationDelivery, delivery_id)
            attempts = session.exec(
                select(ParentPushDeliveryAttempt).order_by(ParentPushDeliveryAttempt.attempt_no)
            ).all()
            self.assertEqual(target.status, ParentPushDeliveryTargetStatus.failed)
            self.assertEqual(target.attempt_count, 2)
            self.assertEqual([attempt.attempt_no for attempt in attempts], [1, 2])
            self.assertEqual(delivery.status, NotificationDeliveryStatus.failed)
            self.assertEqual(
                ensure_utc(delivery.completed_at),
                self.now + timedelta(seconds=31),
            )

    def test_subscription_gone_disables_only_the_failed_subscription(self):
        gone = ParentPushSendResult(
            result=ParentPushDeliveryAttemptResult.terminal_failed,
            provider_status_code=410,
            error_code="subscription_gone",
            error_message="Push Serviceで購読が無効になっています",
        )
        with Session(self.engine) as session:
            self._create_delivery(session, subscription_count=2)
            plan_pending_deliveries(
                session,
                environment="development",
                now=self.now,
            )
            target = claim_next_delivery_target(session, now=self.now)
            process_claimed_target(
                session,
                target,
                transport=ScriptedTransport([gone]),
                environment="development",
                now=self.now,
            )

            failed_subscription = session.get(
                ParentPushSubscription,
                target.subscription_id,
            )
            other_subscription = session.exec(
                select(ParentPushSubscription).where(
                    ParentPushSubscription.id != target.subscription_id
                )
            ).one()
            self.assertEqual(
                failed_subscription.status,
                ParentPushSubscriptionStatus.expired,
            )
            self.assertEqual(
                failed_subscription.disabled_reason,
                "push_service_gone",
            )
            self.assertEqual(
                other_subscription.status,
                ParentPushSubscriptionStatus.active,
            )

    def test_development_webpush_suppresses_non_test_device_before_send(self):
        with Session(self.engine) as session:
            delivery_id = self._create_delivery(session)
            subscription = session.exec(select(ParentPushSubscription)).one()
            subscription.is_test_device = False
            session.add(subscription)
            session.commit()
            plan_pending_deliveries(
                session,
                environment="development",
                now=self.now,
            )
            target = claim_next_delivery_target(session, now=self.now)
            transport = ScriptedTransport(
                [
                    ParentPushSendResult(
                        result=ParentPushDeliveryAttemptResult.accepted,
                    )
                ],
                name=ParentPushTransport.webpush,
            )

            process_claimed_target(
                session,
                target,
                transport=transport,
                environment="development",
                now=self.now,
            )

            delivery = session.get(ParentNotificationDelivery, delivery_id)
            self.assertEqual(target.status, ParentPushDeliveryTargetStatus.suppressed)
            self.assertEqual(delivery.status, NotificationDeliveryStatus.suppressed)
            self.assertEqual(transport.payloads, [])
            self.assertEqual(
                session.exec(select(ParentPushDeliveryAttempt)).all(),
                [],
            )

    def test_expired_target_finishes_without_transport_attempt(self):
        with Session(self.engine) as session:
            delivery_id = self._create_delivery(session)
            delivery = session.get(ParentNotificationDelivery, delivery_id)
            delivery.expires_at = self.now - timedelta(seconds=1)
            session.add(delivery)
            session.commit()
            plan_pending_deliveries(
                session,
                environment="development",
                now=self.now,
            )

            self.assertIsNone(claim_next_delivery_target(session, now=self.now))
            session.refresh(delivery)
            self.assertEqual(delivery.status, NotificationDeliveryStatus.expired)
            self.assertEqual(
                session.exec(select(ParentPushDeliveryAttempt)).all(),
                [],
            )


if __name__ == "__main__":
    unittest.main()
