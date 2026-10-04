import hashlib
import hmac

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from registry.models import Dog, Kennel, KennelMembership, Submission
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
            is_staff=True,
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
        form = PaymentPackageForm(
            {
                "kennel": self.kennel.pk,
                "package": SubmissionPayment.Package.MULTI_DOG,
                "dog_count": 4,
            },
            user=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["amount_kobo"], 150000)
        self.assertEqual(
            SubmissionPayment.price_for(SubmissionPayment.Package.LITTER, 0),
            20000,
        )

        too_many = PaymentPackageForm(
            {
                "kennel": self.kennel.pk,
                "package": SubmissionPayment.Package.MULTI_DOG,
                "dog_count": 5,
            },
            user=self.user,
        )
        self.assertFalse(too_many.is_valid())

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
