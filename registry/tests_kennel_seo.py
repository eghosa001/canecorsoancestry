"""Focused kennel SEO tests; the public directory does not favor a single owner."""
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from registry.models import Kennel


@override_settings(SITE_URL="https://canecorsoancestry.com")
class KennelSEOTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ordinary = Kennel.objects.create(
            name="Alpha Kennel", slug="alpha-kennel", is_public=True
        )
        cls.bellissimo = Kennel.objects.create(
            name="Bellissimo Geni", slug="bellissimo-geni", is_public=True,
            verified_at=timezone.now(), city="Benin City", country="Nigeria",
            description="A kennel profile backed by reviewed records.",
        )
        cls.unverified = Kennel.objects.create(
            name="Bellissimo Geni Archives", slug="bellissimo-geni-archives",
            is_public=True, is_archive_hypothesis=True,
        )

    def test_directory_remains_alphabetical_and_fair(self):
        response = self.client.get(reverse("registry:kennel-list"))
        self.assertEqual(response.status_code, 200)
        kennels = list(response.context["kennels"])
        self.assertEqual(kennels[0].pk, self.ordinary.pk)
        self.assertContains(response, "Cane Corso Kennel Directory")
        self.assertNotContains(response, "Featured kennel")

    def test_filtered_directory_keeps_normal_sorting(self):
        response = self.client.get(reverse("registry:kennel-list"), {"q": "Kennel"})
        kennels = list(response.context["kennels"])
        self.assertEqual(kennels[0].pk, self.ordinary.pk)

    def test_kennel_profile_has_unique_metadata_and_real_description(self):
        response = self.client.get(
            reverse("registry:kennel-detail", args=[self.bellissimo.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bellissimo Geni · Cane Corso Kennel & Pedigrees")
        self.assertContains(response, "application/ld+json")
        self.assertContains(response, "A kennel profile backed by reviewed records.")
        self.assertNotContains(response, "Featured kennel")
        self.assertNotContains(response, "site-owner selection")

    def test_home_does_not_display_single_kennel_promotion(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Featured kennel")
        self.assertNotContains(response, "Site-owner selection")
