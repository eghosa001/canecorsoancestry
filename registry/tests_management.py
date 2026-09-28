from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    Dog,
    DogAlias,
    DogRedirect,
    Kennel,
    MergeHistory,
    Notification,
    Submission,
    VerificationState,
)
from .services import approve_submission, duplicate_candidates, merge_dogs


class DogMergeTests(TestCase):
    def test_merge_repoints_relationships_and_keeps_old_url(self):
        canonical = Dog.objects.create(
            name="Karma",
            slug="karma",
            sex=Dog.Sex.FEMALE,
            is_public=True,
        )
        duplicate = Dog.objects.create(
            name="Karma Duplicate",
            slug="karma-old",
            sex=Dog.Sex.FEMALE,
            is_public=True,
        )
        child = Dog.objects.create(
            name="Child",
            slug="child-merge",
            sire=duplicate,
            is_public=True,
        )
        DogAlias.objects.create(dog=duplicate, name="Karma Alt")

        history = merge_dogs(canonical, duplicate)

        child.refresh_from_db()
        self.assertEqual(child.sire, canonical)
        self.assertFalse(Dog.objects.filter(pk=duplicate.pk).exists())
        self.assertTrue(DogAlias.objects.filter(dog=canonical, name="Karma Alt").exists())
        self.assertTrue(DogRedirect.objects.filter(old_slug="karma-old", dog=canonical).exists())
        self.assertEqual(MergeHistory.objects.get(pk=history.pk).canonical_dog, canonical)

        response = self.client.get(reverse("registry:dog-detail", args=["karma-old"]))
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.url, reverse("registry:dog-detail", args=["karma"]))


class SubmissionApprovalTests(TestCase):
    def test_approved_new_dog_stays_private_and_notifies_submitter(self):
        user = get_user_model().objects.create_user(username="breeder")
        reviewer = get_user_model().objects.create_user(username="mod", is_staff=True)
        kennel = Kennel.objects.create(name="Test Kennel", slug="test-kennel")
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=user,
            kennel=kennel,
            payload={"name": "New Dog", "sex": Dog.Sex.MALE},
        )

        approve_submission(submission, reviewer)

        submission.refresh_from_db()
        dog = submission.dog
        self.assertEqual(submission.status, Submission.Status.APPROVED)
        self.assertFalse(dog.is_public)
        self.assertEqual(dog.verification_state, VerificationState.COMMUNITY)
        self.assertTrue(Notification.objects.filter(user=user).exists())



class DuplicateCandidateTests(TestCase):
    def test_normalized_name_match_is_suggested_without_merging(self):
        first = Dog.objects.create(name="Custodi-Nos Karma", slug="candidate-a")
        second = Dog.objects.create(name="Custodi Nos Karma", slug="candidate-b")

        candidates = duplicate_candidates()

        self.assertEqual(candidates[0]["left"].pk in {first.pk, second.pk}, True)
        self.assertIn("Same normalized name", candidates[0]["reasons"])
        self.assertEqual(Dog.objects.count(), 2)
