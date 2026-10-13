"""Change-scoped checkout and privacy regression tests."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from registry.models import Kennel, KennelMembership, Dog, Submission, ModerationRoleAssignment
from registry.services import approve_submission
from .models import PaymentSubmissionLink, SubmissionPayment


class DogDraftListingTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="draft-owner", email="draft@example.com", password="pass12345",
        )
        self.other = get_user_model().objects.create_user(
            username="draft-other", email="other@example.com", password="pass12345",
        )
        self.kennel = Kennel.objects.create(
            name="Verified Draft Kennel", slug="verified-draft-kennel",
            verified_at=timezone.now(),
        )
        KennelMembership.objects.create(
            user=self.owner, kennel=self.kennel, role=KennelMembership.Role.OWNER,
        )
        self.client.force_login(self.owner)

    def _draft(self):
        return Submission.objects.create(
            submitted_by=self.owner, kennel=self.kennel,
            kind=Submission.Kind.DOG,
            payload={"_paid_submission": True, "name": "Not Yet Paid", "sex": Dog.Sex.MALE},
        )

    @patch("accounts.dog_drafts.verify_submission")
    def test_create_private_submission_without_dog_or_payment(self, _check):
        response = self.client.post(reverse("accounts:submit-dog"), {
            "kennel": str(self.kennel.pk), "name": "New Nigerian Dog", "sex": Dog.Sex.MALE,
        })
        self.assertEqual(response.status_code, 302)
        draft = Submission.objects.get(payload__name="New Nigerian Dog")
        self.assertEqual(draft.status, Submission.Status.PENDING)
        self.assertFalse(Dog.objects.filter(name="New Nigerian Dog").exists())
        self.assertFalse(PaymentSubmissionLink.objects.filter(submission=draft).exists())
        self.assertContains(self.client.get(reverse("accounts:submissions")), "Pay ₦500 to list")

    @override_settings(PAYSTACK_SECRET_KEY="test-paystack", SITE_URL="https://example.com")
    @patch("accounts.dog_drafts.initialize_transaction")
    def test_checkout_links_exact_draft_once(self, initialize):
        initialize.return_value = {
            "authorization_url": "https://checkout.paystack.com/test",
            "access_code": "access-123",
        }
        draft = self._draft()
        url = reverse("accounts:draft-checkout", args=[draft.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        link = PaymentSubmissionLink.objects.get(submission=draft)
        self.assertEqual(link.payment.amount_kobo, 50000)
        self.assertEqual(link.payment.status, SubmissionPayment.Status.PENDING)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(PaymentSubmissionLink.objects.filter(submission=draft).count(), 1)
        self.assertEqual(initialize.call_count, 1)

    def test_cannot_approve_unpaid_draft_or_view_other_members_checkout(self):
        draft = self._draft()
        reviewer = get_user_model().objects.create_user(username="draft-reviewer", password="pass12345")
        ModerationRoleAssignment.objects.create(
            user=reviewer, role=ModerationRoleAssignment.Role.REVIEWER,
        )
        with self.assertRaisesRegex(ValueError, "paid Paystack"):
            approve_submission(draft, reviewer)
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(reverse("accounts:draft-checkout", args=[draft.pk])).status_code,
            404,
        )

    def test_archive_bootstrap_reserves_private_unverified_kennels(self):
        from django.core.management import call_command
        call_command("bootstrap_nigerian_kennel_archives", verbosity=0)
        call_command("bootstrap_nigerian_kennel_archives", verbosity=0)
        for name in ("Pet Palace Kennels", "Ofreelife Kennels"):
            kennel = Kennel.objects.get(name=name)
            self.assertFalse(kennel.is_public)
            self.assertIsNone(kennel.verified_at)
            self.assertFalse(kennel.memberships.exists())
            self.assertFalse(kennel.dogs.exists())
