from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from accounts.forms import (
    DOCUMENT_MAX_BYTES,
    IMAGE_MAX_BYTES,
    DogDocumentSubmissionForm,
    DogImageSubmissionForm,
    validate_document_upload,
    validate_image_upload,
)
from registry.models import DogDocument


class UploadValidationTests(SimpleTestCase):
    def test_image_extension_cannot_hide_invalid_content(self):
        form = DogImageSubmissionForm(
            data={"caption": "", "notes": ""},
            files={
                "attachment": SimpleUploadedFile(
                    "dog.jpg",
                    b"this is not a jpeg",
                    content_type="image/jpeg",
                )
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("attachment", form.errors)

    def test_valid_jfif_thumbnail_is_accepted_as_jpeg(self):
        buffer = BytesIO()
        Image.new("RGB", (24, 24)).save(buffer, format="JPEG")
        form = DogImageSubmissionForm(
            data={"caption": "", "notes": ""},
            files={
                "attachment": SimpleUploadedFile(
                    "dog-thumbnail.jfif",
                    buffer.getvalue(),
                    content_type="image/jpeg",
                )
            },
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_iphone_heic_photo_is_accepted_and_normalized_to_jpeg(self):
        buffer = BytesIO()
        Image.new("RGB", (24, 24)).save(buffer, format="HEIF")
        form = DogImageSubmissionForm(
            data={"caption": "", "notes": ""},
            files={
                "attachment": SimpleUploadedFile(
                    "iphone-photo.heic",
                    buffer.getvalue(),
                    content_type="image/heic",
                )
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        upload = form.cleaned_data["attachment"]
        self.assertTrue(upload.name.endswith(".jpg"))
        self.assertEqual(upload.content_type, "image/jpeg")
        with Image.open(upload) as image:
            self.assertEqual(image.format, "JPEG")

    def test_iphone_heic_evidence_is_accepted_and_normalized(self):
        buffer = BytesIO()
        Image.new("RGB", (24, 24)).save(buffer, format="HEIF")
        form = DogDocumentSubmissionForm(
            data={
                "title": "iPhone evidence",
                "document_type": DogDocument.DocumentType.PEDIGREE,
                "notes": "",
            },
            files={
                "attachment": SimpleUploadedFile(
                    "certificate.heic",
                    buffer.getvalue(),
                    content_type="image/heic",
                )
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.cleaned_data["attachment"].name.endswith(".jpg"))

    def test_image_size_limit_is_enforced_before_decoding(self):
        upload = SimpleUploadedFile("dog.jpg", b"\xff\xd8\xff")
        upload.size = IMAGE_MAX_BYTES + 1
        with self.assertRaisesRegex(ValidationError, "10 MB or smaller"):
            validate_image_upload(upload)

    def test_document_size_limit_is_enforced_before_signature_check(self):
        upload = SimpleUploadedFile("evidence.pdf", b"%PDF-1.7")
        upload.size = DOCUMENT_MAX_BYTES + 1
        with self.assertRaisesRegex(ValidationError, "20 MB or smaller"):
            validate_document_upload(upload)

    def test_document_extension_cannot_hide_invalid_content(self):
        form = DogDocumentSubmissionForm(
            data={
                "title": "Evidence",
                "document_type": DogDocument.DocumentType.PEDIGREE,
                "notes": "",
            },
            files={
                "attachment": SimpleUploadedFile(
                    "evidence.pdf",
                    b"not really a pdf",
                    content_type="application/pdf",
                )
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("attachment", form.errors)
