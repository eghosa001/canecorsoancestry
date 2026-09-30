from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from accounts.forms import DogDocumentSubmissionForm, DogImageSubmissionForm
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
