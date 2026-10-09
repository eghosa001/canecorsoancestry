from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from core.r2_gateway_storage import CloudflareR2GatewayStorage
from registry.models import Dog, DogDocument, DogImage, DogSource, Kennel, KennelMembership, ModerationRoleAssignment, Submission

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
            attachment=SimpleUploadedFile(
                "member-dog.jpg", b"photo-fixture-data", content_type="image/jpeg",
            ),
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
        self.assertEqual(image.image.name, submission.attachment.name)
        self.assertEqual(image.caption, "Stacked portrait")
        self.assertTrue(image.is_primary)

        public_profile = self.client.get(
            reverse("registry:dog-detail", args=[submission.dog.slug])
        )
        public_search = self.client.get(
            reverse("registry:dog-search"), {"q": "Member Dog"}
        )
        self.assertContains(public_profile, "Member Dog")
        self.assertContains(public_profile, image.image.url)
        self.assertContains(public_search, "Member Dog")

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


    def test_paid_dog_photo_uses_verified_r2_upload_response(self):
        member = get_user_model().objects.create_user(
            username="paid-r2-photo-member",
            email="paid-r2-photo@example.com",
            password="test-pass-123",
        )
        kennel = Kennel.objects.create(
            name="Paid R2 Photo Kennel",
            slug="paid-r2-photo-kennel",
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
            amount_kobo=150000,
            reference="CCA-paid-r2-photo",
            status=SubmissionPayment.Status.PAID,
            paid_at=timezone.now(),
        )
        buffer = BytesIO()
        Image.new("RGB", (40, 30)).save(buffer, format="PNG")
        photo = SimpleUploadedFile(
            "normal-phone-photo.png",
            buffer.getvalue(),
            content_type="image/png",
        )
        self.client.force_login(member)

        storage = CloudflareR2GatewayStorage(
            base_url="https://media.example.test",
            timeout=1,
        )
        field = Submission._meta.get_field("attachment")

        def verified_put(*args, **kwargs):
            size = len(kwargs["data"])
            return BytesIO(
                (
                    '{"status":"stored","key":"submissions/photo.jpg",'
                    f'"size":{size},"r2_verified":true}}'
                ).encode("utf-8")
            )

        with (
            patch.object(field, "storage", storage),
            patch.object(storage, "exists", return_value=False),
            patch.object(storage, "_request", side_effect=verified_put) as request,
        ):
            response = self.client.post(
                reverse("accounts:payment-submit-dog", args=[payment.pk]),
                {
                    "name": "Paid Upload Dog",
                    "sex": Dog.Sex.MALE,
                    "primary_photo": photo,
                    "photo_caption": "Profile portrait",
                    "notes": "",
                },
            )

        self.assertEqual(response.status_code, 302)
        submission = Submission.objects.get(
            submitted_by=member,
            kind=Submission.Kind.DOG,
        )
        self.assertTrue(submission.attachment.name.endswith(".jpg"))
        self.assertTrue(submission.payload["photo_sha256"])
        request.assert_called_once()

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
            'accept="image/*"',
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

    def test_regular_gallery_photo_is_written_then_approved_end_to_end(self):
        member = get_user_model().objects.create_user(
            username="general-photo-member",
            password="test-pass-123",
        )
        kennel = Kennel.objects.create(
            name="General Photo Kennel",
            slug="general-photo-kennel",
        )
        KennelMembership.objects.create(
            user=member,
            kennel=kennel,
            role=KennelMembership.Role.OWNER,
        )
        dog = Dog.objects.create(
            name="General Photo Dog",
            slug="general-photo-dog",
            kennel=kennel,
            is_public=True,
        )
        buffer = BytesIO()
        Image.new("RGBA", (48, 36), (80, 90, 100, 180)).save(buffer, format="PNG")
        photo = SimpleUploadedFile(
            "gallery-photo.data",
            buffer.getvalue(),
            content_type="application/octet-stream",
        )
        self.client.force_login(member)

        field = Submission._meta.get_field("attachment")
        with TemporaryDirectory() as temp_dir:
            storage = FileSystemStorage(location=temp_dir, base_url="/media/")
            with patch.object(field, "storage", storage):
                response = self.client.post(
                    reverse("accounts:submit-image", args=[dog.pk]),
                    {
                        "caption": "Gallery portrait",
                        "is_primary": "on",
                        "notes": "",
                        "attachment": photo,
                    },
                )

                self.assertEqual(response.status_code, 302)
                submission = Submission.objects.get(
                    kind=Submission.Kind.IMAGE,
                    dog=dog,
                )
                self.assertTrue(submission.attachment.name.endswith(".jpg"))
                stored_path = Path(temp_dir) / submission.attachment.name
                self.assertTrue(stored_path.exists())
                with Image.open(stored_path) as stored:
                    self.assertEqual(stored.format, "JPEG")

                # Verify member submission does not leak to visitors before approval.
                self.client.logout()
                pending_profile = self.client.get(
                    reverse("registry:dog-detail", args=[dog.slug])
                )
                self.assertNotContains(
                    pending_profile, submission.attachment.name
                )
                approve_submission(submission, self.reviewer, "Photo checked.")
                image = DogImage.objects.get(dog=dog)
                self.assertEqual(image.image.name, submission.attachment.name)
                self.assertTrue(image.is_primary)
                public_profile = self.client.get(
                    reverse("registry:dog-detail", args=[dog.slug])
                )
                self.assertContains(public_profile, image.image.url)
                public_search = self.client.get(
                    reverse("registry:dog-search"), {"q": dog.name}
                )
                self.assertContains(public_search, image.image.url)

    def test_heic_photo_reaches_submission_storage_as_jpeg(self):
        member = get_user_model().objects.create_user(
            username="heic-upload-member",
            password="test-pass-123",
        )
        kennel = Kennel.objects.create(
            name="HEIC Upload Kennel",
            slug="heic-upload-kennel",
        )
        KennelMembership.objects.create(
            user=member,
            kennel=kennel,
            role=KennelMembership.Role.OWNER,
        )
        dog = Dog.objects.create(
            name="HEIC Upload Dog",
            slug="heic-upload-dog",
            kennel=kennel,
            is_public=True,
        )
        buffer = BytesIO()
        Image.new("RGB", (32, 32)).save(buffer, format="HEIF")
        photo = SimpleUploadedFile(
            "IMG_0001.HEIC",
            buffer.getvalue(),
            content_type="image/heic",
        )
        self.client.force_login(member)
        storage = Submission._meta.get_field("attachment").storage

        with patch.object(storage, "save", return_value="submissions/heic-upload.jpg") as save:
            response = self.client.post(
                reverse("accounts:submit-image", args=[dog.pk]),
                {
                    "caption": "HEIC portrait",
                    "is_primary": "on",
                    "notes": "",
                    "attachment": photo,
                },
            )

        self.assertEqual(response.status_code, 302)
        submission = Submission.objects.get(kind=Submission.Kind.IMAGE, dog=dog)
        self.assertTrue(submission.attachment.name.endswith(".jpg"))
        self.assertEqual(save.call_args.args[1].content_type, "image/jpeg")


