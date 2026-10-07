from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from registry.models import Dog, DogImage, DogSource, Kennel, KennelMembership, ModerationRoleAssignment, Submission

from .models import PaymentSubmissionLink, SubmissionPayment
from registry.services import approve_submission


class MemberAccessFlowTests(TestCase):
    def setUp(self):
        self.reviewer = get_user_model().objects.create_user(
            username="reviewer"
        )
        ModerationRoleAssignment.objects.create(
            user=self.reviewer,
            role=ModerationRoleAssignment.Role.REVIEWER,
        )

    def test_signup_uses_kennel_identity_and_email_login(self):
        response = self.client.post(
            reverse("accounts:signup"),
            {
                "kennel_name": "New Member Kennels",
                "email": "member@example.com",
                "password1": "Strong-pass-12345",
                "password2": "Strong-pass-12345",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        user = get_user_model().objects.get(email="member@example.com")
        self.assertEqual(user.username, "new-member-kennels")
        self.assertEqual(user.profile.display_name, "New Member Kennels")
        self.assertTrue(
            Submission.objects.filter(
                submitted_by=user,
                kind=Submission.Kind.KENNEL_CREATE,
                status=Submission.Status.PENDING,
            ).exists()
        )

        self.client.logout()
        login_response = self.client.post(
            reverse("login"),
            {"username": "member@example.com", "password": "Strong-pass-12345"},
        )
        self.assertRedirects(login_response, reverse("dashboard"))

    def test_paid_dog_is_private_until_admin_approval_then_member_can_view_pedigree(self):
        member = get_user_model().objects.create_user(
            username="dog-member",
            email="dog-member@example.com",
            password="test-pass-123",
        )
        kennel = Kennel.objects.create(
            name="Verified Member Kennel",
            slug="verified-member-kennel",
            verified_at=timezone.now(),
        )
        KennelMembership.objects.create(
            user=member,
            kennel=kennel,
            role=KennelMembership.Role.OWNER,
        )
        payment = SubmissionPayment.objects.create(
            user=member,
            kennel=kennel,
            package=SubmissionPayment.Package.SINGLE_DOG,
            dog_count=1,
            amount_kobo=50000,
            reference="CCA-member-access",
            status=SubmissionPayment.Status.PAID,
            paid_at=timezone.now(),
        )
        submission = Submission.objects.create(
            kind=Submission.Kind.DOG,
            submitted_by=member,
            kennel=kennel,
            payload={
                "_paid_submission": True,
                "name": "Member Dog",
                "sex": Dog.Sex.MALE,
                "photo_caption": "Stacked portrait",
                "photo_sha256": "abc123",
            },
            attachment="submissions/2026/10/member-dog.jpg",
        )
        PaymentSubmissionLink.objects.create(
            payment=payment,
            submission=submission,
            slot_kind=PaymentSubmissionLink.SlotKind.DOG,
        )

        self.assertFalse(Dog.objects.filter(name="Member Dog").exists())
        self.assertEqual(submission.status, Submission.Status.PENDING)

        approve_submission(submission, self.reviewer, "Facts checked.")
        submission.refresh_from_db()
        self.assertTrue(submission.dog.is_public)
        image = DogImage.objects.get(dog=submission.dog)
        self.assertEqual(image.image.name, "submissions/2026/10/member-dog.jpg")
        self.assertEqual(image.caption, "Stacked portrait")
        self.assertTrue(image.is_primary)

        self.client.force_login(member)
        pedigree = self.client.get(
            reverse("accounts:member-pedigree", args=[submission.dog.pk])
        )
        self.assertContains(pedigree, "Member Dog")


    def test_paid_dog_form_accepts_first_profile_photo_in_same_submission(self):
        member = get_user_model().objects.create_user(
            username="photo-form-member",
            email="photo-form@example.com",
            password="test-pass-123",
        )
        kennel = Kennel.objects.create(
            name="Photo Form Kennel",
            slug="photo-form-kennel",
            verified_at=timezone.now(),
        )
        KennelMembership.objects.create(
            user=member,
            kennel=kennel,
            role=KennelMembership.Role.OWNER,
        )
        payment = SubmissionPayment.objects.create(
            user=member,
            kennel=kennel,
            package=SubmissionPayment.Package.SINGLE_DOG,
            dog_count=1,
            amount_kobo=50000,
            reference="CCA-photo-form",
            status=SubmissionPayment.Status.PAID,
            paid_at=timezone.now(),
        )
        self.client.force_login(member)

        response = self.client.get(
            reverse("accounts:payment-submit-dog", args=[payment.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertContains(response, 'name="primary_photo"')
        self.assertContains(response, "first profile photo")


    def test_existing_dog_photo_form_shows_target_profile_and_current_photo(self):
        member = get_user_model().objects.create_user(
            username="target-photo-member",
            password="test-pass-123",
        )
        kennel = Kennel.objects.create(
            name="Target Photo Kennel",
            slug="target-photo-kennel",
        )
        KennelMembership.objects.create(
            user=member,
            kennel=kennel,
            role=KennelMembership.Role.OWNER,
        )
        dog = Dog.objects.create(
            name="Target Photo Dog",
            slug="target-photo-dog",
            kennel=kennel,
            is_public=True,
        )
        DogImage.objects.create(
            dog=dog,
            image="dogs/target-photo-dog.jpg",
            is_primary=True,
        )
        self.client.force_login(member)

        response = self.client.get(
            reverse("accounts:submit-image", args=[dog.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You are updating")
        self.assertContains(response, "Target Photo Dog")
        self.assertContains(response, "/media/dogs/target-photo-dog.jpg")
        self.assertContains(response, "View current profile")

    def test_existing_dog_photo_form_uses_public_source_photo_fallback(self):
        member = get_user_model().objects.create_user(
            username="source-photo-member",
            password="test-pass-123",
        )
        kennel = Kennel.objects.create(
            name="Source Photo Kennel",
            slug="source-photo-kennel",
        )
        KennelMembership.objects.create(
            user=member,
            kennel=kennel,
            role=KennelMembership.Role.OWNER,
        )
        dog = Dog.objects.create(
            name="Source Photo Dog",
            slug="source-photo-dog",
            kennel=kennel,
            is_public=True,
        )
        source_url = (
            "https://www.canecorsopedigree.com/"
            "static/images/animal/123/source-photo.jpg"
        )
        DogSource.objects.create(
            dog=dog,
            source_type=DogSource.SourceType.PEDIGREE,
            title="Archived pedigree source",
            raw_payload={"image_url": source_url},
        )
        self.client.force_login(member)

        response = self.client.get(
            reverse("accounts:submit-image", args=[dog.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, source_url)
        self.assertNotContains(response, "No approved photo yet")
        self.assertContains(
            response,
            'accept="image/jpeg,.jpg,.jpeg,.jpe,.jfif,image/png,image/webp,image/heic,image/heif,.heic,.heif,.hif"',
            html=False,
        )

    def test_photo_storage_failure_returns_form_error_instead_of_500(self):
        member = get_user_model().objects.create_user(
            username="upload-error-member",
            password="test-pass-123",
        )
        kennel = Kennel.objects.create(
            name="Upload Error Kennel",
            slug="upload-error-kennel",
        )
        KennelMembership.objects.create(
            user=member,
            kennel=kennel,
            role=KennelMembership.Role.OWNER,
        )
        dog = Dog.objects.create(
            name="Upload Error Dog",
            slug="upload-error-dog",
            kennel=kennel,
            is_public=True,
        )
        buffer = BytesIO()
        Image.new("RGB", (3, 3)).save(buffer, format="JPEG")
        photo = SimpleUploadedFile(
            "dog.jpg",
            buffer.getvalue(),
            content_type="image/jpeg",
        )
        self.client.force_login(member)
        storage = Submission._meta.get_field("attachment").storage

        with patch.object(storage, "save", side_effect=OSError("gateway unavailable")):
            response = self.client.post(
                reverse("accounts:submit-image", args=[dog.pk]),
                {
                    "caption": "Portrait",
                    "is_primary": "on",
                    "notes": "",
                    "attachment": photo,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The file could not be stored right now")
        self.assertFalse(
            Submission.objects.filter(
                kind=Submission.Kind.IMAGE,
                dog=dog,
            ).exists()
        )


class PopularDogTests(TestCase):
    def test_homepage_uses_search_originated_popularity(self):
        kennel = Kennel.objects.create(name="Popular Kennel", slug="popular-kennel")
        popular = Dog.objects.create(
            name="Popular Dog", slug="popular-dog", kennel=kennel, is_public=True
        )
        same_kennel = Dog.objects.create(
            name="Second Kennel Dog",
            slug="second-kennel-dog",
            kennel=kennel,
            is_public=True,
        )
        DogImage.objects.create(
            dog=popular,
            image="dogs/popular-dog.jpg",
            is_primary=True,
        )
        DogImage.objects.create(
            dog=same_kennel,
            image="dogs/second-kennel-dog.jpg",
            is_primary=True,
        )

        self.client.get(
            reverse("registry:dog-detail", args=[popular.slug]),
            {"source": "search"},
        )
        popular.refresh_from_db()
        self.assertEqual(popular.search_count, 1)

        featured = list(self.client.get(reverse("home")).context["featured_dogs"])
        self.assertEqual(featured[0], popular)
        self.assertNotIn(same_kennel, featured)
