"""Real downloadable pedigree PDF, access control, and complete export depth."""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from registry.models import Dog, Kennel, KennelMembership
from pedigrees.pdf_export import pedigree_pdf_response


class PdfRenderingTests(SimpleTestCase):
    @patch("pedigrees.pdf_export.pedigree_export_rows")
    def test_pdf_is_real_and_preserves_export_depth(self, export_rows):
        dog = SimpleNamespace(name="Pedigree Test Dog", slug="pedigree-test-dog")
        export_rows.return_value = [
            {"generation": 0, "path": "Subject", "name": dog.name,
             "sex": "Male", "date_of_birth": "", "colour": "",
             "country": "", "kennel": "", "repeated": "no"},
            {"generation": 10, "path": "Sire → " * 9 + "Dam",
             "name": "Ten-generation ancestor with a very long name",
             "sex": "Female", "date_of_birth": "1960-01-01",
             "colour": "", "country": "", "kennel": "",
             "repeated": "yes"},
        ]
        response = pedigree_pdf_response(dog, 10, public_only=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("10g.pdf", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertGreater(len(response.content), 1500)
        export_rows.assert_called_once_with(dog, 10, public_only=False)

    @patch("pedigrees.pdf_export.pedigree_export_rows", return_value=[])
    def test_empty_ancestry_still_has_viewable_pdf(self, _rows):
        dog = SimpleNamespace(name="Dog Without Ancestors", slug="no-ancestors")
        response = pedigree_pdf_response(dog, 4, public_only=True)
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertEqual(response.status_code, 200)


class PdfRoutePermissionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="pdf-kennel-owner", password="test-pass-123"
        )
        self.other = get_user_model().objects.create_user(
            username="pdf-unrelated-member", password="test-pass-123"
        )
        self.kennel = Kennel.objects.create(
            name="PDF Test Kennel", slug="pdf-test-kennel",
        )
        KennelMembership.objects.create(
            user=self.user, kennel=self.kennel, role=KennelMembership.Role.OWNER,
        )
        self.public = Dog.objects.create(
            name="Public Download Dog", slug="public-download-dog",
            kennel=self.kennel, is_public=True,
        )
        self.private = Dog.objects.create(
            name="Private Download Dog", slug="private-download-dog",
            kennel=self.kennel, is_public=False,
        )

    def test_member_can_download_public_pedigree_on_phone(self):
        self.client.force_login(self.other)
        response = self.client.get(
            reverse("pedigrees:export-pdf", args=[self.public.slug]),
            {"generations": "6"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("6g.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_private_dog_not_available_through_public_pdf(self):
        self.client.force_login(self.other)
        response = self.client.get(
            reverse("pedigrees:export-pdf", args=[self.private.slug])
        )
        self.assertEqual(response.status_code, 404)

    def test_private_pdf_authorized_member_only(self):
        url = reverse("accounts:member-pedigree-export-pdf", args=[self.private.pk])
        anonymous = self.client.get(url)
        self.assertEqual(anonymous.status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.user)
        response = self.client.get(url, {"generations": "5"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("5g.pdf", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertTrue(response.content.startswith(b"%PDF-"))

    def test_public_pdf_requires_sign_in(self):
        response = self.client.get(
            reverse("pedigrees:export-pdf", args=[self.public.slug])
        )
        self.assertEqual(response.status_code, 302)

    def test_csv_remains_available_separately(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("pedigrees:export", args=[self.public.slug])
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
