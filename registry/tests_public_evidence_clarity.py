"""Public pedigree research must explain evidence status without inventing verification."""
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, DogSource, VerificationState


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
        self.assertContains(response, "Source attribution on file")
        self.assertContains(response, "not proof")

    def test_no_imported_source_shows_missing_evidence_not_invented_document(self):
        dog = Dog.objects.create(
            name="Missing Evidence", slug="missing-evidence", is_public=True
        )
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertContains(response, "No source attribution recorded")
        self.assertContains(response, "Not independently verified")
