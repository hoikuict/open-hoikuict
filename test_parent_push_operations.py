import unittest
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

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
from parent_push_operations import (
    build_parent_push_daily_metrics,
    purge_parent_push_operational_data,
)
from time_utils import ensure_utc


class ParentPushOperationsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.now = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)

    def _parent(self, session, *, suffix="main"):
        parent = ParentAccount(
            display_name=f"運用保護者{suffix}",
            email=f"operations-{suffix}@example.com",
        )
        session.add(parent)
        session.flush()
        return parent

    def _notification(self, session, parent, *, suffix, created_at=None):
        notification = ParentNotification(
            parent_account_id=parent.id,
            kind=ParentNotificationKind.attendance_confirmation_request,
            title="内部タイトル",
            body="内部本文",
            source_type="operations_test",
            source_id=suffix,
            created_at=created_at or self.now,
        )
        session.add(notification)
        session.flush()
        return notification

    def _subscription(self, session, parent, *, suffix, **overrides):
        values = {
            "parent_account_id": parent.id,
            "endpoint": f"https://push.example.test/{suffix}",
            "endpoint_hash": f"hash-{suffix}",
            "p256dh_key": f"p256dh-{suffix}",
            "auth_key": f"auth-{suffix}",
            "environment": "development",
            "device_label": f"端末{suffix}",
            "user_agent": "private-user-agent",
        }
        values.update(overrides)
        subscription = ParentPushSubscription(**values)
        session.add(subscription)
        session.flush()
        return subscription

    def test_daily_metrics_distinguish_delivery_outcomes(self):
        with Session(self.engine) as session:
            parent = self._parent(session)
            notification = self._notification(session, parent, suffix="delivery")
            delivery = ParentNotificationDelivery(
                notification_id=notification.id,
                channel=NotificationDeliveryChannel.push,
                status=NotificationDeliveryStatus.clicked,
                created_at=self.now,
            )
            session.add(delivery)
            session.flush()
            clicked_subscription = self._subscription(
                session,
                parent,
                suffix="clicked",
            )
            failed_subscription = self._subscription(
                session,
                parent,
                suffix="failed",
            )
            retry_subscription = self._subscription(
                session,
                parent,
                suffix="retry",
            )
            clicked_target = ParentPushDeliveryTarget(
                delivery_id=delivery.id,
                subscription_id=clicked_subscription.id,
                status=ParentPushDeliveryTargetStatus.clicked,
                accepted_at=self.now,
                shown_at=self.now,
                clicked_at=self.now,
                created_at=self.now,
            )
            failed_target = ParentPushDeliveryTarget(
                delivery_id=delivery.id,
                subscription_id=failed_subscription.id,
                status=ParentPushDeliveryTargetStatus.failed,
                created_at=self.now,
            )
            retry_target = ParentPushDeliveryTarget(
                delivery_id=delivery.id,
                subscription_id=retry_subscription.id,
                status=ParentPushDeliveryTargetStatus.retry_wait,
                next_retry_at=self.now + timedelta(minutes=2),
                created_at=self.now,
            )
            session.add(clicked_target)
            session.add(failed_target)
            session.add(retry_target)
            session.flush()
            session.add(
                ParentPushDeliveryAttempt(
                    target_id=failed_target.id,
                    attempt_no=1,
                    transport=ParentPushTransport.webpush,
                    result=ParentPushDeliveryAttemptResult.terminal_failed,
                    error_code="subscription_gone",
                    created_at=self.now,
                )
            )
            session.add(
                ParentPushDeliveryAttempt(
                    target_id=failed_target.id,
                    attempt_no=2,
                    transport=ParentPushTransport.webpush,
                    result=ParentPushDeliveryAttemptResult.terminal_failed,
                    error_code="vapid_auth_failed",
                    created_at=self.now,
                )
            )
            no_target_notification = self._notification(
                session,
                parent,
                suffix="no-target",
            )
            session.add(
                ParentNotificationDelivery(
                    notification_id=no_target_notification.id,
                    channel=NotificationDeliveryChannel.push,
                    status=NotificationDeliveryStatus.suppressed,
                    created_at=self.now,
                )
            )
            session.commit()

            metrics = build_parent_push_daily_metrics(
                session,
                day=date(2026, 8, 12),
            )

            self.assertEqual(metrics.notification_count, 2)
            self.assertEqual(metrics.push_delivery_count, 2)
            self.assertEqual(metrics.target_count, 3)
            self.assertEqual(metrics.no_subscription_count, 1)
            self.assertEqual(metrics.accepted_count, 1)
            self.assertEqual(metrics.shown_count, 1)
            self.assertEqual(metrics.clicked_count, 1)
            self.assertEqual(metrics.terminal_failed_count, 1)
            self.assertEqual(metrics.subscription_gone_count, 1)
            self.assertEqual(metrics.vapid_auth_failed_count, 1)
            self.assertEqual(metrics.retry_wait_count, 1)
            self.assertEqual(
                metrics.oldest_retry_at,
                ensure_utc(retry_target.next_retry_at),
            )

    def test_retention_deletes_old_attempts_and_redacts_old_disabled_subscription(self):
        old_at = self.now - timedelta(days=91)
        recent_at = self.now - timedelta(days=89)
        with Session(self.engine) as session:
            parent = self._parent(session, suffix="retention")
            notification = self._notification(
                session,
                parent,
                suffix="retention",
                created_at=old_at,
            )
            delivery = ParentNotificationDelivery(
                notification_id=notification.id,
                channel=NotificationDeliveryChannel.push,
                created_at=old_at,
            )
            session.add(delivery)
            session.flush()
            old_revoked = self._subscription(
                session,
                parent,
                suffix="old-revoked",
                status=ParentPushSubscriptionStatus.revoked,
                disabled_at=old_at,
            )
            recent_revoked = self._subscription(
                session,
                parent,
                suffix="recent-revoked",
                status=ParentPushSubscriptionStatus.revoked,
                disabled_at=recent_at,
            )
            active = self._subscription(
                session,
                parent,
                suffix="active",
                status=ParentPushSubscriptionStatus.active,
                disabled_at=old_at,
            )
            target = ParentPushDeliveryTarget(
                delivery_id=delivery.id,
                subscription_id=old_revoked.id,
                status=ParentPushDeliveryTargetStatus.failed,
                created_at=old_at,
            )
            session.add(target)
            session.flush()
            old_attempt = ParentPushDeliveryAttempt(
                target_id=target.id,
                attempt_no=1,
                transport=ParentPushTransport.webpush,
                result=ParentPushDeliveryAttemptResult.terminal_failed,
                created_at=old_at,
            )
            recent_attempt = ParentPushDeliveryAttempt(
                target_id=target.id,
                attempt_no=2,
                transport=ParentPushTransport.webpush,
                result=ParentPushDeliveryAttemptResult.terminal_failed,
                created_at=recent_at,
            )
            session.add(old_attempt)
            session.add(recent_attempt)
            session.commit()
            old_attempt_id = old_attempt.id
            recent_attempt_id = recent_attempt.id
            old_revoked_id = old_revoked.id
            recent_revoked_id = recent_revoked.id
            active_id = active.id

            result = purge_parent_push_operational_data(session, now=self.now)
            session.commit()

            self.assertEqual(result.deleted_attempt_count, 1)
            self.assertEqual(result.redacted_subscription_count, 1)
            self.assertIsNone(session.get(ParentPushDeliveryAttempt, old_attempt_id))
            self.assertIsNotNone(session.get(ParentPushDeliveryAttempt, recent_attempt_id))
            redacted = session.get(ParentPushSubscription, old_revoked_id)
            self.assertTrue(redacted.endpoint.startswith("redacted:"))
            self.assertEqual(redacted.p256dh_key, "")
            self.assertEqual(redacted.auth_key, "")
            self.assertIsNone(redacted.device_label)
            self.assertIsNone(redacted.user_agent)
            self.assertIn(
                "recent-revoked",
                session.get(ParentPushSubscription, recent_revoked_id).endpoint,
            )
            self.assertIn(
                "active",
                session.get(ParentPushSubscription, active_id).endpoint,
            )

            second = purge_parent_push_operational_data(session, now=self.now)
            self.assertEqual(second.deleted_attempt_count, 0)
            self.assertEqual(second.redacted_subscription_count, 0)

    def test_retention_days_must_be_positive(self):
        with Session(self.engine) as session:
            with self.assertRaisesRegex(ValueError, "1日以上"):
                purge_parent_push_operational_data(
                    session,
                    now=self.now,
                    retention_days=0,
                )


if __name__ == "__main__":
    unittest.main()
