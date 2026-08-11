import json
import unittest

from pywebpush import WebPushException

from models import (
    ParentPushDeliveryAttemptResult,
    ParentPushSubscription,
)
from parent_push_service import (
    SAFE_PUSH_BODY,
    SAFE_PUSH_TITLE,
    WebPushParentPushTransport,
    classify_web_push_response,
)


class FakeResponse:
    def __init__(self, status_code, *, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = "provider response must not be persisted"


class ParentWebPushTransportTests(unittest.TestCase):
    def setUp(self):
        self.subscription = ParentPushSubscription(
            parent_account_id=1,
            endpoint="https://push.example.test/private-endpoint",
            endpoint_hash="hash",
            p256dh_key="private-p256dh",
            auth_key="private-auth",
            environment="development",
            is_test_device=True,
        )
        self.payload = {
            "schema_version": 1,
            "notification_id": 10,
            "target_id": 20,
            "kind": "attendance_confirmation_request",
            "title": SAFE_PUSH_TITLE,
            "body": SAFE_PUSH_BODY,
            "action_url": "/parent-portal/notifications/10",
            "shown_receipt_token": "shown-token",
            "clicked_receipt_token": "clicked-token",
            "expires_at": None,
        }

    def test_transport_passes_encrypted_webpush_inputs_and_accepts_success(self):
        calls = []

        def sender(**kwargs):
            calls.append(kwargs)
            return FakeResponse(201, headers={"X-Request-Id": "request-123"})

        transport = WebPushParentPushTransport(
            vapid_private_key="private-vapid-key",
            vapid_subject="mailto:developer@example.com",
            sender=sender,
        )

        result = transport.send(
            subscription=self.subscription,
            payload=self.payload,
        )

        self.assertEqual(result.result, ParentPushDeliveryAttemptResult.accepted)
        self.assertEqual(result.provider_status_code, 201)
        self.assertEqual(result.provider_request_id, "request-123")
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call["content_encoding"], "aes128gcm")
        self.assertEqual(call["timeout"], 10)
        self.assertEqual(call["vapid_claims"], {"sub": "mailto:developer@example.com"})
        self.assertEqual(call["subscription_info"]["endpoint"], self.subscription.endpoint)
        self.assertEqual(call["subscription_info"]["keys"]["p256dh"], "private-p256dh")
        self.assertEqual(json.loads(call["data"]), self.payload)

    def test_webpush_exception_is_classified_without_provider_body(self):
        def sender(**kwargs):
            del kwargs
            raise WebPushException(
                "provider included a private endpoint",
                response=FakeResponse(410),
            )

        transport = WebPushParentPushTransport(
            vapid_private_key="private-vapid-key",
            vapid_subject="mailto:developer@example.com",
            sender=sender,
        )

        result = transport.send(
            subscription=self.subscription,
            payload=self.payload,
        )

        self.assertEqual(result.result, ParentPushDeliveryAttemptResult.terminal_failed)
        self.assertEqual(result.error_code, "subscription_gone")
        self.assertNotIn(self.subscription.endpoint, result.error_message)
        self.assertNotIn("provider response", result.error_message)

    def test_provider_status_classification(self):
        cases = {
            202: (ParentPushDeliveryAttemptResult.accepted, None),
            404: (ParentPushDeliveryAttemptResult.terminal_failed, "subscription_gone"),
            410: (ParentPushDeliveryAttemptResult.terminal_failed, "subscription_gone"),
            429: (ParentPushDeliveryAttemptResult.retryable_failed, "rate_limited"),
            500: (ParentPushDeliveryAttemptResult.retryable_failed, "provider_unavailable"),
            503: (ParentPushDeliveryAttemptResult.retryable_failed, "provider_unavailable"),
            400: (ParentPushDeliveryAttemptResult.terminal_failed, "provider_rejected"),
            403: (ParentPushDeliveryAttemptResult.terminal_failed, "provider_rejected"),
            413: (ParentPushDeliveryAttemptResult.terminal_failed, "payload_too_large"),
        }
        for status_code, expected in cases.items():
            with self.subTest(status_code=status_code):
                result = classify_web_push_response(status_code)
                self.assertEqual((result.result, result.error_code), expected)

        missing_response = classify_web_push_response(None)
        self.assertEqual(
            missing_response.result,
            ParentPushDeliveryAttemptResult.retryable_failed,
        )
        self.assertEqual(missing_response.error_code, "transport_unavailable")


if __name__ == "__main__":
    unittest.main()
