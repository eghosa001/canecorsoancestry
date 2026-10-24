"""Plain-language hip/elbow display tests; source records are never rewritten."""
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import Dog, HealthRecord, VerificationState
from .orthopaedic_health import describe_orthopaedic_result


class GradeInterpretationTests(SimpleTestCase):
    def test_common_combined_hda_ed0_variants(self):
        for label, result in (
            ("HD-A ED-0", ""),
            ("HDA ED0", "normal"),
            ("Orthopaedic screening", "HD-A / ED-0"),
            ("", "hd a, ed 0"),
            ("Hip dysplasia: A", "Elbow dysplasia: 0"),
        ):
            with self.subTest(label=label, result=result):
                rows = describe_orthopaedic_result(label, result)
                self.assertEqual([(r["grade"], r["headline"]) for r in rows], [
                    ("HD-A", "Normal hips"),
                    ("ED-0", "Normal elbows"),
                ])

    def test_individual_scores_and_abnormal_grades(self):
        self.assertEqual(
            describe_orthopaedic_result("Hip score", "A")[0]["headline"],
            "Normal hips",
        )
        self.assertEqual(
            describe_orthopaedic_result("Elbow dysplasia", "2")[0]["headline"],
            "Moderate elbow changes",
        )
        rows = describe_orthopaedic_result("HD-C ED-1", "")
        self.assertEqual([r["tone"] for r in rows], ["caution", "caution"])
        self.assertEqual(rows[0]["headline"], "Mild hip dysplasia")
        self.assertEqual(
            describe_orthopaedic_result("HD-B", "")[0]["headline"],
            "Hips are close to normal",
        )

    def test_no_guessing_when_grade_is_absent_or_invalid(self):
        for test_type, result in (
            ("Hip score", "Clear"),
            ("HD-Z", "ED-9"),
            ("Heart examination", "Normal"),
            ("Hip score", "15"),  # Not FCI A-E grading
            ("Genetic test", "Carrier"),
        ):
            with self.subTest(test_type=test_type, result=result):
                self.assertEqual(describe_orthopaedic_result(test_type, result), [])


class PublicOrthopaedicGradeTests(TestCase):
    def setUp(self):
        self.dog = Dog.objects.create(
            name="Clear joint report", slug="clear-joint-report", is_public=True,
        )
        self.url = reverse("registry:dog-detail", args=[self.dog.slug])

    def test_one_combined_record_becomes_two_short_rows(self):
        record = HealthRecord.objects.create(
            dog=self.dog, test_type="HDA ED0", result="Certified",
            verification_state=VerificationState.HEALTH_VERIFIED, is_public=True,
        )
        response = self.client.get(self.url)
        self.assertContains(response, "Hip &amp; elbow health")
        self.assertContains(response, "Normal hips")
        self.assertContains(response, "Normal elbows")
        self.assertContains(response, "HD-A")
        self.assertContains(response, "ED-0")
        self.assertContains(response, 'class="orthopaedic-compact-row"', count=2)
        self.assertNotContains(response, "Not verified")
        self.assertNotContains(response, "X-ray screening found no signs")
        self.assertNotContains(response, "orthopaedic-health-card")
        record.refresh_from_db()
        self.assertEqual((record.test_type, record.result), ("HDA ED0", "Certified"))

    def test_unverified_entry_never_says_verified(self):
        HealthRecord.objects.create(
            dog=self.dog, test_type="ED0", result="Recorded",
            verification_state=VerificationState.COMMUNITY, is_public=True,
        )
        response = self.client.get(self.url)
        self.assertContains(response, "Normal elbows")
        self.assertNotContains(response, "Not verified")
        self.assertNotContains(response, "Health/DNA verified")

    def test_actual_legacy_pedigree_health_summary_is_easy_to_read_and_not_falsely_verified(self):
        # Matches the existing public dog-profile screenshot exactly.
        source = HealthRecord.objects.create(
            dog=self.dog,
            test_type="Legacy health summary",
            result="HD A · ED 0 (as shown on supplied pedigree)",
            verification_state=VerificationState.COMMUNITY,
            is_public=True,
        )
        response = self.client.get(self.url)
        self.assertContains(response, "Hip &amp; elbow health")
        self.assertContains(response, "Normal hips")
        self.assertContains(response, "Normal elbows")
        self.assertNotContains(response, "Not verified")
        self.assertContains(response, "HD-A")
        self.assertContains(response, "ED-0")
        self.assertContains(response, 'class="orthopaedic-compact-row"', count=2)
        self.assertNotContains(response, "The X-ray screening found no signs")
        self.assertNotContains(response, "Source: supplied pedigree")
        self.assertNotContains(response, "orthopaedic-health-card")
        self.assertNotContains(response, "Legacy health summary")
        source.refresh_from_db()
        self.assertEqual(source.result, "HD A · ED 0 (as shown on supplied pedigree)")

    def test_private_results_still_have_no_public_card(self):
        HealthRecord.objects.create(
            dog=self.dog, test_type="HDA ED0", result="Recorded",
            verification_state=VerificationState.HEALTH_VERIFIED, is_public=False,
        )
        response = self.client.get(self.url)
        self.assertContains(response, "No available records")
        self.assertNotContains(response, "Normal hips")
        self.assertNotContains(response, "Normal elbows")

    def test_unknown_grades_keep_source_text_in_other_health_section(self):
        HealthRecord.objects.create(
            dog=self.dog, test_type="HD unknown", result="ED pending",
            verification_state=VerificationState.HEALTH_VERIFIED, is_public=True,
        )
        response = self.client.get(self.url)
        self.assertContains(response, "Other health results")
        self.assertContains(response, "HD unknown")
        self.assertContains(response, "ED pending")
        self.assertNotContains(response, "orthopaedic-compact-row")
