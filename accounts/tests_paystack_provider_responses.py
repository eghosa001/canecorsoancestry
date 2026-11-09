"""Untrusted Paystack API JSON must not create 500s or offsite checkouts."""
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from accounts.payments import PaystackError, initialize_transaction, verify_transaction


class PaystackProviderResponseTests(SimpleTestCase):
    def payment(self):
        user = Mock(email="member@example.test", pk="user-one")
        kennel = Mock(pk="kennel-one")
        return Mock(
            user=user, kennel=kennel, pk="payment-one",
            user_id="user-one", kennel_id="kennel-one",
            package="single_dog", amount_kobo=50000, currency="NGN",
            reference="CCA-test-valid-reference",
        )

    def response(self, body):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = body
        return response

    @patch("accounts.payments.requests.post")
    def test_malformed_checkout_responses_are_rejected(self, post):
        with self.settings(PAYSTACK_SECRET_KEY="sk_test_demo"):
            for body in ([], "bad", 5, None, {"status": True, "data": []},
                         {"status": True, "data": {"access_code": []}},
                         {"status": False, "message": "Secret provider error"}):
                with self.subTest(body=body):
                    post.return_value = self.response(body)
                    with self.assertRaises(PaystackError):
                        initialize_transaction(self.payment(), "https://example.test/callback")

    @patch("accounts.payments.requests.post")
    def test_checkout_rejects_external_http_and_spoofed_paystack_urls(self, post):
        with self.settings(PAYSTACK_SECRET_KEY="sk_test_demo"):
            for url in (
                "http://checkout.paystack.com/abc",
                "https://checkout.paystack.com.evil.test/abc",
                "https://evil.test/abc",
                "https://user:pass@checkout.paystack.com/abc",
                "https://checkout.paystack.com:8443/abc",
                "//checkout.paystack.com/abc",
                "https://checkout.paystack.com",
            ):
                post.return_value = self.response({
                    "status": True,
                    "data": {"authorization_url": url, "access_code": "access-test"},
                })
                with self.subTest(url=url), self.assertRaises(PaystackError):
                    initialize_transaction(self.payment(), "https://example.test/callback")

    @patch("accounts.payments.requests.post")
    def test_valid_checkout_is_unchanged(self, post):
        data = {
            "authorization_url": "https://checkout.paystack.com/secure-test",
            "access_code": "code-123",
        }
        post.return_value = self.response({"status": True, "data": data})
        with self.settings(PAYSTACK_SECRET_KEY="sk_test_demo"):
            self.assertEqual(
                initialize_transaction(self.payment(), "https://example.test/callback"),
                data,
            )
        self.assertEqual(post.call_args.kwargs["json"]["amount"], "50000")

    @patch("accounts.payments.requests.get")
    def test_verification_bad_json_shape_returns_payment_error(self, get):
        with self.settings(PAYSTACK_SECRET_KEY="sk_test_demo"):
            for body in ([], 5, None, "bad", {"status": True, "data": []},
                         {"status": False, "message": "Sensitive provider response"}):
                get.return_value = self.response(body)
                with self.subTest(body=body), self.assertRaises(PaystackError) as error:
                    verify_transaction("CCA-example-reference")
                self.assertNotIn("Sensitive provider response", str(error.exception))

    @patch("accounts.payments.requests.get")
    def test_valid_verified_payment_response_is_unchanged(self, get):
        data = {"reference": "CCA-example-reference", "amount": 50000, "status": "success"}
        get.return_value = self.response({"status": True, "data": data})
        with self.settings(PAYSTACK_SECRET_KEY="sk_test_demo"):
            self.assertEqual(verify_transaction("CCA-example-reference"), data)
