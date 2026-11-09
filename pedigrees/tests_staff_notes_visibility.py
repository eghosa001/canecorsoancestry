"""Member pedigree pages hide internal review guidance without losing core features."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, Kennel, KennelMembership, ModerationRoleAssignment


class PedigreeStaffNotesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.kennel = Kennel.objects.create(name="Pedigree Notes Kennel", slug="pedigree-notes-kennel")
        cls.public = Dog.objects.create(name="Review Notes Public", slug="review-notes-public", kennel=cls.kennel, is_public=True)
        cls.private = Dog.objects.create(name="Review Notes Private", slug="review-notes-private", kennel=cls.kennel, is_public=False)
        cls.member = get_user_model().objects.create_user(username="notes-member")
        cls.moderator = get_user_model().objects.create_user(username="notes-moderator")
        KennelMembership.objects.create(
            user=cls.member, kennel=cls.kennel, role=KennelMembership.Role.OWNER
        )
        ModerationRoleAssignment.objects.create(
            user=cls.moderator, role=ModerationRoleAssignment.Role.REVIEWER,
            assigned_by=cls.moderator,
        )

    def test_ordinary_member_keeps_pedigree_and_pdf_but_not_staff_review_notes(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("pedigrees:detail", args=[self.public.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_staff_notes"])
        self.assertContains(response, "Download pedigree (PDF)")
        self.assertContains(response, "Coefficient of inbreeding")
        self.assertContains(response, "pedigree-board")
        self.assertNotContains(response, "Analysis only; no pedigree record is changed.")
        self.assertNotContains(response, "The calculation uses the recorded direct ancestral paths")
        self.assertNotContains(response, "Each path contributes")
        self.assertNotContains(response, "Siblings and offspring are not additional COI ancestors.")
        self.assertNotContains(response, "No canonical record")
        self.assertContains(response, 'role="region" tabindex="0"')

    def test_authorized_private_member_has_same_clean_interface(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("accounts:member-pedigree", args=[self.private.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_staff_notes"])
        self.assertContains(response, "Download pedigree (PDF)")
        self.assertContains(response, "pedigree-board")
        self.assertNotContains(response, "Analysis only; no pedigree record is changed.")
        self.assertNotContains(response, "The calculation uses the recorded direct ancestral paths")

    def test_active_moderator_can_read_internal_explanations_on_published_pedigree(self):
        self.client.force_login(self.moderator)
        response = self.client.get(reverse("pedigrees:detail", args=[self.public.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["show_staff_notes"])
        self.assertContains(response, "Each path contributes")
        self.assertContains(response, "Analysis only; no pedigree record is changed.")
        self.assertContains(response, "The calculation uses the recorded direct ancestral paths")
        self.assertContains(response, "Download pedigree (PDF)")

    def test_staff_notes_do_not_grant_access_to_private_member_pedigrees(self):
        self.client.force_login(self.moderator)
        response = self.client.get(reverse("accounts:member-pedigree", args=[self.private.pk]))
        self.assertIn(response.status_code, (302, 403, 404))
