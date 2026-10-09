"""Keep image/registration cards correct while removing a remote Supabase query."""
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.core.cache import cache

from registry.models import Dog, DogRegistration, RegistrationAuthority
from registry.querysets import with_card_registration
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
