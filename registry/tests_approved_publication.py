"""End-to-end moderation publication: pending is private; final approval is visible.

Use the actual Django public URLs, templates, FileField media authorization and
review service. All files live in a temporary local test storage, never R2.
"""
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from registry.models import (
    Dog, DogDocument, DogIdentityNumber, DogImage, DogRegistration,
    HealthRecord, Kennel, Litter, ModerationRoleAssignment, Submission,
)
from registry.services import approve_submission


@patch("registry.services.verify_submission", return_value=[])
class ApprovedPublicContentTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        settings = override_settings(MEDIA_ROOT=self.tmp.name, MEDIA_EDGE_BASE_URL="")
        settings.enable()
        self.addCleanup(settings.disable)
        User = get_user_model()
        self.reviewer = User.objects.create_user(username="publication-reviewer")
        ModerationRoleAssignment.objects.create(
            user=self.reviewer, role=ModerationRoleAssignment.Role.REVIEWER,
        )
        self.member = User.objects.create_user(username="publication-member")
        self.kennel = Kennel.objects.create(name="Publication Kennel", slug="publication-kennel")
        self.dog = Dog.objects.create(
            name="Publication Dog", slug="publication-dog", sex=Dog.Sex.MALE,
            kennel=self.kennel, is_public=True, colour="Black",
        )

    def upload(self, name="approved-test-image.jpg"):
        return SimpleUploadedFile(name, b"approved-image-test-content", content_type="image/jpeg")

    def submission(self, kind, *, dog=None, attachment=None, payload=None, **fields):
        values = {
            "kind": kind, "submitted_by": self.member,
            "dog": self.dog if dog is None else dog,
            "kennel": self.kennel, "payload": payload or {},
            **fields,
        }
        if attachment is not None:
            values["attachment"] = attachment
        return Submission.objects.create(**values)

    def approve(self, submission):
        with self.captureOnCommitCallbacks(execute=True):
            approve_submission(submission, self.reviewer, "Reviewed supporting evidence")
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.APPROVED)
        self.assertEqual(submission.reviewed_by_id, self.reviewer.id)
        return submission

    def profile(self, dog=None):
        return self.client.get(reverse("registry:dog-detail", args=[(dog or self.dog).slug]))

    def test_member_image_is_private_until_approval_then_main_photo_and_public_media(self, _verification):
        sub = self.submission(
            Submission.Kind.IMAGE, attachment=self.upload("new-main.jpg"),
            payload={"caption": "Verified new portrait", "is_primary": True},
        )
        image_path = "/media/" + sub.attachment.name
        self.assertEqual(self.client.get(image_path).status_code, 404)
        self.assertNotContains(self.profile(), "new-main", status_code=200)
        self.approve(sub)
        approved = DogImage.objects.get(dog=self.dog)
        self.assertTrue(approved.is_primary)
        self.assertEqual(approved.image.name, sub.attachment.name)
        self.assertContains(self.profile(), approved.image.url)
        media = self.client.get(approved.image.url)
        self.assertEqual(media.status_code, 200)
        self.assertTrue(media["Content-Type"].startswith("image/"))

    def test_missing_uploaded_photo_cannot_be_approved_or_made_public(self, _verification):
        sub = self.submission(
            Submission.Kind.IMAGE, attachment=self.upload("now-missing.jpg"),
            payload={"is_primary": True},
        )
        path = sub.attachment.name
        sub.attachment.storage.delete(path)
        with self.assertRaisesRegex(ValueError, "missing from media storage"):
            self.approve(sub)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Submission.Status.PENDING)
        self.assertFalse(DogImage.objects.filter(dog=self.dog).exists())
        self.assertEqual(self.client.get("/media/" + path).status_code, 404)

    def test_missing_new_dog_photo_blocks_approval_before_canonical_record_creation(self, _verification):
        sub = self.submission(
            Submission.Kind.DOG, attachment=self.upload("deleted-before-review.jpg"),
            payload={"name": "Must Remain Pending", "sex": Dog.Sex.MALE},
        )
        sub.attachment.storage.delete(sub.attachment.name)
        with self.assertRaisesRegex(ValueError, "missing from media storage"):
            self.approve(sub)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Submission.Status.PENDING)
        self.assertIsNone(sub.dog_id)
        self.assertFalse(Dog.objects.filter(name="Must Remain Pending").exists())

    def test_non_primary_approved_photo_enters_gallery_without_replacing_main(self, _verification):
        primary = DogImage.objects.create(dog=self.dog, image="dogs/main.jpg", is_primary=True)
        sub = self.submission(
            Submission.Kind.IMAGE, attachment=self.upload("second-photo.jpg"),
            payload={"caption": "Side portrait", "is_primary": False},
        )
        self.approve(sub)
        photos = list(DogImage.objects.filter(dog=self.dog))
        self.assertEqual(len(photos), 2)
        self.assertEqual(sum(photo.is_primary for photo in photos), 1)
        self.assertTrue(DogImage.objects.get(pk=primary.pk).is_primary)
        self.assertContains(self.profile(), "Side portrait")
        self.assertContains(self.profile(), sub.attachment.name)
        self.assertContains(self.client.get(reverse("registry:dog-search"), {"q": self.dog.name}), primary.image.name)

    def test_new_approved_dog_photo_and_registration_show_on_public_profile_and_search(self, _verification):
        sub = self.submission(
            Submission.Kind.DOG, attachment=self.upload("first-photo.jpg"),
            payload={
                "name": "Freshly Approved With Photo", "sex": Dog.Sex.FEMALE,
                "colour": "Blue", "country": "Nigeria",
                "registration": "PUBLIC-REG-01", "microchip_number": "CHIP-2026",
            },
        )
        self.assertFalse(Dog.objects.filter(name="Freshly Approved With Photo").exists())
        self.approve(sub)
        dog = sub.dog
        self.assertTrue(dog.is_public)
        photo = DogImage.objects.get(dog=dog)
        self.assertTrue(photo.is_primary)
        self.assertContains(self.profile(dog), "PUBLIC-REG-01")
        self.assertContains(self.profile(dog), "Blue")
        self.assertContains(self.profile(dog), photo.image.url)
        self.assertContains(self.client.get(reverse("registry:dog-search"), {"q": dog.name}), dog.name)
        self.assertTrue(DogIdentityNumber.objects.filter(
            dog=dog, kind=DogIdentityNumber.Kind.MICROCHIP,
        ).exists())

    def test_approved_correction_renders_name_colour_registration_and_parents(self, _verification):
        dam = Dog.objects.create(name="Published Dam", slug="published-dam", sex=Dog.Sex.FEMALE, is_public=True)
        sub = self.submission(Submission.Kind.CORRECTION, payload={
            "name": "Corrected Display Name", "colour": "Brindle",
            "registration": "CORRECT-REG-01", "dam_id": str(dam.pk),
            "bio": "Approved biographical details",
        })
        self.assertContains(self.profile(), "Publication Dog")
        self.approve(sub)
        page = self.profile()
        for value in ("Corrected Display Name", "Brindle", "CORRECT-REG-01",
                      "Published Dam", "Approved biographical details"):
            self.assertContains(page, value)
        self.assertEqual(self.dog.slug, "publication-dog")
        self.assertTrue(DogRegistration.objects.filter(
            dog=self.dog, number="CORRECT-REG-01",
        ).exists())

    def test_approved_health_is_public_but_attached_evidence_stays_private(self, _verification):
        sub = self.submission(
            Submission.Kind.HEALTH, attachment=self.upload("health-evidence.jpg"),
            payload={"test_type": "Hip screening", "result": "Clear", "evidence_type": "health"},
        )
        self.assertNotContains(self.profile(), "Hip screening")
        self.approve(sub)
        self.assertTrue(HealthRecord.objects.filter(dog=self.dog, test_type="Hip screening", result="Clear").exists())
        self.assertContains(self.profile(), "Hip screening")
        self.assertContains(self.profile(), "Clear")
        doc = DogDocument.objects.get(source_submission=sub)
        self.assertFalse(doc.is_public)
        self.assertEqual(self.client.get(doc.file.url).status_code, 404)
        self.assertNotContains(self.profile(), "supporting evidence")

    def test_approved_public_document_and_visibility_request_show_and_private_stays_hidden(self, _verification):
        sub = self.submission(
            Submission.Kind.DOCUMENT,
            attachment=self.upload("pedigree-evidence.pdf"),
            payload={"title": "Approved pedigree certificate",
                     "document_type": DogDocument.DocumentType.OTHER, "is_public": True},
        )
        self.assertNotContains(self.profile(), "Approved pedigree certificate")
        self.approve(sub)
        doc = DogDocument.objects.get(source_submission=sub)
        self.assertTrue(doc.is_public)
        self.assertContains(self.profile(), "Approved pedigree certificate")
        self.assertEqual(self.client.get(doc.file.url).status_code, 200)

        private = DogDocument.objects.create(
            dog=self.dog, title="Previously private document",
            file="submissions/private-evidence.pdf", is_public=False,
        )
        self.assertNotContains(self.profile(), "Previously private document")
        visibility = self.submission(
            Submission.Kind.DOCUMENT_VISIBILITY,
            document=private, payload={"is_public": True},
        )
        self.approve(visibility)
        self.assertContains(self.profile(), "Previously private document")

    def test_approved_kennel_update_and_litter_are_visible_after_review(self, _verification):
        update = self.submission(
            Submission.Kind.KENNEL, payload={"city": "Benin City", "country": "Nigeria"},
        )
        self.approve(update)
        self.assertContains(
            self.client.get(reverse("registry:kennel-detail", args=[self.kennel.slug])),
            "Benin City",
        )
        litter = self.submission(
            Submission.Kind.LITTER_CREATE,
            payload={"code": "PUB-LITTER-01", "country": "Nigeria"},
        )
        self.approve(litter)
        self.assertTrue(litter.litter.is_public)
        page = self.client.get(reverse("registry:litter-detail", args=[litter.litter.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "PUB-LITTER-01")
