from django.contrib.auth import get_user_model
from django.test import TestCase

from core.media_views import _can_read_media
from registry.models import (
    DisputeCase,
    Dog,
    DogDocument,
    DogImage,
    Kennel,
    KennelMembership,
    Submission,
)


class CloudflareMediaAccessTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.other = User.objects.create_user(username="other", password="pass")
        self.staff = User.objects.create_user(
            username="staff",
            password="pass",
            is_staff=True,
        )
        self.kennel = Kennel.objects.create(name="Test Kennel", slug="test-kennel")
        KennelMembership.objects.create(
            kennel=self.kennel,
            user=self.owner,
            role=KennelMembership.Role.OWNER,
        )
        self.dog = Dog.objects.create(
            name="Private Dog",
            slug="private-dog",
            kennel=self.kennel,
            is_public=False,
        )

    def test_public_dog_image_is_publicly_readable(self):
        self.dog.is_public = True
        self.dog.save(update_fields=["is_public"])
        DogImage.objects.create(dog=self.dog, image="dogs/public.jpg")
        self.assertEqual(
            _can_read_media(self.other, "dogs/public.jpg"),
            (True, True),
        )

    def test_private_document_is_limited_to_member_or_staff(self):
        DogDocument.objects.create(
            dog=self.dog,
            title="Private pedigree",
            file="documents/private.pdf",
            submitted_by=self.owner,
            is_public=False,
        )
        self.assertEqual(
            _can_read_media(self.owner, "documents/private.pdf"),
            (True, False),
        )
        self.assertEqual(
            _can_read_media(self.other, "documents/private.pdf"),
            (False, False),
        )
        self.assertEqual(
            _can_read_media(self.staff, "documents/private.pdf"),
            (True, False),
        )

    def test_submission_attachment_is_not_public(self):
        Submission.objects.create(
            kind=Submission.Kind.DOCUMENT,
            submitted_by=self.owner,
            dog=self.dog,
            kennel=self.kennel,
            attachment="submissions/evidence.pdf",
        )
        self.assertEqual(
            _can_read_media(self.owner, "submissions/evidence.pdf"),
            (True, False),
        )
        self.assertEqual(
            _can_read_media(self.other, "submissions/evidence.pdf"),
            (False, False),
        )

    def test_dispute_attachment_is_owner_or_staff_only(self):
        DisputeCase.objects.create(
            dog=self.dog,
            opened_by=self.owner,
            reason=DisputeCase.Reason.PEDIGREE,
            details="Review this.",
            attachment="disputes/review.pdf",
        )
        self.assertEqual(
            _can_read_media(self.owner, "disputes/review.pdf"),
            (True, False),
        )
        self.assertEqual(
            _can_read_media(self.other, "disputes/review.pdf"),
            (False, False),
        )
