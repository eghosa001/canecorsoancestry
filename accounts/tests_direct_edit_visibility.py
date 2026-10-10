"""Focused tests for the live editor's public visibility and image selection."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, DogImage, ModerationAudit, ModerationRoleAssignment


class StaffChangeVisibilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(username="immediate-visibility-editor")
        self.owner = User.objects.create_superuser(
            username="visibility-owner",
            email="visibility-owner@example.com",
            password="owner-test-password",
        )
        ModerationRoleAssignment.objects.create(
            user=self.staff, role=ModerationRoleAssignment.Role.REVIEWER,
        )
        ModerationRoleAssignment.objects.create(
            user=self.owner, role=ModerationRoleAssignment.Role.OWNER,
            assigned_by=self.owner,
        )
        self.dog = Dog.objects.create(name="Before", slug="visibility-dog", is_public=True)
        self.client.force_login(self.staff)

    def payload(self, **kwargs):
        editor = reverse("accounts:dog-direct-edit", args=[self.dog.pk])
        response = self.client.get(editor)
        self.assertEqual(response.status_code, 200)
        data = {
            "version": response.context["version"],
            "name": self.dog.name,
            "sex": self.dog.sex,
            "verification_state": self.dog.verification_state,
            "reason": "Verified from existing pedigree records",
        }
        for name, formset in response.context["formsets"].items():
            for field, value in formset.management_form.initial.items():
                data[f"{name}-{field}"] = str(value)
            for index, form in enumerate(formset.forms):
                for field_name in form.fields:
                    if field_name in ("DELETE", "dog"):
                        continue
                    value = form[field_name].value()
                    if value is None or value is False:
                        continue
                    if hasattr(value, "storage"):
                        continue
                    data[f"{name}-{index}-{field_name}"] = "on" if value is True else str(value)
        data.update(kwargs)
        return editor, data

    def test_live_edit_clears_cached_public_metadata(self):
        url, data = self.payload(name="After")
        cache.set("cca:home:featured-dog-ids:v1", [self.dog.pk], 300)
        cache.set("cca:home:public-stats:v4", {"dog_count": 1}, 300)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(cache.get("cca:home:featured-dog-ids:v1"))
        self.assertIsNone(cache.get("cca:home:public-stats:v4"))
        self.assertContains(
            self.client.get(reverse("registry:dog-detail", args=[self.dog.slug])),
            "After",
        )

    def test_unrelated_edit_keeps_existing_primary_photo(self):
        DogImage.objects.create(dog=self.dog, image="dog-photos/verified.jpg", is_primary=True)
        url, data = self.payload(name="Corrected Name")
        data.pop("images-0-make_primary", None)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(DogImage.objects.get(dog=self.dog).is_primary)


    def test_super_admin_switch_appears_immediately_after_bio(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("accounts:dog-direct-edit", args=[self.dog.pk]))
        self.assertEqual(response.status_code, 200)
        ordered = list(response.context["form"].fields)
        self.assertEqual(ordered[ordered.index("bio") + 1], "visibility_public")
        self.assertContains(response, 'role="switch"')
        self.assertContains(response, 'name="visibility_public"')
        self.assertContains(response, "Unpublished")
        self.assertContains(response, "Published")
        self.assertContains(response, 'data-canonical-visibility-editor')
        self.assertContains(response, 'data-publication-preview-badge')
        self.assertNotContains(response, 'id="publication-heading"')
        self.assertNotContains(response, 'class="dog-visibility-form"')

    def test_status_colours_and_manage_dog_visibility_text(self):
        self.client.force_login(self.owner)
        url = reverse("accounts:dog-direct-edit", args=[self.dog.pk])
        self.assertContains(self.client.get(url), "canonical-publication-badge--published")
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        self.assertContains(self.client.get(url), "canonical-publication-badge--unpublished")
        self.assertContains(self.client.get(url), 'data-initially-public="false"')
        manage = self.client.get(reverse("accounts:dog-edit-list"), {"q": self.dog.name})
        self.assertContains(manage, "canonical-publication-badge--unpublished")

    def test_private_django_dog_publishes_and_updates_bio_in_same_save(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        self.client.force_login(self.owner)
        url, data = self.payload(
            bio="Owner reviewed this dog's pedigree.",
            visibility_public="on",
        )
        self.assertFalse(self.client.get(url).context["form"]["visibility_public"].value())
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, data)
        self.assertRedirects(response, url)
        self.dog.refresh_from_db()
        self.assertTrue(self.dog.is_public)
        self.assertEqual(self.dog.bio, "Owner reviewed this dog's pedigree.")
        self.assertEqual(
            self.client.get(reverse("registry:dog-detail", args=[self.dog.slug])).status_code,
            200,
        )
        audit = ModerationAudit.objects.get(
            dog=self.dog,
            summary__publication_action="publish",
        )
        self.assertEqual(audit.actor, self.owner)
        self.assertFalse(audit.summary["before"]["publication"]["is_public"])
        self.assertTrue(audit.summary["after"]["publication"]["is_public"])

    def test_publish_makes_dog_searchable_even_without_a_photograph(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        self.client.force_login(self.owner)
        url, data = self.payload(visibility_public="on")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.client.logout()
        profile_url = reverse("registry:dog-detail", args=[self.dog.slug])
        self.assertEqual(self.client.get(profile_url).status_code, 200)
        search = self.client.get(reverse("registry:dog-search"), {"q": self.dog.name})
        self.assertEqual(search.status_code, 200)
        self.assertContains(search, self.dog.name)
        suggestions = self.client.get(reverse("registry:dog-suggestions"), {"q": self.dog.name})
        self.assertEqual(suggestions.status_code, 200)
        self.assertIn(self.dog.name, [x["name"] for x in suggestions.json()["results"]])

    def test_switch_off_unpublishes_without_removing_dog_from_manage_dogs(self):
        self.client.force_login(self.owner)
        url, data = self.payload(visibility_public="false")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertFalse(self.dog.is_public)
        self.assertEqual(
            self.client.get(reverse("registry:dog-detail", args=[self.dog.slug])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("accounts:dog-direct-edit", args=[self.dog.pk])).status_code,
            200,
        )
        self.assertTrue(ModerationAudit.objects.filter(
            dog=self.dog, summary__publication_action="unpublish",
        ).exists())

    def test_reviewer_cannot_see_switch_or_change_visibility_with_forged_post(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        url, data = self.payload()
        self.assertNotContains(self.client.get(url), 'name="visibility_public"')
        data["visibility_public"] = "on"
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertFalse(self.dog.is_public)
        self.assertFalse(ModerationAudit.objects.filter(
            dog=self.dog, summary__publication_action="publish",
        ).exists())

    def test_legacy_owner_save_without_switch_preserves_public_status(self):
        self.client.force_login(self.owner)
        url, data = self.payload(name="Corrected legacy dog")
        # Older browser or client data should not silently unpublish a dog.
        data.pop("visibility_public", None)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertTrue(self.dog.is_public)
        self.assertEqual(self.dog.name, "Corrected legacy dog")

    def test_stale_visibility_form_never_publishes_or_logs_success(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        self.client.force_login(self.owner)
        url, data = self.payload(visibility_public="on")
        self.dog.bio = "Newly updated meanwhile"
        self.dog.save(update_fields=["bio", "updated_at"])
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.dog.refresh_from_db()
        self.assertFalse(self.dog.is_public)
        self.assertEqual(self.dog.bio, "Newly updated meanwhile")
        self.assertFalse(ModerationAudit.objects.filter(
            dog=self.dog, summary__publication_action="publish",
        ).exists())

    def test_super_admin_reverting_visibility_revision_restores_previous_status(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        self.client.force_login(self.owner)
        url, data = self.payload(visibility_public="on")
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        audit = ModerationAudit.objects.get(
            dog=self.dog, summary__publication_action="publish",
        )
        review_url = reverse(
            "accounts:dog-review-edit", args=[self.dog.pk, audit.pk],
        )
        response = self.client.post(review_url, {
            "decision": "revert", "reason": "Publication decision reversed after review",
        })
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertFalse(self.dog.is_public)
        self.assertEqual(
            self.client.get(reverse("registry:dog-detail", args=[self.dog.slug])).status_code,
            404,
        )
