"""Focused tests for the live editor's public visibility and image selection."""
from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, DogImage, ModerationAudit, ModerationRoleAssignment


class StaffChangeVisibilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(username="immediate-visibility-editor")
        self.senior = User.objects.create_user(username="visibility-senior")
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
        ModerationRoleAssignment.objects.create(
            user=self.senior, role=ModerationRoleAssignment.Role.SENIOR,
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
        caches['public'].set("cca:home:featured-dog-ids:v1", [self.dog.pk], 300)
        caches['public'].set("cca:home:public-stats:v4", {"dog_count": 1}, 300)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(caches['public'].get("cca:home:featured-dog-ids:v1"))
        self.assertIsNone(caches['public'].get("cca:home:public-stats:v4"))
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

    def test_moderator_can_publish_private_dog_with_audited_visibility(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        url, data = self.payload(visibility_public="on")
        self.assertContains(self.client.get(url), 'name="visibility_public"')
        self.assertContains(self.client.get(url), "Save dog details and visibility")
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.dog.refresh_from_db()
        self.assertTrue(self.dog.is_public)
        self.assertFalse(self.dog.visibility_locked_by_superadmin)
        event = ModerationAudit.objects.get(dog=self.dog, summary__publication_action="publish")
        self.assertEqual(event.actor, self.staff)
        self.assertFalse(event.summary["is_owner"])

    def test_senior_can_publish_and_moderator_can_unpublish(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        self.client.force_login(self.senior)
        url, data = self.payload(visibility_public="on")
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.dog.refresh_from_db()
        self.assertTrue(self.dog.is_public)
        self.assertFalse(self.dog.visibility_locked_by_superadmin)
        self.client.force_login(self.staff)
        url, data = self.payload(visibility_public="false")
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.dog.refresh_from_db()
        self.assertFalse(self.dog.is_public)
        self.assertTrue(ModerationAudit.objects.filter(
            dog=self.dog, actor=self.staff, summary__publication_action="unpublish",
        ).exists())

    def test_super_admin_publication_lock_blocks_moderator_and_senior(self):
        self.dog.is_public = False
        self.dog.visibility_locked_by_superadmin = True
        self.dog.save(update_fields=["is_public", "visibility_locked_by_superadmin"])
        for user in (self.staff, self.senior):
            self.client.force_login(user)
            url, data = self.payload(visibility_public="on")
            self.assertNotContains(self.client.get(url), 'name="visibility_public"')
            self.assertEqual(self.client.post(url, data).status_code, 403)
            self.dog.refresh_from_db()
            self.assertFalse(self.dog.is_public)
        self.assertFalse(ModerationAudit.objects.filter(
            dog=self.dog, summary__publication_action="publish",
        ).exists())

    def test_moderator_cannot_publish_and_change_ancestry_in_single_post(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        url, data = self.payload(visibility_public="on", sex=Dog.Sex.FEMALE)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Save protected ancestry or evidence changes separately")
        self.dog.refresh_from_db()
        self.assertFalse(self.dog.is_public)
        self.assertNotEqual(self.dog.sex, Dog.Sex.FEMALE)

    def test_direct_publication_endpoint_allows_senior_and_respects_owner_lock(self):
        self.dog.is_public = False
        self.dog.save(update_fields=["is_public"])
        endpoint = reverse("accounts:dog-set-public-visibility", args=[self.dog.pk])
        self.client.force_login(self.senior)
        self.assertEqual(self.client.post(endpoint, {
            "action": "publish", "reason": "Breeder identity and supporting evidence confirmed",
            "confirm_visibility": "yes",
            "version": self.dog.updated_at.isoformat(),
        }).status_code, 302)
        self.dog.refresh_from_db()
        self.assertTrue(self.dog.is_public)
        self.assertFalse(self.dog.visibility_locked_by_superadmin)
        self.assertTrue(ModerationAudit.objects.filter(
            dog=self.dog, actor=self.senior, summary__publication_action="publish",
        ).exists())
        self.dog.visibility_locked_by_superadmin = True
        self.dog.save(update_fields=["visibility_locked_by_superadmin", "updated_at"])
        self.assertEqual(self.client.post(endpoint, {
            "action": "unpublish", "reason": "Attempt to bypass Super Admin publication lock",
            "confirm_visibility": "yes",
            "version": self.dog.updated_at.isoformat(),
        }).status_code, 403)
        self.dog.refresh_from_db()
        self.assertTrue(self.dog.is_public)

    def test_inactive_moderator_has_no_publication_authority(self):
        from registry.permissions import can_publish_canonical_dog
        self.staff.is_active = False
        self.staff.save(update_fields=["is_active"])
        self.assertFalse(can_publish_canonical_dog(self.staff))
        self.client.force_login(self.staff)
        # Django treats inactive sessions as unauthenticated and redirects to login.
        self.assertEqual(self.client.get(
            reverse("accounts:dog-direct-edit", args=[self.dog.pk])
        ).status_code, 302)

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
