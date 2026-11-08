"""Published-only evidence triage: selection, ranking and non-mutation."""
from django.test import TestCase
from django.utils import timezone

from registry.management.commands.audit_evidence_review_queue import evidence_review_triage
from registry.models import Dog, DogSource, VerificationState


class EvidenceReviewTriageTests(TestCase):
    def test_public_worklist_excludes_private_hidden_and_kennel_hidden(self):
        source = Dog.objects.create(
            name="Needs Review", slug="needs-review", is_public=True, search_count=99,
        )
        hidden = Dog.objects.create(
            name="Hidden", slug="hidden-worklist", is_public=True,
            hidden_by_moderation=True, search_count=100,
        )
        private = Dog.objects.create(
            name="Private", slug="private-worklist", is_public=False, search_count=101,
        )
        for dog in (source, hidden, private):
            DogSource.objects.create(
                dog=dog, source_type=DogSource.SourceType.PEDIGREE,
                title="Archive", source_url="https://example.org/dog",
            )
        out = evidence_review_triage(include_public_slugs=True)
        self.assertEqual(out["unreviewed_with_source"]["total"], 1)
        self.assertEqual(
            out["unreviewed_with_source"]["public_candidates"],
            [{"slug": source.slug, "search_count": 99}],
        )
        self.assertNotIn("hidden-worklist", str(out))
        self.assertNotIn("private-worklist", str(out))

    def test_prioritizes_popular_missing_evidence_and_preserves_dog_status(self):
        low = Dog.objects.create(
            name="Low", slug="low-worklist", is_public=True, search_count=1,
        )
        high = Dog.objects.create(
            name="High", slug="high-worklist", is_public=True, search_count=50,
        )
        out = evidence_review_triage(limit=1, include_public_slugs=True)
        self.assertEqual(out["unreviewed_without_source"]["total"], 2)
        self.assertEqual(
            out["unreviewed_without_source"]["public_candidates"][0]["slug"],
            high.slug,
        )
        self.assertEqual(low.verification_state, VerificationState.COMMUNITY)
        self.assertEqual(high.verification_state, VerificationState.COMMUNITY)

    def test_reviewed_state_without_source_is_followup_not_revocation(self):
        dog = Dog.objects.create(
            name="Previously Reviewed", slug="reviewed-worklist", is_public=True,
            verification_state=VerificationState.PEDIGREE_REVIEWED,
        )
        out = evidence_review_triage(include_public_slugs=True)
        self.assertEqual(out["reviewed_status_without_timestamped_dogsource"]["total"], 1)
        self.assertEqual(out["unreviewed_without_source"]["total"], 0)
        dog.refresh_from_db()
        self.assertEqual(dog.verification_state, VerificationState.PEDIGREE_REVIEWED)

    def test_timestamped_review_source_not_misclassified(self):
        dog = Dog.objects.create(
            name="Reviewed Source", slug="reviewed-source-worklist", is_public=True,
            verification_state=VerificationState.IDENTITY_REVIEWED,
        )
        DogSource.objects.create(
            dog=dog, source_type=DogSource.SourceType.PEDIGREE,
            title="Reviewed evidence", source_url="https://example.org/evidence",
            verified_at=timezone.now(),
        )
        out = evidence_review_triage(include_public_slugs=True)
        self.assertEqual(out["reviewed_status_without_timestamped_dogsource"]["total"], 0)

    def test_default_report_exposes_no_slugs(self):
        Dog.objects.create(name="Named", slug="named-worklist", is_public=True)
        out = evidence_review_triage()
        self.assertNotIn("named-worklist", str(out))
        self.assertNotIn("public_candidates", str(out))

    def test_invalid_or_unbounded_limit_rejected(self):
        for invalid in (-1, 0, 101, "10"):
            with self.subTest(limit=invalid), self.assertRaises(ValueError):
                evidence_review_triage(invalid)