class ApprovedDocumentPublicationTests(TestCase):
    """Exercise browser upload -> pending moderation -> public PDF -> storage."""

    def setUp(self):
        self.owner = get_user_model().objects.create_user(
            username="pdf-member", password="strong-test-password"
        )
        self.reviewer = get_user_model().objects.create_user(
            username="pdf-reviewer"
        )
        ModerationRoleAssignment.objects.create(
            user=self.reviewer, role=ModerationRoleAssignment.Role.REVIEWER
        )
        self.kennel = Kennel.objects.create(
            name="Document Publication Kennel", slug="document-publication-kennel"
        )
        KennelMembership.objects.create(
            user=self.owner, kennel=self.kennel,
            role=KennelMembership.Role.OWNER
        )
        self.dog = Dog.objects.create(
            name="Document Publication Dog",
            slug="document-publication-dog",
            kennel=self.kennel, is_public=True
        )

    @staticmethod
    def pdf():
        return SimpleUploadedFile(
            "pedigree-proof.pdf",
            b"%PDF-1.4\\n1 0 obj\\n<< /Type /Catalog >>\\nendobj\\n%%EOF\\n",
            content_type="application/pdf",
        )

    def test_public_document_appears_only_after_admin_approval_and_file_opens(self):
        original = self.pdf().read()
        submission_field = Submission._meta.get_field("attachment")
        document_field = DogDocument._meta.get_field("file")
        with TemporaryDirectory() as temp_dir:
            storage = FileSystemStorage(location=temp_dir, base_url="/media/")
            with patch.object(submission_field, "storage", storage), patch.object(
                document_field, "storage", storage
            ):
                self.client.force_login(self.owner)
                response = self.client.post(
                    reverse("accounts:submit-document", args=[self.dog.pk]),
                    {
                        "title": "Official pedigree certificate",
                        "document_type": DogDocument.DocumentType.PEDIGREE,
                        "is_public": "on",
                        "notes": "Please publish after verification",
                        "attachment": self.pdf(),
                    },
                )
                self.assertRedirects(response, reverse("accounts:submissions"))
                submission = Submission.objects.get(
                    kind=Submission.Kind.DOCUMENT, dog=self.dog
                )
                self.assertEqual(submission.status, Submission.Status.PENDING)
                self.assertFalse(DogDocument.objects.filter(dog=self.dog).exists())
                self.client.logout()
                before = self.client.get(
                    reverse("registry:dog-detail", args=[self.dog.slug])
                )
                self.assertNotContains(before, "Official pedigree certificate")

                # Exercise the actual moderator approval HTTP endpoint,
                # rather than calling the service directly.
                self.client.force_login(self.reviewer)
                review_response = self.client.post(
                    reverse(
                        "accounts:review-submission",
                        args=[submission.pk, "approve"],
                    ),
                    {"resolution_notes": "Document checked."},
                )
                self.assertEqual(review_response.status_code, 302)
                self.client.logout()
                submission.refresh_from_db()
                self.assertEqual(submission.status, Submission.Status.APPROVED)
                document = DogDocument.objects.get(source_submission=submission)
                self.assertTrue(document.is_public)
                self.assertEqual(document.title, "Official pedigree certificate")
                self.assertTrue(storage.exists(document.file.name))
                with document.file.open("rb") as published_file:
                    self.assertEqual(published_file.read(), original)
                public = self.client.get(
                    reverse("registry:dog-detail", args=[self.dog.slug])
                )
                self.assertContains(public, "Published documents")
                self.assertContains(public, document.title)
                self.assertContains(public, document.file.url)

    def test_approved_private_document_never_appears_on_public_profile(self):
        submission_field = Submission._meta.get_field("attachment")
        document_field = DogDocument._meta.get_field("file")
        with TemporaryDirectory() as temp_dir:
            storage = FileSystemStorage(location=temp_dir, base_url="/media/")
            with patch.object(submission_field, "storage", storage), patch.object(
                document_field, "storage", storage
            ):
                self.client.force_login(self.owner)
                response = self.client.post(
                    reverse("accounts:submit-document", args=[self.dog.pk]),
                    {
                        "title": "Confidential ownership proof",
                        "document_type": DogDocument.DocumentType.REGISTRATION,
                        "notes": "Keep private",
                        "attachment": self.pdf(),
                    },
                )
                self.assertRedirects(response, reverse("accounts:submissions"))
                submission = Submission.objects.get(
                    kind=Submission.Kind.DOCUMENT, dog=self.dog
                )
                self.client.logout()
                approve_submission(submission, self.reviewer, "Evidence verified.")
                document = DogDocument.objects.get(source_submission=submission)
                self.assertFalse(document.is_public)
                self.assertTrue(storage.exists(document.file.name))
                public = self.client.get(
                    reverse("registry:dog-detail", args=[self.dog.slug])
                )
                self.assertNotContains(public, "Confidential ownership proof")
                self.assertNotContains(public, document.file.url)


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
