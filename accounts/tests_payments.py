import hashlib
import hmac

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
                "dog_count": 4,
            },
            user=self.user,
        )
        self.assertTrue(batch_form.is_valid(), batch_form.errors)
        self.assertEqual(batch_form.cleaned_data["amount_kobo"], 150000)

        oversized_form = PaymentPackageForm(
            {
                "kennel": self.kennel.pk,
                "package": SubmissionPayment.Package.MULTI_DOG,
                "dog_count": 5,
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
        self.assertContains(response, "₦1,000")
        self.assertEqual(SubmissionPayment.objects.filter(user=self.user).count(), 0)

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
