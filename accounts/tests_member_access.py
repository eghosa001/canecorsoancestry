from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import Dog, DogImage, Kennel, KennelMembership, Submission

from .models import PaymentSubmissionLink, SubmissionPayment
from registry.services import approve_submission


class MemberAccessFlowTests(TestCase):
    def setUp(self):
        self.reviewer = get_user_model().objects.create_user(
            username="reviewer", is_staff=True
        )

    def test_signup_uses_kennel_identity_and_email_login(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "kennel_name": "New Member Kennels",
                "email": "member@example.com",
                "password1": "Strong-pass-12345",
                "password2": "Strong-pass-12345",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        user = get_user_model().objects.get(email="member@example.com")
        self.assertEqual(user.username, "new-member-kennels")
        self.assertEqual(user.profile.display_name, "New Member Kennels")
        self.assertTrue(
            Submission.objects.filter(
                submitted_by=user,
                kind=Submission.Kind.KENNEL_CREATE,
                status=Submission.Status.PENDING,
            ).exists()
        )

        self.client.logout()
        login_response = self.client.post(
            reverse("login"),
            {"username": "member@example.com", "password": "Strong-pass-12345"},
        )
        self.assertRedirects(login_response, reverse("dashboard"))

    def test_paid_dog_is_private_until_admin_approval_then_member_can_view_pedigree(self):
        member = get_user_model().objects.create_user(
            username="dog-member",
            email="dog-member@example.com",
            password="test-pass-123",
        )
        kennel = Kennel.objects.create(
            name="Verified Member Kennel",
            slug="verified-member-kennel",
            verified_at=timezone.now(),
        )
        KennelMembership.objects.create(
            user=member,
            kennel=kennel,
            role=KennelMembership.Role.OWNER,
        )
        payment = SubmissionPayment.objects.create(
            user=member,
            kennel=kennel,
            package=SubmissionPayment.Package.SINGLE_DOG,
            dog_count=1,
            amount_kobo=50000,
            reference="CCA-member-access",
            status=SubmissionPayment.Status.PAID,
            paid_at=timezone.now(),
        )
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=member,
            kennel=kennel,
            payload={
                "_paid_submission": True,
                "name": "Member Dog",
                "sex": Dog.Sex.MALE,
            },
        )
        PaymentSubmissionLink.objects.create(
            payment=payment,
            submission=submission,
            slot_kind=PaymentSubmissionLink.SlotKind.DOG,
        )

        self.assertFalse(Dog.objects.filter(name="Member Dog").exists())
        self.assertEqual(submission.status, Submission.Status.PENDING)

        approve_submission(submission, self.reviewer, "Facts checked.")
        submission.refresh_from_db()
        self.assertTrue(submission.dog.is_public)

        self.client.force_login(member)
        pedigree = self.client.get(
            reverse("accounts:member-pedigree", args=[submission.dog.pk])
        )
        self.assertContains(pedigree, "Member Dog")


class PopularDogTests(TestCase):
    def test_homepage_uses_search_originated_popularity(self):
        kennel = Kennel.objects.create(name="Popular Kennel", slug="popular-kennel")
        popular = Dog.objects.create(
            name="Popular Dog", slug="popular-dog", kennel=kennel, is_public=True
        )
        same_kennel = Dog.objects.create(
            name="Second Kennel Dog",
            slug="second-kennel-dog",
            kennel=kennel,
            is_public=True,
        )
        DogImage.objects.create(
            dog=popular,
            image="dogs/popular-dog.jpg",
            is_primary=True,
        )
        DogImage.objects.create(
            dog=same_kennel,
            image="dogs/second-kennel-dog.jpg",
            is_primary=True,
        )

        self.client.get(
            reverse("registry:dog-detail", args=[popular.slug]),
            {"source": "search"},
        )
        popular.refresh_from_db()
        self.assertEqual(popular.search_count, 1)

        featured = list(self.client.get(reverse("home")).context["featured_dogs"])
        self.assertEqual(featured[0], popular)
        self.assertNotIn(same_kennel, featured)
