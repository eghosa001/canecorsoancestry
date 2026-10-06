from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import Dog, DogImage, DogRegistration, Kennel, RegistrationAuthority
from .services import duplicate_candidates


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

        response = self.client.get(reverse("registry:dog-search"), {"q": "Paged Dog"})

        self.assertEqual(response.context["result_count"], 25)
        self.assertEqual(len(response.context["dogs"]), 24)
        self.assertTrue(response.context["page_obj"].has_next())

    def test_duplicate_candidates_skip_very_common_name_buckets(self):
        for index in range(9):
            Dog.objects.create(name="Atlas", slug=f"atlas-{index}")

        Dog.objects.create(name="Rare Twin", slug="rare-twin-a")
        Dog.objects.create(name="Rare Twin", slug="rare-twin-b")

        rows = duplicate_candidates(limit=10)

        self.assertTrue(
            any(
                row["reference"].name == "Rare Twin"
                and row["candidate"].name == "Rare Twin"
                for row in rows
            )
        )
        self.assertFalse(
            any(
                row["reference"].name == "Atlas"
                or row["candidate"].name == "Atlas"
                for row in rows
            )
        )

    def test_search_origin_profile_still_records_popularity(self):
        dog = Dog.objects.create(
            name="Search Counter Dog",
            slug="search-counter-dog",
            is_public=True,
        )

        response = self.client.get(
            reverse("registry:dog-detail", args=[dog.slug]),
            {"source": "search"},
        )

        self.assertEqual(response.status_code, 200)
        dog.refresh_from_db()
        self.assertEqual(dog.search_count, 1)

    def test_default_browse_only_shows_imaged_dogs_by_popularity(self):
        kennel = Kennel.objects.create(name="Shared Kennel", slug="shared-kennel")
        popular = Dog.objects.create(
            name="Popular Imaged Dog",
            slug="popular-imaged-dog",
            kennel=kennel,
            is_public=True,
            search_count=50,
        )
        same_kennel = Dog.objects.create(
            name="Second Shared Kennel Dog",
            slug="second-shared-kennel-dog",
            kennel=kennel,
            is_public=True,
            search_count=20,
        )
        quieter = Dog.objects.create(
            name="Quieter Imaged Dog",
            slug="quieter-imaged-dog",
            is_public=True,
            search_count=3,
        )
        Dog.objects.create(
            name="No Image Dog",
            slug="no-image-dog",
            is_public=True,
            search_count=500,
        )
        DogImage.objects.create(dog=popular, image="dogs/popular.jpg", is_primary=True)
        DogImage.objects.create(dog=same_kennel, image="dogs/shared-second.jpg", is_primary=True)
        DogImage.objects.create(dog=quieter, image="dogs/quieter.jpg", is_primary=True)

        response = self.client.get(reverse("registry:dog-search"))

        self.assertEqual(
            [dog.name for dog in response.context["dogs"]],
            ["Popular Imaged Dog", "Quieter Imaged Dog"],
        )
        self.assertNotContains(response, "Second Shared Kennel Dog")
        self.assertNotContains(response, "No Image Dog")

    def test_dog_suggestions_return_live_matches(self):
        Dog.objects.create(
            name="Suggestion Champion",
            slug="suggestion-champion",
            is_public=True,
            search_count=8,
        )

        response = self.client.get(
            reverse("registry:dog-suggestions"),
            {"q": "Suggestion"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["name"], "Suggestion Champion")

    def test_dog_suggestions_browse_returns_popular_sex_matches(self):
        Dog.objects.create(
            name="Browse Sire",
            slug="browse-sire",
            sex=Dog.Sex.MALE,
            is_public=True,
            search_count=20,
        )
        Dog.objects.create(
            name="Browse Dam",
            slug="browse-dam",
            sex=Dog.Sex.FEMALE,
            is_public=True,
            search_count=30,
        )

        response = self.client.get(
            reverse("registry:dog-suggestions"),
            {"browse": "1", "sex": "male"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["name"], "Browse Sire")

    def test_dog_suggestions_use_single_database_query(self):
        kennel = Kennel.objects.create(name="Fast Kennel", slug="fast-kennel")
        dog = Dog.objects.create(
            name="Performance Champion",
            slug="performance-champion",
            kennel=kennel,
            is_public=True,
            search_count=15,
        )
        DogRegistration.objects.create(dog=dog, number="PERF-001")

        with self.assertNumQueries(1):
            response = self.client.get(
                reverse("registry:dog-suggestions"),
                {"q": "Performance"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["registration"], "PERF-001")

    def test_public_dog_profile_always_exposes_coi(self):
        common = Dog.objects.create(
            name="COI Common", slug="coi-common-profile", is_public=True
        )
        sire = Dog.objects.create(
            name="COI Sire",
            slug="coi-sire-profile",
            sex=Dog.Sex.MALE,
            sire=common,
            is_public=True,
        )
        dam = Dog.objects.create(
            name="COI Dam",
            slug="coi-dam-profile",
            sex=Dog.Sex.FEMALE,
            sire=common,
            is_public=True,
        )
        dog = Dog.objects.create(
            name="COI Dog",
            slug="coi-dog-profile",
            sire=sire,
            dam=dam,
            is_public=True,
        )

        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "COI")
        self.assertContains(response, "12.50%")

    def test_public_dog_profile_bounds_large_relationship_previews(self):
        sire = Dog.objects.create(
            name="Preview Sire",
            slug="preview-sire",
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        dog = Dog.objects.create(
            name="Preview Dog",
            slug="preview-dog",
            sire=sire,
            sex=Dog.Sex.MALE,
            is_public=True,
        )
        for index in range(3):
            Dog.objects.create(
                name=f"Preview Sibling {index}",
                slug=f"preview-sibling-{index}",
                sire=sire,
                is_public=True,
            )
            dam = Dog.objects.create(
                name=f"Preview Dam {index}",
                slug=f"preview-dam-{index}",
                sex=Dog.Sex.FEMALE,
                is_public=True,
            )
            Dog.objects.create(
                name=f"Preview Child {index}",
                slug=f"preview-child-{index}",
                sire=dog,
                dam=dam,
                is_public=True,
            )

        with patch("registry.views.PROFILE_RELATION_PREVIEW_LIMIT", 2):
            response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["siblings"]), 2)
        self.assertEqual(len(response.context["offspring"]), 2)
        self.assertEqual(len(response.context["mates"]), 2)
        self.assertTrue(response.context["siblings_truncated"])
        self.assertTrue(response.context["offspring_truncated"])
        self.assertTrue(response.context["mates_truncated"])

    def test_public_search_finds_external_registration_number(self):
        dog = Dog.objects.create(name="Branco", slug="branco", is_public=True)
        authority = RegistrationAuthority.objects.create(code="KSS", name="Kennel authority")
        DogRegistration.objects.create(dog=dog, authority=authority, number="JR 710606 Cc")

        response = self.client.get(reverse("registry:dog-search"), {"q": "710606"})

        self.assertContains(response, "Branco")

    def test_kennel_directory_searches_name_city_and_country(self):
        Kennel.objects.create(name="Sforza", slug="sforza", city="Rome", country="Italy")
        Kennel.objects.create(name="Custodi Nos", slug="custodi-nos", country="Serbia")

        response = self.client.get(reverse("registry:kennel-list"), {"q": "Rome"})

        self.assertContains(response, "Sforza")
        self.assertNotContains(response, "Custodi Nos")

    def test_kennel_directory_shows_sixty_names_per_page(self):
        for index in range(61):
            Kennel.objects.create(name=f"Kennel {index:02d}", slug=f"kennel-{index:02d}")

        response = self.client.get(reverse("registry:kennel-list"))

        self.assertEqual(len(response.context["kennels"]), 60)
        self.assertTrue(response.context["page_obj"].has_next())

