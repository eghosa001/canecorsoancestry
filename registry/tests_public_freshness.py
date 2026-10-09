"""Regression: a committed moderation approval is visible on the next request."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, Kennel, ModerationRoleAssignment, Submission
from registry.services import approve_submission


class ApprovedChangesAppearImmediatelyTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.reviewer = User.objects.create_user(username="fresh-reviewer")
        ModerationRoleAssignment.objects.create(
            user=self.reviewer, role=ModerationRoleAssignment.Role.REVIEWER
        )
        self.member = User.objects.create_user(username="fresh-member")
        self.kennel = Kennel.objects.create(
            name="Freshness kennel", slug="freshness-kennel",
        )
        self.dog = Dog.objects.create(
            name="Original Display Name", slug="freshness-dog",
            is_public=True, kennel=self.kennel,
        )

    @patch("registry.services.verify_submission", return_value=[])
    def test_approved_rename_updates_public_profile_and_all_caches(self, _verify):
        submission = Submission.objects.create(
            kind=Submission.Kind.CORRECTION, dog=self.dog,
            kennel=self.kennel, submitted_by=self.member,
            payload={"name": "Updated Display Name", "country": "Italy"},
        )
        keys = (
            "cca:home:featured-dog-ids:v1",
            "cca:home:public-stats:v4",
            "cca:dog-search:default-count:v1",
            "cca:dog-search:countries:v3",
            "cca:dog-search:kennels:v3",
        )
        for key in keys:
            cache.set(key, "old", 900)
        with self.captureOnCommitCallbacks(execute=True):
            approve_submission(submission, self.reviewer, "Identity confirmed.")
        for key in keys:
            self.assertIsNone(cache.get(key), f"Stale Django metadata: {key}")
        self.dog.refresh_from_db()
        self.assertEqual(self.dog.name, "Updated Display Name")
        response = self.client.get(
            reverse("registry:dog-detail", kwargs={"slug":self.dog.slug})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Updated Display Name")

    @patch("registry.services.verify_submission", return_value=[])
    def test_approved_new_dog_appears_immediately_by_explicit_search(self, _verify):
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=self.member,
            kennel=self.kennel,
            payload={"name": "Brand New Verified Dog", "sex":Dog.Sex.MALE},
        )
        with self.captureOnCommitCallbacks(execute=True):
            approve_submission(submission, self.reviewer, "Identity confirmed.")
        submission.refresh_from_db()
        self.assertIsNotNone(submission.dog_id)
        response=self.client.get(reverse("registry:dog-search"), {"q": "Brand New Verified Dog"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Brand New Verified Dog")
        # The unfiltered gallery intentionally requires an image; explicit
        # search must find this approved dog regardless of photo availability.

    def test_merge_invalidates_public_metadata(self):
        from registry.services import merge_dogs
        duplicate = Dog.objects.create(
            name="Duplicate Dog", slug="duplicate-dog",
            is_public=True, kennel=self.kennel,
        )
        key = "cca:home:public-stats:v4"
        cache.set(key, {"dog_count": 999}, 300)
        with self.captureOnCommitCallbacks(execute=True):
            merge_dogs(self.dog, duplicate, performed_by=self.reviewer)
        self.assertIsNone(cache.get(key))
        self.assertFalse(Dog.objects.filter(pk=duplicate.pk).exists())
