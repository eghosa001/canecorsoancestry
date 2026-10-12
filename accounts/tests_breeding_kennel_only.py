"""Only the verified breeding kennel appears publicly; buyers remain private."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.forms import DogSubmissionForm
from accounts.models import PaymentSubmissionLink, SubmissionPayment
from registry.models import Dog, Kennel, KennelMembership, ModerationRoleAssignment, Submission
from registry.services import approve_submission


class BreedingKennelOnlyTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user(
            username="pet-palace-buyer", email="buyer@example.com", password="test-password"
        )
        self.staff = User.objects.create_user(username="breeder-reviewer")
        ModerationRoleAssignment.objects.create(
            user=self.staff, role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.buyer_kennel = Kennel.objects.create(
            name="Pet Palace", slug="pet-palace",
            is_public=True, verified_at=timezone.now(),
        )
        self.breeder_kennel = Kennel.objects.create(
            name="Custodinus", slug="custodinus", is_public=True,
        )
        KennelMembership.objects.create(
            user=self.member, kennel=self.buyer_kennel, role=KennelMembership.Role.OWNER,
        )
        self.payment = SubmissionPayment.objects.create(
            user=self.member, kennel=self.buyer_kennel,
            package=SubmissionPayment.Package.SINGLE_DOG,
            dog_count=1, amount_kobo=50000,
            reference="CCA-BREEDER-TEST", status=SubmissionPayment.Status.PAID,
            paid_at=timezone.now(),
        )

    def submit_paid_dog(self, kennel_value, *, name="Agatha Custodinus"):
        self.client.force_login(self.member)
        data = {
            "name": name, "sex": Dog.Sex.FEMALE,
            "breeding_kennel": kennel_value,
            "notes": "Verified historical breeding kennel and pedigree",
        }
        response = self.client.post(
            reverse("accounts:payment-submit-dog", args=[self.payment.pk]), data
        )
        self.assertEqual(response.status_code, 302)
        submission = Submission.objects.get(
            kind=Submission.Kind.DOG, submitted_by=self.member
        )
        self.assertEqual(submission.kennel_id, self.buyer_kennel.pk)
        self.assertIn("breeding_kennel_id", submission.payload)
        self.assertFalse(Dog.objects.filter(name=name).exists())
        approve_submission(submission, self.staff)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.APPROVED)
        return submission.dog

    def test_purchased_dog_keeps_breeding_kennel_and_original_registered_name(self):
        dog = self.submit_paid_dog(str(self.breeder_kennel.pk))
        self.assertEqual(dog.name, "Agatha Custodinus")
        self.assertEqual(dog.kennel_id, self.breeder_kennel.pk)
        self.assertNotEqual(dog.kennel_id, self.buyer_kennel.pk)
        # The public profile must not expose a buyer as the dog's owner;
        # a signed-in member's own navbar may still show their kennel.
        self.client.logout()
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Breeding kennel")
        self.assertContains(response, "Custodinus")
        self.assertContains(response, f'/kennels/{self.breeder_kennel.slug}/')
        self.assertNotContains(response, "Current owner")
        self.assertNotContains(response, "Pet Palace")
        directory = self.client.get(reverse("registry:kennel-list"))
        rows = {x.slug: x.public_dog_count for x in directory.context["kennels"]}
        self.assertEqual(rows[self.breeder_kennel.slug], 1)
        self.assertEqual(rows[self.buyer_kennel.slug], 0)
        # The buyer can still access the dog through their approved submission.
        self.client.force_login(self.member)
        own_workspace = self.client.get(reverse("accounts:my-pedigrees"))
        self.assertEqual(own_workspace.status_code, 200)
        self.assertContains(own_workspace, "Agatha Custodinus")

    def test_unregistered_breeder_leaves_kennel_field_blank_not_buyer_kennel(self):
        dog = self.submit_paid_dog("", name="Unregistered Breeder Dog")
        self.assertIsNone(dog.kennel_id)
        # The public profile must not expose a buyer as the dog's owner;
        # a signed-in member's own navbar may still show their kennel.
        self.client.logout()
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<dt>Breeding kennel</dt>", html=False)
        self.assertNotContains(response, "Pet Palace")
        self.assertNotContains(response, "Current owner")
        self.client.force_login(self.member)
        self.assertContains(self.client.get(reverse("accounts:my-pedigrees")), dog.name)

    def test_form_labels_and_optional_breeding_kennel_are_distinct(self):
        form = DogSubmissionForm(user=self.member, kennel=self.buyer_kennel)
        self.assertTrue(form.fields["kennel"].disabled)
        self.assertEqual(form.fields["breeding_kennel"].label, "Breeding kennel (origin)")
        self.assertFalse(form.fields["breeding_kennel"].required)
        self.assertIn("the kennel that originally bred", form.fields["breeding_kennel"].help_text.lower())
        self.assertIn(self.breeder_kennel, form.fields["breeding_kennel"].queryset)
        self.assertEqual(form.fields["breeding_kennel"].initial, self.buyer_kennel)

    def test_cannot_select_private_or_nonexistent_breeding_kennel(self):
        private = Kennel.objects.create(name="Private Breeder", slug="private-breeder", is_public=False)
        for value in (str(private.pk), "12345678-1234-1234-1234-123456789012"):
            form = DogSubmissionForm(
                {"name": "Example Dog", "sex": Dog.Sex.MALE, "breeding_kennel": value},
                user=self.member, kennel=self.buyer_kennel,
            )
            self.assertFalse(form.is_valid())
            self.assertIn("breeding_kennel", form.errors)

    def test_legacy_paid_dog_submission_keeps_original_breeder_compatibility(self):
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=self.member, kennel=self.buyer_kennel,
            payload={"_paid_submission": True, "name": "Original Bred Dog", "sex": Dog.Sex.MALE},
        )
        PaymentSubmissionLink.objects.create(
            payment=self.payment, submission=submission,
            slot_kind=PaymentSubmissionLink.SlotKind.DOG,
        )
        approve_submission(submission, self.staff)
        submission.refresh_from_db()
        self.assertEqual(submission.dog.kennel_id, self.buyer_kennel.pk)
