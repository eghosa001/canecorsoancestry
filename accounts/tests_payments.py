import hashlib
import hmac
import json
from unittest.mock import patch

from django.conf import settings

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import Dog, Kennel, KennelMembership, ModerationRoleAssignment, Submission
from registry.services import approve_submission

from .forms import PaymentPackageForm
from .models import PaymentSubmissionLink, SubmissionPayment
from .payments import PaystackError, record_successful_payment, webhook_signature_valid


class PaidSubmissionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="paid-kennel",
            email="owner@example.com",
            password="test-pass-123",
        )
        self.reviewer = get_user_model().objects.create_user(
            username="reviewer",
            password="test-pass-123",
        )
        ModerationRoleAssignment.objects.create(
            user=self.reviewer,
            role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.kennel = Kennel.objects.create(
            name="Paid Kennel",
            slug="paid-kennel",
            verified_at=timezone.now(),
        )
        KennelMembership.objects.create(
            kennel=self.kennel,
            user=self.user,
            role=KennelMembership.Role.OWNER,
        )

    def test_package_prices_and_multi_dog_limit(self):
        batch_form = PaymentPackageForm(
            {
                "kennel": self.kennel.pk,
                "package": SubmissionPayment.Package.MULTI_DOG,
                "dog_count": 6,
            },
            user=self.user,
        )
        self.assertTrue(batch_form.is_valid(), batch_form.errors)
        self.assertEqual(batch_form.cleaned_data["amount_kobo"], 150000)

        oversized_form = PaymentPackageForm(
            {
                "kennel": self.kennel.pk,
                "package": SubmissionPayment.Package.MULTI_DOG,
                "dog_count": 7,
            },
            user=self.user,
        )
        self.assertFalse(oversized_form.is_valid())

        litter_form = PaymentPackageForm(
            {
                "kennel": self.kennel.pk,
                "package": SubmissionPayment.Package.LITTER,
            },
            user=self.user,
        )
        self.assertTrue(litter_form.is_valid(), litter_form.errors)
        self.assertEqual(litter_form.cleaned_data["amount_kobo"], 100000)

    @patch("accounts.views.verify_transaction")
    def test_member_can_recheck_pending_payment_status(self, verify):
        payment = SubmissionPayment.objects.create(
            user=self.user,
            kennel=self.kennel,
            package=SubmissionPayment.Package.SINGLE_DOG,
            dog_count=1,
            amount_kobo=50000,
            reference="CCA-manual-verify",
            status=SubmissionPayment.Status.PENDING,
        )
        verify.return_value = {
            "id": 12345,
            "reference": payment.reference,
            "status": "success",
            "amount": 50000,
            "currency": "NGN",
            "metadata": {"payment_id": str(payment.pk)},
        }
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:payment-verify", args=[payment.pk])
        )

        self.assertRedirects(
            response,
            reverse("accounts:payment-detail", args=[payment.pk]),
            fetch_redirect_response=False,
        )
        payment.refresh_from_db()
        self.assertEqual(payment.status, SubmissionPayment.Status.PAID)
        self.assertIsNotNone(payment.paid_at)

        detail = self.client.get(reverse("accounts:payment-detail", args=[payment.pk]))
        self.assertContains(detail, "Payment confirmed — your package is ready.")
        self.assertContains(detail, "Submit dog")

    @patch("accounts.views.verify_transaction")
    def test_member_payment_recheck_keeps_unpaid_checkout_pending(self, verify):
        payment = SubmissionPayment.objects.create(
            user=self.user,
            kennel=self.kennel,
            package=SubmissionPayment.Package.SINGLE_DOG,
            dog_count=1,
            amount_kobo=50000,
            reference="CCA-still-pending",
            status=SubmissionPayment.Status.PENDING,
            authorization_url="https://checkout.paystack.com/still-pending",
        )
        verify.side_effect = PaystackError("Payment has not completed successfully.")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:payment-verify", args=[payment.pk]),
            follow=True,
        )

        payment.refresh_from_db()
        self.assertEqual(payment.status, SubmissionPayment.Status.PENDING)
        self.assertContains(response, "Payment has not completed successfully.")
        self.assertContains(response, "Already paid? Check payment status")

    def test_payment_start_fails_safely_without_paystack_configuration(self):
        self.client.force_login(self.user)
        with self.settings(PAYSTACK_SECRET_KEY=""):
            response = self.client.post(
                reverse("accounts:new-payment"),
                {
                    "kennel": self.kennel.pk,
                    "package": SubmissionPayment.Package.SINGLE_DOG,
                    "dog_count": 1,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paystack is not configured on the server yet.")
        self.assertContains(response, "₦1,500")
        self.assertContains(response, "₦1,000")
        self.assertEqual(SubmissionPayment.objects.filter(user=self.user).count(), 0)

    @patch("accounts.views.initialize_transaction")
    def test_payment_start_uses_same_origin_handoff_before_paystack(self, initialize):
        initialize.return_value = {
            "access_code": "test-access-code",
            "authorization_url": "https://checkout.paystack.com/test-access-code",
        }
        self.client.force_login(self.user)

        with self.settings(
            PAYSTACK_SECRET_KEY="sk_test_example",
            SITE_URL="https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev",
        ):
            response = self.client.post(
                reverse("accounts:new-payment"),
                {
                    "kennel": self.kennel.pk,
                    "package": SubmissionPayment.Package.SINGLE_DOG,
                    "dog_count": 1,
                },
            )

        payment = SubmissionPayment.objects.get(user=self.user)
        expected = f"{reverse('accounts:payment-detail', args=[payment.pk])}?checkout=1"
        self.assertRedirects(response, expected, fetch_redirect_response=False)
        initialize.assert_called_once()
        callback_url = initialize.call_args.args[1]
        self.assertEqual(
            callback_url,
            "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev"
            + reverse("accounts:paystack-callback"),
        )

        detail = self.client.get(expected)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Opening secure Paystack checkout")
        self.assertContains(detail, "data-paystack-checkout-link")
        self.assertContains(detail, "https://checkout.paystack.com/test-access-code")
        self.assertContains(detail, "window.location.replace")

    @patch("accounts.views.initialize_transaction")
    def test_retry_reuses_recent_pending_checkout_instead_of_creating_duplicates(self, initialize):
        existing = SubmissionPayment.objects.create(
            user=self.user,
            kennel=self.kennel,
            package=SubmissionPayment.Package.SINGLE_DOG,
            dog_count=1,
            amount_kobo=50000,
            reference="CCA-existing-pending",
            status=SubmissionPayment.Status.PENDING,
            access_code="existing-access",
            authorization_url="https://checkout.paystack.com/existing-access",
        )
        self.client.force_login(self.user)

        with self.settings(PAYSTACK_SECRET_KEY="sk_test_example"):
            response = self.client.post(
                reverse("accounts:new-payment"),
                {
                    "kennel": self.kennel.pk,
                    "package": SubmissionPayment.Package.SINGLE_DOG,
                    "dog_count": 1,
                },
            )

        expected = f"{reverse('accounts:payment-detail', args=[existing.pk])}?checkout=1"
        self.assertRedirects(response, expected, fetch_redirect_response=False)
        initialize.assert_not_called()
        self.assertEqual(SubmissionPayment.objects.filter(user=self.user).count(), 1)

    def test_outdated_pending_checkout_cannot_be_resumed(self):
        payment = SubmissionPayment.objects.create(
            user=self.user,
            kennel=self.kennel,
            package=SubmissionPayment.Package.MULTI_DOG,
            dog_count=4,
            amount_kobo=100000,
            reference="CCA-retired-price",
            status=SubmissionPayment.Status.PENDING,
            access_code="retired-access",
            authorization_url="https://checkout.paystack.com/retired-access",
        )
        self.client.force_login(self.user)

        response = self.client.get(
            f"{reverse('accounts:payment-detail', args=[payment.pk])}?checkout=1"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This checkout uses retired pricing.")
        self.assertContains(response, "₦1500")
        self.assertNotContains(response, 'data-paystack-checkout-link')
        self.assertNotContains(response, "window.location.replace")

    def test_payment_start_shows_immediate_checkout_feedback(self):
        self.client.force_login(self.user)
        with self.settings(PAYSTACK_SECRET_KEY="sk_test_example"):
            response = self.client.get(reverse("accounts:new-payment"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-paystack-start-form")
        self.assertContains(response, "data-paystack-start-submit")
        self.assertContains(response, "Starting secure Paystack checkout")
        self.assertContains(response, "Opening Paystack…")

    def test_site_uses_lagos_timezone_for_displayed_payment_times(self):
        self.assertEqual(settings.TIME_ZONE, "Africa/Lagos")

    def test_paid_submission_cannot_be_approved_without_paid_link(self):
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=self.user,
            kennel=self.kennel,
            payload={
                "_paid_submission": True,
                "name": "Pending Dog",
                "sex": Dog.Sex.MALE,
            },
        )
        with self.assertRaisesRegex(ValueError, "paid Paystack"):
            approve_submission(submission, self.reviewer)

    def test_paid_dog_is_published_only_after_payment_and_admin_approval(self):
        payment = SubmissionPayment.objects.create(
            user=self.user,
            kennel=self.kennel,
            package=SubmissionPayment.Package.SINGLE_DOG,
            dog_count=1,
            amount_kobo=50000,
            reference="CCA-paid-test",
            status=SubmissionPayment.Status.PAID,
            paid_at=timezone.now(),
        )
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=self.user,
            kennel=self.kennel,
            payload={
                "_paid_submission": True,
                "name": "Verified Dog",
                "sex": Dog.Sex.MALE,
            },
        )
        PaymentSubmissionLink.objects.create(
            payment=payment,
            submission=submission,
            slot_kind=PaymentSubmissionLink.SlotKind.DOG,
        )

        approve_submission(submission, self.reviewer)
        submission.refresh_from_db()
        dog = Dog.objects.get(name="Verified Dog")
        self.assertTrue(dog.is_public)
        self.assertEqual(submission.status, Submission.Status.APPROVED)

    def test_paystack_amount_is_verified(self):
        payment = SubmissionPayment.objects.create(
            user=self.user,
            kennel=self.kennel,
            package=SubmissionPayment.Package.SINGLE_DOG,
            dog_count=1,
            amount_kobo=50000,
            reference="CCA-verify-test",
        )
        with self.assertRaisesRegex(PaystackError, "amount mismatch"):
            record_successful_payment(
                payment.reference,
                {
                    "reference": payment.reference,
                    "status": "success",
                    "amount": 1000,
                    "currency": "NGN",
                },
            )

    def test_webhook_signature_uses_paystack_secret(self):
        body = b'{"event":"charge.success"}'
        secret = "test-secret"
        with self.settings(PAYSTACK_SECRET_KEY=secret):
            signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
            self.assertTrue(webhook_signature_valid(body, signature))
            self.assertFalse(webhook_signature_valid(body, "bad"))

    def test_signed_webhook_confirms_once_and_rejects_forgery(self):
        payment = SubmissionPayment.objects.create(
            user=self.user, kennel=self.kennel,
            package=SubmissionPayment.Package.SINGLE_DOG,
            dog_count=1, amount_kobo=50000,
            reference="CCA-signed-event",
            status=SubmissionPayment.Status.PENDING,
        )
        event = {"event": "charge.success", "data": {
            "id": 34567, "reference": payment.reference, "status": "success",
            "amount": 50000, "currency": "NGN",
            "metadata": {"payment_id": str(payment.pk)},
        }}
        body = json.dumps(event).encode()
        secret = "sk_test_webhook_signing"
        signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
        url = reverse("accounts:paystack-webhook")

        with self.settings(PAYSTACK_SECRET_KEY=secret):
            invalid = self.client.post(
                url, body, content_type="application/json",
                HTTP_X_PAYSTACK_SIGNATURE="forged-signature",
            )
            payment.refresh_from_db()
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(payment.status, SubmissionPayment.Status.PENDING)

            accepted = self.client.post(
                url, body, content_type="application/json",
                HTTP_X_PAYSTACK_SIGNATURE=signature,
            )
            payment.refresh_from_db()
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(payment.status, SubmissionPayment.Status.PAID)
            first_paid_at = payment.paid_at

            replay = self.client.post(
                url, body, content_type="application/json",
                HTTP_X_PAYSTACK_SIGNATURE=signature,
            )
            payment.refresh_from_db()
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(payment.paid_at, first_paid_at)

    def test_signed_webhook_does_not_accept_wrong_amount(self):
        payment = SubmissionPayment.objects.create(
            user=self.user, kennel=self.kennel,
            package=SubmissionPayment.Package.SINGLE_DOG,
            dog_count=1, amount_kobo=50000,
            reference="CCA-wrong-webhook-amount",
            status=SubmissionPayment.Status.PENDING,
        )
        event = {"event": "charge.success", "data": {
            "id": 9876, "reference": payment.reference,
            "status": "success", "amount": 1000, "currency": "NGN",
        }}
        body = json.dumps(event).encode()
        secret = "sk_test_webhook_signing"
        signature = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
        with self.settings(PAYSTACK_SECRET_KEY=secret):
            response = self.client.post(
                reverse("accounts:paystack-webhook"), body,
                content_type="application/json",
                HTTP_X_PAYSTACK_SIGNATURE=signature,
            )
        payment.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payment.status, SubmissionPayment.Status.PENDING)
