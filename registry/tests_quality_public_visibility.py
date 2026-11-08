"""Data quality public metrics use the same visibility rule as the website."""
from django.test import TestCase
from django.utils import timezone

from registry.data_quality import public_coi_review_sample, quick_quality_report
from registry.models import Dog, DogSource, Kennel, VerificationState


class PublishedQualityVisibilityTests(TestCase):
    def test_only_truly_visible_dogs_affect_public_quality_counts(self):
        visible = Dog.objects.create(
            name="Visible Quality Dog", slug="visible-quality",
            is_public=True, verification_state=VerificationState.IDENTITY_REVIEWED,
        )
        mod_hidden = Dog.objects.create(
            name="Moderation Hidden Quality", slug="mod-hidden-quality",
            is_public=True, hidden_by_moderation=True,
        )
        private = Dog.objects.create(
            name="Private Quality", slug="private-quality", is_public=False,
        )
        kennel = Kennel.objects.create(
            name="Hidden Kennel Quality", slug="hidden-kennel-quality",
            hide_dogs=True,
        )
        kennel_hidden = Dog.objects.create(
            name="Kennel Hidden Quality", slug="kennel-hidden-quality",
            kennel=kennel, is_public=True,
        )
        # Review metadata on suppressed records must not inflate the public
        # documentation ratio or be rendered as an evidence-review sample.
        for dog in (visible, mod_hidden, private, kennel_hidden):
            DogSource.objects.create(
                dog=dog, title="Archive",
                source_type=DogSource.SourceType.PEDIGREE,
                source_url="https://example.test/archive",
                verified_at=timezone.now(),
            )
        report = quick_quality_report()
        counts = report["counts"]
        self.assertEqual(counts["public_dogs"], 1)
        self.assertEqual(counts["source_backed_public"], 1)
        self.assertEqual(counts["verified_source_backed_public"], 1)
        self.assertEqual(counts["public_without_sources"], 0)
        self.assertEqual(counts["community_only_public"], 0)
        self.assertEqual(report["source_coverage_percent"], 100.0)
        self.assertEqual(report["verified_source_coverage_percent"], 100.0)

    def test_public_issue_samples_exclude_suppressed_records(self):
        visible = Dog.objects.create(
            name="Visible Missing Source", slug="visible-missing-source",
            is_public=True, sex=Dog.Sex.UNKNOWN,
        )
        Dog.objects.create(
            name="Hidden Missing Source", slug="hidden-missing-source",
            is_public=True, hidden_by_moderation=True, sex=Dog.Sex.UNKNOWN,
        )
        report = quick_quality_report(sample_limit=12)
        self.assertEqual(report["counts"]["public_without_sources"], 1)
        self.assertEqual(report["counts"]["unknown_sex_public"], 1)
        self.assertEqual(
            [d.pk for d in report["samples"]["public_without_sources"]],
            [visible.pk],
        )
        self.assertEqual(
            [d.pk for d in report["samples"]["unknown_sex_public"]],
            [visible.pk],
        )

    def test_suppressed_parent_not_counted_as_publicly_linked_parent(self):
        sire = Dog.objects.create(
            name="Suppressed Sire", slug="suppressed-sire-quality",
            sex=Dog.Sex.MALE, is_public=True, hidden_by_moderation=True,
        )
        dam = Dog.objects.create(
            name="Visible Dam", slug="visible-dam-quality",
            sex=Dog.Sex.FEMALE, is_public=True,
        )
        Dog.objects.create(
            name="Public Child With Hidden Sire", slug="public-child-hidden-sire",
            is_public=True, sire=sire, dam=dam,
        )
        report = quick_quality_report()
        self.assertEqual(report["counts"]["both_parents_public"], 0)
        self.assertEqual(report["counts"]["pedigree_linked_public"], 1)
        self.assertEqual(public_coi_review_sample(), [])

    def test_public_coi_sample_excludes_moderation_hidden_subject(self):
        sire = Dog.objects.create(
            name="Public Father", slug="quality-public-father", is_public=True,
            sex=Dog.Sex.MALE,
        )
        dam = Dog.objects.create(
            name="Public Mother", slug="quality-public-mother", is_public=True,
            sex=Dog.Sex.FEMALE,
        )
        public_child = Dog.objects.create(
            name="Public COI Child", slug="public-coi-child-quality",
            is_public=True, sire=sire, dam=dam,
        )
        hidden_child = Dog.objects.create(
            name="Suppressed COI Child", slug="suppressed-coi-child-quality",
            is_public=True, hidden_by_moderation=True,
            sire=sire, dam=dam,
        )
        rows = public_coi_review_sample(limit=10)
        self.assertIn(public_child.pk, [row["dog"].pk for row in rows])
        self.assertNotIn(hidden_child.pk, [row["dog"].pk for row in rows])
