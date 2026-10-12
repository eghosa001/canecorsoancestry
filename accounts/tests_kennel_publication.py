"""Focused regression checks for independent kennel and dog visibility."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, Kennel, ModerationAudit, ModerationRoleAssignment


class KennelPublicationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(username="kennel-reviewer", password="unused")
        ModerationRoleAssignment.objects.create(
            user=self.staff, role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.member = User.objects.create_user(username="kennel-member")
        self.kennel = Kennel.objects.create(name="Quality Kennel", slug="quality-kennel")
        self.first = Dog.objects.create(
            name="Alpha Publication", slug="alpha-publication",
            kennel=self.kennel, is_public=True,
        )
        self.second = Dog.objects.create(
            name="Beta Publication", slug="beta-publication",
            kennel=self.kennel, is_public=True,
        )
        self.private = Dog.objects.create(
            name="Never Approved", slug="never-approved",
            kennel=self.kennel, is_public=False,
        )

    def change(self, action, **extra):
        self.kennel.refresh_from_db()
        return self.client.post(
            reverse("accounts:kennel-publication-change", args=[self.kennel.pk]),
            {"action": action, "reason": "Reviewed kennel publication",
             "version": self.kennel.updated_at.isoformat(), "confirm": "yes", **extra},
        )

    def dogs_change(self, action, *dogs):
        self.kennel.refresh_from_db()
        return self.client.post(
            reverse("accounts:kennel-dogs-visibility-change", args=[self.kennel.pk]),
            {"action": action, "reason": "Reviewed selected records",
             "version": self.kennel.updated_at.isoformat(), "confirm": "yes",
             "dog_ids": [str(dog.pk) for dog in dogs]},
        )

    def test_four_kennel_modes_and_restore_keep_dog_approvals(self):
        self.client.force_login(self.staff)
        for action, kennel_visible, first_visible in [
            ("hide_profile", False, True),
            ("hide_all", False, False),
            ("hide_dogs", True, False),
            ("show_all", True, True),
        ]:
            self.assertEqual(self.change(action).status_code, 302)
            self.kennel.refresh_from_db()
            self.first.refresh_from_db()
            self.assertEqual(self.kennel.is_public, kennel_visible)
            self.assertTrue(self.first.is_public)
            self.assertEqual(self.first.is_effectively_public, first_visible)
            self.assertEqual(
                self.client.get(reverse("registry:kennel-detail", args=[self.kennel.slug])).status_code,
                200 if kennel_visible else 404,
            )
            self.assertEqual(
                self.client.get(reverse("registry:dog-detail", args=[self.first.slug])).status_code,
                200 if first_visible else 404,
            )
        self.assertEqual(self.client.get(reverse("registry:dog-detail", args=[self.private.slug])).status_code, 404)
        self.assertEqual(
            ModerationAudit.objects.filter(summary__kind="kennel_publication").count(), 4,
        )

    def test_selected_dog_hide_restore_affects_only_selection(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.dogs_change("hide", self.first).status_code, 302)
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertTrue(self.first.is_public)
        self.assertTrue(self.first.hidden_by_moderation)
        self.assertFalse(self.first.is_effectively_public)
        self.assertTrue(self.second.is_effectively_public)
        self.assertEqual(self.client.get(reverse("registry:dog-detail", args=[self.first.slug])).status_code, 404)
        self.assertEqual(self.client.get(reverse("registry:dog-detail", args=[self.second.slug])).status_code, 200)
        self.assertNotContains(
            self.client.get(reverse("registry:dog-search"), {"q": self.first.name}),
            self.first.slug + "/",
        )
        self.assertEqual(self.dogs_change("restore", self.first, self.private).status_code, 302)
        self.first.refresh_from_db()
        self.private.refresh_from_db()
        self.assertTrue(self.first.is_effectively_public)
        self.assertFalse(self.private.is_effectively_public)
        self.assertFalse(self.private.is_public)

    def test_non_moderator_cannot_change_publication_and_foreign_dog_rejected(self):
        self.client.force_login(self.member)
        self.assertEqual(self.change("hide_all").status_code, 403)
        self.assertEqual(self.dogs_change("hide", self.first).status_code, 403)
        self.client.force_login(self.staff)
        foreign = Kennel.objects.create(name="Other Kennel", slug="other-kennel")
        other_dog = Dog.objects.create(name="Foreign Dog", slug="foreign-dog", kennel=foreign, is_public=True)
        self.assertEqual(self.dogs_change("hide", self.first, other_dog).status_code, 302)
        self.first.refresh_from_db()
        self.assertFalse(self.first.hidden_by_moderation)
        self.assertEqual(self.change("hide_all", version="stale").status_code, 302)
        self.kennel.refresh_from_db()
        self.assertTrue(self.kennel.is_public)
        self.assertFalse(self.kennel.hide_dogs)

    def test_sitemap_and_public_kennel_list_honor_profile_visibility(self):
        self.client.force_login(self.staff)
        self.change("hide_profile")
        directory = self.client.get(reverse("registry:kennel-list"))
        self.assertNotContains(directory, self.kennel.name)
        self.assertEqual(self.client.get(reverse("registry:dog-detail", args=[self.first.slug])).status_code, 200)
        self.change("hide_all")
        self.assertNotContains(self.client.get(reverse("registry:dog-search"), {"q": self.first.name}), self.first.slug + "/")
