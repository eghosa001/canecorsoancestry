"""Public profiles keep verification clear but hide internal provenance labels."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from registry.models import Dog, DogImage, DogSource, DogTitle, VerificationState


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
        self.assertNotContains(response, "Not independently verified")
        self.assertNotContains(response, 'class="profile-evidence-summary"')
        self.assertNotContains(response, "Source attribution on file")
        self.assertNotContains(response, "Imported pedigree listing")
        self.assertNotContains(response, "About COI &amp; sources")

    def test_no_imported_source_does_not_display_internal_source_status(self):
        dog = Dog.objects.create(
            name="Missing Evidence", slug="missing-evidence", is_public=True
        )
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertNotContains(response, "No source attribution recorded")
        self.assertNotContains(response, "Not independently verified")

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
        self.assertEqual(image.public_caption, "")

    def test_real_photo_description_stays_visible(self):
        dog = Dog.objects.create(
            name="Portrait Dog", slug="portrait-dog", is_public=True,
        )
        image = DogImage.objects.create(
            dog=dog, image="dogs/portrait.jpg",
            caption="Side portrait", is_primary=True,
        )
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertEqual(image.public_caption, "Side portrait")
        self.assertContains(response, "Side portrait")

    def test_profile_shows_only_populated_biography_and_title_panels(self):
        titled = Dog.objects.create(
            name="Titled Without Bio", slug="titled-without-bio",
            is_public=True, bio="", bloodline="",
        )
        DogTitle.objects.create(dog=titled, name="National Champion")
        response = self.client.get(reverse("registry:dog-detail", args=[titled.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "National Champion")
        self.assertContains(response, '<h2>Titles</h2>', html=True)
        self.assertNotContains(response, '<h2>About</h2>', html=True)
        self.assertNotContains(response, "No public biography has been recorded")
        self.assertNotContains(response, "<dt>Bloodline</dt>")

        described = Dog.objects.create(
            name="Described Without Titles", slug="described-without-titles",
            is_public=True, bio="Calm, well-documented ancestry.",
        )
        response = self.client.get(reverse("registry:dog-detail", args=[described.slug]))
        self.assertContains(response, "Calm, well-documented ancestry.")
        self.assertContains(response, '<h2>About</h2>', html=True)
        self.assertNotContains(response, '<h2>Titles</h2>', html=True)
        self.assertNotContains(response, "No titles recorded.")

    def test_imported_boilerplate_is_staff_only_and_does_not_erase_bio(self):
        source_note = "Verified from Tessa Sangue Magnifica’s supplied pedigree."
        dog = Dog.objects.create(
            name="Source Note Ancestor",
            slug="source-note-ancestor",
            is_public=True,
            bio=source_note,
        )
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, source_note)
        self.assertNotContains(response, '<h2>About</h2>', html=True)
        self.assertEqual(dog.bio, source_note)

        staff = get_user_model().objects.create_superuser(
            username="source-note-auditor",
            email="source-note-auditor@example.test",
            password="test-pass-123",
        )
        self.client.force_login(staff)
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, source_note)

    def test_real_biography_and_factual_coi_disclosure_remain_public(self):
        dog = Dog.objects.create(
            name="Real Biography",
            slug="real-biography",
            is_public=True,
            bio="Enjoys obedience training and lives with her breeder.",
        )
        response = self.client.get(reverse("registry:dog-detail", args=[dog.slug]))
        self.assertContains(response, dog.bio)
        self.assertContains(response, "<h2>About</h2>", html=True)
        self.assertNotContains(response, "pedigree intelligence")

