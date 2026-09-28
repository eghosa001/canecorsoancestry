from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Dog


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
