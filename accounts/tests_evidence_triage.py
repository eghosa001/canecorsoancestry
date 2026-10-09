"""Moderation evidence triage must stay truthful, paginated and staff-only."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from registry.models import (
    Dog, DogSource, ModerationRoleAssignment, VerificationState,
)


class EvidenceTriageTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.superadmin = User.objects.create_superuser(
            username="evidence-superadmin", email="evidence-superadmin@example.test",
            password="testing-only-password",
        )
        self.mod = User.objects.create_user(username="evidence-reviewer")
        self.member = User.objects.create_user(username="evidence-member")
        ModerationRoleAssignment.objects.create(
            user=self.superadmin, role=ModerationRoleAssignment.Role.OWNER,
            assigned_by=self.superadmin,
        )
        ModerationRoleAssignment.objects.create(
            user=self.mod, role=ModerationRoleAssignment.Role.REVIEWER,
            assigned_by=self.superadmin,
        )
        self.missing = Dog.objects.create(
            name="Needs Source Attribution", slug="needs-source-attribution",
            sex=Dog.Sex.UNKNOWN, is_public=True,
        )
        self.unreviewed = Dog.objects.create(
            name="Has Unreviewed Source", slug="has-unreviewed-source",
            sex=Dog.Sex.MALE, is_public=True,
        )
        DogSource.objects.create(
            dog=self.unreviewed, source_type=DogSource.SourceType.PEDIGREE,
            title="Imported historical reference",
        )
        self.reviewed = Dog.objects.create(
            name="With Human Reviewed Source", slug="with-human-reviewed-source",
            sex=Dog.Sex.FEMALE, is_public=True,
            verification_state=VerificationState.IDENTITY_REVIEWED,
        )
        DogSource.objects.create(
            dog=self.reviewed, source_type=DogSource.SourceType.REGISTRY,
            title="Document checked by a human",
            verified_at=timezone.now(),
        )
        self.private = Dog.objects.create(
            name="Confidential Unpublished Dog", slug="confidential-unpublished",
            is_public=False,
        )
        cache.clear()
        self.base = reverse("accounts:data-health-evidence")

    def test_source_gaps_and_verified_status_are_not_conflated(self):
        self.client.force_login(self.superadmin)
        response = self.client.get(self.base, {"issue": "missing-source"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.missing.name)
        self.assertNotContains(response, self.unreviewed.name)
        self.assertNotContains(response, self.private.name)
        self.assertContains(response, "No source attribution")
        response = self.client.get(self.base, {"issue": "unreviewed-source"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.missing.name)
        self.assertContains(response, self.unreviewed.name)
        self.assertNotContains(response, self.reviewed.name)
        self.assertNotContains(response, self.private.name)
        self.assertContains(response, "No source independently reviewed")
        self.assertContains(
            response, reverse("accounts:dog-direct-edit", args=[self.unreviewed.pk])
        )

    def test_other_evidence_filters_and_server_side_pagination(self):
        self.client.force_login(self.superadmin)
        community = self.client.get(self.base, {"issue": "community-only"})
        self.assertContains(community, self.missing.name)
        self.assertContains(community, self.unreviewed.name)
        self.assertNotContains(community, self.reviewed.name)
        unknown = self.client.get(self.base, {"issue": "unknown-sex"})
        self.assertContains(unknown, self.missing.name)
        self.assertNotContains(unknown, self.unreviewed.name)
        for i in range(36):
            Dog.objects.create(
                name=f"Unattributed Example {i:02d}",
                slug=f"unattributed-example-{i:02d}",
                is_public=True,
            )
        first = self.client.get(self.base, {"issue": "missing-source"})
        self.assertEqual(len(first.context["dogs"]), 30)
        self.assertEqual(first.context["page_obj"].paginator.count, 37)
        second = self.client.get(self.base, {"issue": "missing-source", "page": "2"})
        self.assertEqual(len(second.context["dogs"]), 7)
        self.assertContains(first, "Next")
        self.assertContains(second, "Previous")

    def test_staff_read_access_never_grants_source_editing(self):
        self.client.force_login(self.mod)
        result = self.client.get(self.base)
        self.assertEqual(result.status_code, 200)
        self.assertNotContains(result, "Review source evidence")
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.base).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.base).status_code, 302)
        self.client.force_login(self.superadmin)
        self.assertEqual(self.client.get(self.base, {"issue": "unsupported"}).status_code, 400)

    def test_data_health_displays_actual_numerator_and_review_ratio(self):
        self.client.force_login(self.superadmin)
        result = self.client.get(reverse("accounts:data-health"), {"refresh": "1"})
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "2 of 3")
        self.assertContains(result, "1 of 3")
        self.assertContains(result, "A reference is not proof")
        self.assertContains(result, reverse("accounts:data-health-evidence"))
