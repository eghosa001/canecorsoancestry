"""Legacy mixed health text must not overflow public dog profile or fake verification."""
from django.test import TestCase, SimpleTestCase
from django.urls import reverse

from .legacy_health import legacy_mixed_health_rows
from .models import Dog, HealthRecord, VerificationState


class LegacyHealthParsingTests(SimpleTestCase):
    def test_exact_mixed_record_from_mobile_screenshot(self):
        rows = legacy_mixed_health_rows(
            "Purity Verification/Health Test",
            "100% Cane Corso. CMR1 CLEAR. DSRA CLEAR",
        )
        self.assertEqual(
            [(r["test"], r["result"]) for r in rows],
            [("Breed purity", "Not verified"), ("CMR1", "Clear"), ("DSRA", "Clear")],
        )
        self.assertTrue(all(not row["verified"] for row in rows))

    def test_conflicting_status_is_not_shown_as_clear(self):
        rows = legacy_mixed_health_rows(
            "Purity Verification/Health Test",
            "CMR1 CLEAR; CMR1 AFFECTED; DSRA INCONCLUSIVE",
        )
        self.assertEqual([(r["test"], r["result"]) for r in rows],
                         [("CMR1", "Result unclear"), ("DSRA", "Inconclusive")])

    def test_unrelated_health_summary_not_reinterpreted(self):
        self.assertIsNone(legacy_mixed_health_rows("Heart screening", "Clear"))
        self.assertIsNone(legacy_mixed_health_rows("Breed DNA composition", "100% Cane Corso. DSRA CLEAR"))


class PublicLegacyMixedHealthTests(TestCase):
    def setUp(self):
        self.dog = Dog.objects.create(name="Screenshot Health Dog", slug="screenshot-health-dog", is_public=True)
        self.url = reverse("registry:dog-detail", args=[self.dog.slug])

    def test_public_section_has_three_short_results_without_raw_mixed_prose(self):
        original = HealthRecord.objects.create(
            dog=self.dog, test_type="Purity Verification/Health Test",
            result="100% Cane Corso. CMR1 CLEAR. DSRA CLEAR",
            verification_state=VerificationState.HEALTH_VERIFIED,
            is_public=True,
        )
        page = self.client.get(self.url)
        self.assertContains(page, 'class="health-compact-row"', count=3)
        self.assertContains(page, "Breed purity")
        self.assertContains(page, "CMR1")
        self.assertContains(page, "DSRA")
        self.assertContains(page, "Clear", count=2)
        self.assertContains(page, "Not verified")
        self.assertNotContains(page, "Purity Verification/Health Test")
        self.assertNotContains(page, "100% Cane Corso")
        self.assertNotContains(page, "DNA-tested")
        self.assertNotContains(page, "genetic-screening-status--clear")
        original.refresh_from_db()
        self.assertEqual(original.result, "100% Cane Corso. CMR1 CLEAR. DSRA CLEAR")

    def test_private_mixed_row_is_not_exposed(self):
        HealthRecord.objects.create(
            dog=self.dog, test_type="Purity Verification/Health Test",
            result="100% Cane Corso. CMR1 CLEAR. DSRA CLEAR",
            verification_state=VerificationState.HEALTH_VERIFIED,
            is_public=False,
        )
        page = self.client.get(self.url)
        self.assertContains(page, "No available records")
        self.assertNotContains(page, "CMR1")
        self.assertNotContains(page, "DSRA")
