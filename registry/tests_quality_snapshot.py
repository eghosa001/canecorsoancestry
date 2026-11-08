"""Safety tests for the read-only published data-quality report."""
from django.test import TestCase
from django.utils import timezone

from registry.management.commands.report_data_quality import quality_snapshot
from registry.models import Dog, DogImage, DogSource, VerificationState


class QualitySnapshotTests(TestCase):
    def test_report_excludes_private_dogs_and_separates_source_review(self):
        published = Dog.objects.create(
            name="Public Quality Dog", slug="public-quality-dog", is_public=True,
            verification_state=VerificationState.SOURCE_ATTACHED,
        )
        hidden = Dog.objects.create(
            name="Private Quality Dog", slug="private-quality-dog", is_public=False,
            verification_state=VerificationState.PEDIGREE_REVIEWED,
        )
        DogImage.objects.create(dog=published, image="dogs/public.jpg")
        DogImage.objects.create(dog=hidden, image="dogs/private.jpg")
        DogSource.objects.create(
            dog=published, source_type=DogSource.SourceType.PEDIGREE,
            title="Imported archive", source_url="https://example.org/archive",
        )
        DogSource.objects.create(
            dog=hidden, source_type=DogSource.SourceType.PEDIGREE,
            title="Private report", source_url="https://example.org/private",
            verified_at=timezone.now(),
        )
        report = quality_snapshot()
        self.assertEqual(report["public_dogs"], 1)
        self.assertEqual(report["with_managed_photo"], 1)
        self.assertEqual(report["with_source_url_or_document"], 1)
        self.assertEqual(report["with_timestamped_reviewed_source"], 0)
        self.assertEqual(report["with_reviewed_dog_status"], 0)
        self.assertEqual(report["with_any_recorded_parent"], 0)

    def test_report_counts_reviewed_source_separately_from_dog_status(self):
        dog = Dog.objects.create(
            name="Reviewed Quality Dog", slug="reviewed-quality-dog", is_public=True,
            verification_state=VerificationState.COMMUNITY,
        )
        DogSource.objects.create(
            dog=dog, source_type=DogSource.SourceType.PEDIGREE,
            title="Reviewed pedigree source", source_url="https://example.org/pedigree",
            verified_at=timezone.now(),
        )
        report = quality_snapshot()
        self.assertEqual(report["with_timestamped_reviewed_source"], 1)
        self.assertEqual(report["with_reviewed_dog_status"], 0)
