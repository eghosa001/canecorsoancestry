"""Match only evidence-backed ancestor identities; never alter the database."""
from django.core.management import call_command
from django.test import TestCase

from registry.coi_identity_audit import audit_registration_backed_duplicates
from registry.models import Dog, DogExternalKey, DogRegistration, DogSource


class COIDuplicateAuditTests(TestCase):
    def setUp(self):
        sire = Dog.objects.create(
            name="Archive Grandfather", slug="audit-grandfather", is_public=True,
        )
        dam = Dog.objects.create(
            name="Archive Grandmother", slug="audit-grandmother", is_public=True,
        )
        self.canonical = Dog.objects.create(
            name="Tocco Of Revenge Della Valle Dei Lord",
            slug="audit-bellissimo-tocco",
            sex=Dog.Sex.MALE, is_public=True,
        )
        self.archive = Dog.objects.create(
            name="TOCCO OF REVENGE DELLA VALLE DEI LORD",
            slug="audit-ccp-tocco",
            sex=Dog.Sex.MALE, is_public=True,
            sire=sire, dam=dam,
        )
        DogExternalKey.objects.create(
            dog=self.canonical, namespace="bellissimo-geni", key="audit-tocco",
        )
        DogExternalKey.objects.create(
            dog=self.archive, namespace="canecorsopedigree.com", key="27801",
        )
        DogRegistration.objects.create(
            dog=self.canonical, number="ROI 12/152913",
        )
        self.source = DogSource.objects.create(
            dog=self.archive, title="Archive",
            source_type=DogSource.SourceType.PEDIGREE,
            raw_payload={"pedigree_number": "LO12152913"},
        )

    def test_registration_and_full_name_allow_review_candidate(self):
        result = audit_registration_backed_duplicates()
        self.assertEqual(result["counts"], {
            "ready": 1, "needs_review": 0, "matched": 1
        })
        self.assertEqual(result["candidates"][0]["canonical_slug"],
                         self.canonical.slug)
        self.assertEqual(result["candidates"][0]["source_slug"], self.archive.slug)

    def test_read_only_report_preserves_all_parent_and_source_records(self):
        call_command("audit_coi_duplicate_candidates", limit=10)
        self.canonical.refresh_from_db()
        self.assertIsNone(self.canonical.sire_id)
        self.assertTrue(Dog.objects.filter(pk=self.archive.pk).exists())

    def test_disagreeing_registration_is_not_a_match(self):
        self.source.raw_payload = {"pedigree_number": "LO99999999"}
        self.source.save(update_fields=["raw_payload"])
        self.assertEqual(audit_registration_backed_duplicates()["counts"]["matched"], 0)

    def test_different_sex_is_not_a_match(self):
        Dog.objects.filter(pk=self.archive.pk).update(sex=Dog.Sex.FEMALE)
        self.assertEqual(audit_registration_backed_duplicates()["counts"]["matched"], 0)

    def test_ambiguous_name_not_a_match(self):
        Dog.objects.filter(pk=self.archive.pk).update(name="Another Tocco")
        self.assertEqual(audit_registration_backed_duplicates()["counts"]["matched"], 0)

    def test_conflicting_birth_dates_require_review(self):
        Dog.objects.filter(pk=self.canonical.pk).update(date_of_birth="2011-01-01")
        Dog.objects.filter(pk=self.archive.pk).update(date_of_birth="2012-01-01")
        result = audit_registration_backed_duplicates()
        self.assertEqual(result["counts"]["ready"], 0)
        self.assertEqual(result["counts"]["needs_review"], 1)

    def test_already_reconciled_record_is_not_relisted(self):
        DogExternalKey.objects.filter(dog=self.archive).update(dog=self.canonical)
        self.source.dog = self.canonical
        self.source.save(update_fields=["dog"])
        self.archive.delete()
        self.assertEqual(audit_registration_backed_duplicates()["counts"]["matched"], 0)

    def test_unpublished_record_is_never_reported(self):
        Dog.objects.filter(pk=self.archive.pk).update(is_public=False)
        self.assertEqual(audit_registration_backed_duplicates()["counts"]["matched"], 0)

    def test_capped_results_do_not_change_totals(self):
        report = audit_registration_backed_duplicates(max_display=0)
        self.assertEqual(len(report["candidates"]), 0)
        self.assertEqual(report["counts"]["matched"], 1)
