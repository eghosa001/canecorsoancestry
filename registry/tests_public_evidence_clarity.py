"""Public profiles keep verification clear but hide internal provenance labels."""
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, DogImage, DogSource, VerificationState


class PublicEvidenceClarityTests(TestCase):
    def test_unreviewed_public_dog_is_not_described_as_verified(self):
        dog = Dog.objects.create(
            name="Unreviewed Ancestry", slug="unreviewed-ancestry",
            is_public=True, verification_state=VerificationState.SOURCE_ATTACHED,
        )
        DogSource.objects.create(
            dog=dog, source_type=DogSource.SourceType.PEDIGREE,
            title="Imported pedigree listing",
        )
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Not independently verified")
        self.assertContains(response, 'class="profile-evidence-summary"')
        self.assertNotContains(response, "Source attribution on file")
        self.assertNotContains(response, "Imported pedigree listing")
        self.assertNotContains(response, "About COI &amp; sources")

    def test_no_imported_source_does_not_display_internal_source_status(self):
        dog = Dog.objects.create(
            name="Missing Evidence", slug="missing-evidence", is_public=True
        )
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertNotContains(response, "No source attribution recorded")
        self.assertContains(response, "Not independently verified")

    def test_imported_photo_source_caption_is_not_public(self):
        dog = Dog.objects.create(
            name="Fedor", slug="fedor-public-photo", is_public=True,
        )
        caption = "Archived source photo · CaneCorsoPedigree.com · Snapshot 2026-09-15"
        image = DogImage.objects.create(
            dog=dog, image="dogs/fedor-archive.jpg",
            is_primary=True, caption=caption,
        )
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dogs/fedor-archive.jpg")
        self.assertContains(response, "Photo 1")
        self.assertNotContains(response, "Archived source photo")
        self.assertNotContains(response, "CaneCorsoPedigree.com")
        self.assertNotContains(response, "Snapshot 2026-09-15")
        self.assertEqual(image.caption, caption)  # Retain for internal review.
