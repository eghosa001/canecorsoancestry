from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Dog, DogRegistration, RegistrationAuthority


class DogModelTests(TestCase):
    def test_dog_cannot_be_its_own_parent(self):
        dog = Dog.objects.create(name="Karma", slug="karma")
        dog.sire = dog
        with self.assertRaises(ValidationError):
            dog.full_clean()

    def test_public_search_finds_dog_by_name(self):
        Dog.objects.create(name="Karma Custodi Nos", slug="karma-custodi-nos", is_public=True)
        response = self.client.get(reverse("registry:dog-search"), {"q": "Karma"})
        self.assertContains(response, "Karma Custodi Nos")

    def test_public_search_is_paginated(self):
        for index in range(25):
            Dog.objects.create(
                name=f"Paged Dog {index:02d}",
                slug=f"paged-dog-{index:02d}",
                is_public=True,
            )

        response = self.client.get(reverse("registry:dog-search"))

        self.assertEqual(response.context["result_count"], 25)
        self.assertEqual(len(response.context["dogs"]), 24)
        self.assertTrue(response.context["page_obj"].has_next())

    def test_public_search_finds_external_registration_number(self):
        dog = Dog.objects.create(name="Branco", slug="branco", is_public=True)
        authority = RegistrationAuthority.objects.create(code="KSS", name="Kennel authority")
        DogRegistration.objects.create(dog=dog, authority=authority, number="JR 710606 Cc")

        response = self.client.get(reverse("registry:dog-search"), {"q": "710606"})

        self.assertContains(response, "Branco")
