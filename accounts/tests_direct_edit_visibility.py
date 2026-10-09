"""Focused tests for the live editor's public visibility and image selection."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, DogImage, ModerationRoleAssignment


class StaffChangeVisibilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(username="immediate-visibility-editor")
        ModerationRoleAssignment.objects.create(
            user=self.staff, role=ModerationRoleAssignment.Role.REVIEWER,
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
