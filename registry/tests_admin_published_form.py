"""Prevent regression of published dog's Django Admin change-form rendering."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.admin import DogAdmin
from registry.models import Dog


class PublishedDogAdminPageTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="qa-admin-dog-form",
            email="qa-admin-dog-form@example.test",
            password="only-for-isolated-tests-1",
        )
        self.dog = Dog.objects.create(
            name="QA Published Dog", slug="qa-published-dog", is_public=True,
        )
        self.client.force_login(self.admin)

    def test_published_dog_admin_form_renders_without_editable_name(self):
        response = self.client.get(
            reverse("admin:registry_dog_change", args=[self.dog.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "QA Published Dog")
        self.assertContains(response, "Public website COI")

    def test_private_dog_admin_form_still_renders_editable_name(self):
        self.dog.is_public = False
        self.dog.save(update_fields=("is_public",))
        response = self.client.get(
            reverse("admin:registry_dog_change", args=[self.dog.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "QA Published Dog")
        self.assertContains(response, 'name="name"')
