"""Webhook ingress rejects bad signed JSON before processing any payment."""
import hashlib
import hmac
import json

from django.test import SimpleTestCase
from django.urls import reverse


class PaystackWebhookIngressTests(SimpleTestCase):
    SECRET = "test-webhook-hmac-ingress-secret"

    def signed_request(self, event):
        raw = json.dumps(event).encode("utf-8")
        signature = hmac.new(
            self.SECRET.encode("utf-8"), raw, hashlib.sha512,
        ).hexdigest()
        with self.settings(PAYSTACK_SECRET_KEY=self.SECRET):
            return self.client.post(
                reverse("accounts:paystack-webhook"),
                data=raw, content_type="application/json",
                HTTP_X_PAYSTACK_SIGNATURE=signature,
            )

    def test_validly_signed_non_object_json_is_bad_request_not_server_error(self):
        for event in ([], ["charge.success"], None, 2, "hello"):
            with self.subTest(event=event):
                self.assertEqual(self.signed_request(event).status_code, 400)

    def test_validly_signed_charge_with_wrong_data_type_is_bad_request(self):
        for data in (None, [], "reference", 123, True):
            with self.subTest(data=data):
                response = self.signed_request({"event": "charge.success", "data": data})
                self.assertEqual(response.status_code, 400)

    def test_invalid_reference_is_rejected_before_any_database_query(self):
        for reference in (None, 12, True, [], {}, "", "x" * 81):
            with self.subTest(reference=reference):
                response = self.signed_request({
                    "event": "charge.success",
                    "data": {"reference": reference},
                })
                self.assertEqual(response.status_code, 400)

    def test_rejects_oversized_payload_before_signature_validation(self):
        raw = json.dumps({"event": "charge.success", "data": {"message": "x" * 262200}}).encode()
        with self.settings(PAYSTACK_SECRET_KEY=self.SECRET):
            response = self.client.post(
                reverse("accounts:paystack-webhook"),
                data=raw, content_type="application/json",
                HTTP_X_PAYSTACK_SIGNATURE="invalid",
            )
        self.assertEqual(response.status_code, 413)

    def test_unsigned_webhooks_are_never_accepted(self):
        response = self.client.post(
            reverse("accounts:paystack-webhook"),
            data=b'{"event":"charge.success"}', content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
