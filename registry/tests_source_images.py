from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, DogSource, VerificationState


class CaneCorsoSourceImageFallbackTests(TestCase):
    def test_public_dog_uses_archived_source_image_url_when_no_local_image_exists(self):
        dog = Dog.objects.create(
            name="Image Dog",
            slug="image-dog",
            sex=Dog.Sex.MALE,
            verification_state=VerificationState.SOURCE_ATTACHED,
            is_public=True,
        )
        DogSource.objects.create(
            dog=dog,
            source_type=DogSource.SourceType.PEDIGREE,
            title="CaneCorsoPedigree.com archive (2026-09-15)",
            source_url="https://www.canecorsopedigree.com/view_dog?id=123",
            raw_payload={
                "image_url": "https://www.canecorsopedigree.com/static/images/animal/123.jpg"
            },
        )

        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))

        self.assertContains(
            response,
            'src="https://www.canecorsopedigree.com/static/images/animal/123.jpg"',
            html=False,
        )
        self.assertContains(response, "Image from source record")

    def test_untrusted_external_image_url_is_not_rendered(self):
        dog = Dog.objects.create(
            name="Unsafe Image Dog",
            slug="unsafe-image-dog",
            verification_state=VerificationState.SOURCE_ATTACHED,
            is_public=True,
        )
        DogSource.objects.create(
            dog=dog,
            source_type=DogSource.SourceType.PEDIGREE,
            title="Imported source",
            source_url="https://www.canecorsopedigree.com/view_dog?id=124",
            raw_payload={"image_url": "https://example.com/not-approved.jpg"},
        )

        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))

        self.assertNotContains(response, "https://example.com/not-approved.jpg")
