"""Staff evidence triage: useful ordering without leaking hidden records."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import Dog, DogSource, ModerationRoleAssignment, VerificationState


class StaffEvidencePriorityTests(TestCase):
    def setUp(self):
        self.url = reverse("accounts:data-health-evidence")
        self.staff_user = get_user_model().objects.create_user(
            username="evidence-reviewer-priority", password="StrongTestPassword123!"
        )
        ModerationRoleAssignment.objects.create(
            user=self.staff_user,
            role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.client.force_login(self.staff_user)

    def test_popular_first_and_alphabetical_switch(self):
        low = Dog.objects.create(name="Alpha Archive", slug="alpha-archive", is_public=True, search_count=1)
        high = Dog.objects.create(name="Zeta Archive", slug="zeta-archive", is_public=True, search_count=900)
        popular = self.client.get(self.url)
        self.assertEqual(popular.status_code, 200)
        self.assertEqual(
            [dog.pk for dog in popular.context["dogs"]][:2],
            [high.pk, low.pk],
        )
        alphabetic = self.client.get(self.url, {"sort": "name"})
        self.assertEqual(alphabetic.status_code, 200)
        self.assertEqual(
            [dog.pk for dog in alphabetic.context["dogs"]][:2],
            [low.pk, high.pk],
        )
        self.assertContains(popular, "Most searched first")

    def test_public_worklist_excludes_moderation_hidden(self):
        Dog.objects.create(name="Visible", slug="visible-review", is_public=True)
        Dog.objects.create(
            name="Hidden", slug="hidden-review",
            is_public=True, hidden_by_moderation=True,
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        slugs = {dog.slug for dog in response.context["dogs"]}
        self.assertIn("visible-review", slugs)
        self.assertNotIn("hidden-review", slugs)

    def test_reviewed_status_cross_check_does_not_change_verification(self):
        candidate = Dog.objects.create(
            name="Needs Documentary Crosscheck", slug="needs-crosscheck",
            is_public=True, verification_state=VerificationState.PEDIGREE_REVIEWED,
        )
        verified = Dog.objects.create(
            name="Source Reviewed", slug="source-reviewed",
            is_public=True, verification_state=VerificationState.PEDIGREE_REVIEWED,
        )
        DogSource.objects.create(
            dog=verified, title="Reviewed archive",
            source_type=DogSource.SourceType.PEDIGREE,
            source_url="https://example.org/archive", verified_at=timezone.now(),
        )
        response = self.client.get(
            self.url, {"issue": "reviewed-status-needs-source-check"}
        )
        self.assertEqual(response.status_code, 200)
        slugs = {dog.slug for dog in response.context["dogs"]}
        self.assertEqual(slugs, {candidate.slug})
        self.assertContains(response, "Other approved evidence may exist")
        candidate.refresh_from_db()
        self.assertEqual(candidate.verification_state, VerificationState.PEDIGREE_REVIEWED)

    def test_invalid_sort_rejected(self):
        self.assertEqual(self.client.get(self.url, {"sort": "random"}).status_code, 400)

    def test_regular_member_cannot_access_worklist(self):
        member = get_user_model().objects.create_user(
            username="evidence-member-priority", password="StrongTestPassword123!"
        )
        self.client.force_login(member)
        self.assertEqual(self.client.get(self.url).status_code, 403)
