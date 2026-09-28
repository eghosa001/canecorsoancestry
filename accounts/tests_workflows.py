from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import (
    Dog,
    Kennel,
    KennelMembership,
    Submission,
    VerificationEvent,
    VerificationState,
)


class MemberSubmissionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="member", password="test-pass-123"
        )
        self.kennel = Kennel.objects.create(name="Member Kennel", slug="member-kennel")
        KennelMembership.objects.create(
            user=self.user,
            kennel=self.kennel,
            role=KennelMembership.Role.CONTRIBUTOR,
        )

    def test_member_can_submit_dog_to_linked_kennel(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:submit-dog"),
            {
                "name": "Submitted Dog",
                "sex": Dog.Sex.MALE,
                "kennel": str(self.kennel.pk),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Submission.objects.filter(
                submitted_by=self.user,
                kennel=self.kennel,
                kind=Submission.Kind.DOG,
                status=Submission.Status.PENDING,
            ).exists()
        )

    def test_nonmember_cannot_submit_correction(self):
        dog = Dog.objects.create(
            name="Protected Dog",
            slug="protected-dog",
            kennel=self.kennel,
        )
        outsider = get_user_model().objects.create_user(username="outsider")
        self.client.force_login(outsider)

        response = self.client.get(
            reverse("accounts:submit-correction", args=[dog.pk])
        )

        self.assertEqual(response.status_code, 403)


class ModeratorVerificationTests(TestCase):
    def test_staff_can_record_overall_verification(self):
        staff = get_user_model().objects.create_user(
            username="reviewer", is_staff=True
        )
        dog = Dog.objects.create(name="Review Dog", slug="review-dog")
        self.client.force_login(staff)

        response = self.client.post(
            reverse("accounts:verify-dog"),
            {
                "dog": str(dog.pk),
                "field_name": "",
                "state": VerificationState.IDENTITY_REVIEWED,
                "note": "Identity checked.",
            },
        )

        self.assertEqual(response.status_code, 302)
        dog.refresh_from_db()
        self.assertEqual(dog.verification_state, VerificationState.IDENTITY_REVIEWED)
        self.assertTrue(
            VerificationEvent.objects.filter(
                dog=dog, reviewer=staff, state=VerificationState.IDENTITY_REVIEWED
            ).exists()
        )
