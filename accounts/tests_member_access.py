from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, DogImage, Submission
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

    def test_dog_is_private_until_admin_approval_then_member_can_view_pedigree(self):
        member = get_user_model().objects.create_user(
            username="dog-member", password="test-pass-123"
        )
        self.client.force_login(member)

        response = self.client.post(
            reverse("accounts:submit-dog"),
            {"name": "Member Dog", "sex": Dog.Sex.MALE},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Dog.objects.filter(name="Member Dog").exists())
        submission = Submission.objects.get(
            kind=Submission.Kind.DOG, submitted_by=member
        )
        self.assertEqual(submission.status, Submission.Status.PENDING)

        approve_submission(submission, self.reviewer, "Facts checked.")
        submission.refresh_from_db()
        self.assertTrue(submission.dog.is_public)
        pedigree = self.client.get(
            reverse("accounts:member-pedigree", args=[submission.dog.pk])
        )
        self.assertContains(pedigree, "Member Dog")


class PopularDogTests(TestCase):
    def test_homepage_uses_search_originated_popularity(self):
        popular = Dog.objects.create(
            name="Popular Dog", slug="popular-dog", is_public=True
        )
        DogImage.objects.create(
            dog=popular,
            image="dogs/popular-dog.jpg",
            is_primary=True,
        )
        Dog.objects.create(name="Other Dog", slug="other-dog", is_public=True)

        self.client.get(
            reverse("registry:dog-detail", args=[popular.slug]),
            {"source": "search"},
        )
        popular.refresh_from_db()
        self.assertEqual(popular.search_count, 1)

        featured = list(self.client.get(reverse("home")).context["featured_dogs"])
        self.assertEqual(featured[0], popular)
