"""Live Paystack authentication probe is read-only, private and fail-closed."""
import io
import json
from unittest import TestCase

from scripts.check_paystack_transport import PaymentTransportError, check_paystack_transport


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.body = io.StringIO(json.dumps(payload))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.body.close()

    def read(self, *args):
        return self.body.read(*args)


class PaystackHealthTests(TestCase):
    KEY = "sk_live_test_only_not_a_real_key"

    def test_never_uses_a_mutating_request(self):
        called = []

        def opener(request, timeout):
            called.append(request)
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.full_url, "https://api.paystack.co/balance")
            self.assertEqual(timeout, 12)
            return FakeResponse({
                "status": True,
                "data": [{"currency": "NGN", "balance": 800000}],
            })

        check_paystack_transport(
            secret_key=self.KEY,
            base_url="https://api.paystack.co",
            opener=opener,
        )
        self.assertEqual(len(called), 1)

    def test_missing_or_test_key_is_not_production_ready(self):
        for key in ("", "sk_test_somekey", "pk_live_public", "unsafe"):
            with self.subTest(key=key), self.assertRaises(PaymentTransportError):
                check_paystack_transport(
                    secret_key=key, base_url="https://api.paystack.co",
                    opener=lambda *_args, **_kwargs: self.fail("Network should not run"),
                )

    def test_rejects_endpoint_redirect_targets_or_custom_hosts(self):
        for url in (
            "http://api.paystack.co",
            "https://api.paystack.co.evil.test",
            "https://user:pass@api.paystack.co",
            "https://api.paystack.co/transaction/initialize",
            "https://api.paystack.co:444",
        ):
            with self.subTest(url=url), self.assertRaises(PaymentTransportError):
                check_paystack_transport(
                    secret_key=self.KEY, base_url=url,
                    opener=lambda *_args, **_kwargs: self.fail("Network should not run"),
                )

    def test_rejected_authorization_is_not_reported_as_success(self):
        def opener(_request, timeout):
            return FakeResponse({"status": False, "message": "Private account message", "data": []})
        with self.assertRaises(PaymentTransportError) as ctx:
            check_paystack_transport(
                secret_key=self.KEY, base_url="https://api.paystack.co", opener=opener,
            )
        self.assertNotIn("Private account message", str(ctx.exception))
