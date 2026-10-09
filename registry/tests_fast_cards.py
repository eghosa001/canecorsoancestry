"""Keep image/registration cards correct while removing a remote Supabase query."""
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.core.cache import cache

from registry.models import Dog, DogImage, DogRegistration, RegistrationAuthority
from registry.querysets import with_card_image, with_card_registration
from registry.views import _dog_cards


class FastPublicDogCardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dog = Dog.objects.create(
            name="Card Performance Test Corso", slug="card-performance-test-corso",
            is_public=True, sex=Dog.Sex.MALE,
        )
        authority = RegistrationAuthority.objects.create(
            code="PERF", name="Performance Testing Authority",
        )
        DogRegistration.objects.create(
            dog=cls.dog, authority=authority, number="CARD-001",
        )

    def test_dog_registration_is_inlined_without_another_sql_round_trip(self):
        cards = with_card_registration(_dog_cards(
            Dog.objects.filter(pk=self.dog.pk), include_sources=False,
            include_registrations=False,
        ))
        with CaptureQueriesContext(connection) as queries:
            result = list(cards)
            code = result[0].card_registration_code
            number = result[0].card_registration_number
        self.assertEqual((code, number), ("PERF", "CARD-001"))
        self.assertEqual(len(queries), 2, "dog row + managed image prefetch, no registration query")

    def test_first_photo_and_registration_use_one_db_query(self):
        DogImage.objects.create(
            dog=self.dog, image="dogs/2026/10/lower-priority.jpg",
            is_primary=False, sort_order=0,
        )
        DogImage.objects.create(
            dog=self.dog, image="dogs/2026/10/primary-picture.jpg",
            is_primary=True, sort_order=1,
        )
        cards = with_card_image(with_card_registration(_dog_cards(
            Dog.objects.filter(pk=self.dog.pk), include_sources=False,
            include_registrations=False, include_images=False,
        )))
        with CaptureQueriesContext(connection) as queries:
            rows = list(cards)
        self.assertEqual(len(queries), 1, "dog + first photo + registration must be one remote query")
        self.assertEqual(rows[0].card_registration_number, "CARD-001")
        self.assertEqual(rows[0].card_image_name, "dogs/2026/10/primary-picture.jpg")

        cache.clear()
        page = self.client.get("/dogs/?q=Card%20Performance")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "/media/dogs/2026/10/primary-picture.jpg")
        self.assertNotContains(page, "lower-priority.jpg")
        self.assertContains(page, "CARD-001")

        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, "primary-picture.jpg")
        self.assertContains(home, "CARD-001")

    def test_browse_paginates_ids_before_loading_card_subqueries(self):
        from registry.models import Kennel
        kennel = Kennel.objects.create(name="Browse Perf Kennel", slug="browse-perf-kennel")
        Dog.objects.filter(pk=self.dog.pk).update(kennel=kennel, search_count=10)
        DogImage.objects.create(
            dog=self.dog, image="dogs/2026/10/browse-photo.jpg",
            is_primary=True,
        )
        other = Dog.objects.create(
            name="Second Browse Perf Dog", slug="second-browse-perf-dog",
            is_public=True, kennel=kennel, search_count=5,
        )
        DogImage.objects.create(
            dog=other, image="dogs/2026/10/second-browse-photo.jpg", is_primary=True,
        )
        cache.clear()
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/dogs/?q=")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.dog.name)
        self.assertContains(response, "browse-photo.jpg")
        self.assertContains(response, "CARD-001")
        self.assertNotContains(response, "Second Browse Perf Dog")
        window_queries = [
            item["sql"] for item in queries
            if "ROW_NUMBER()" in item["sql"].upper()
        ]
        self.assertTrue(window_queries, "The one-dog-per-kennel ranking must remain")
        for sql in window_queries:
            self.assertNotIn(
                "registry_dogregistration", sql,
                "Registration card subqueries must run only after pagination",
            )

    def test_public_search_still_renders_registration_and_dog(self):
        cache.clear()
        response = self.client.get("/dogs/?q=Card%20Performance")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CARD-001")
        self.assertContains(response, "PERF")
        self.assertContains(response, self.dog.name)

    def test_public_home_still_renders_featured_registration(self):
        cache.clear()
        # Home uses the most-searched imaged dogs; this un-imaged record should
        # not appear merely because it has a registration.
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "CARD-001")
