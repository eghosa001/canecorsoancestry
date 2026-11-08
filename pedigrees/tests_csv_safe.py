"""Spreadsheet export protection for imported dog and kennel text."""
import csv
import io

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from registry.models import Dog
from .csv_safe import safe_pedigree_csv_row


class PedigreeCsvSanitizerTests(SimpleTestCase):
    def test_formula_prefixes_are_escaped_without_changing_numeric_fields(self):
        for text in ("=2+3", "+SUM(1,1)", "-1+2", "@SUM(2,3)", " \t=HYPERLINK(1,2)", "\r\n@foo"):
            with self.subTest(text=text):
                original = {"name": text, "kennel": text, "generation": 5, "path_contribution_percent": 12.5}
                cleaned = safe_pedigree_csv_row(original)
                self.assertEqual(cleaned["name"], "'" + text)
                self.assertEqual(cleaned["kennel"], "'" + text)
                self.assertEqual(cleaned["generation"], 5)
                self.assertEqual(cleaned["path_contribution_percent"], 12.5)
                self.assertEqual(original["name"], text)

    def test_legitimate_text_not_modified(self):
        original = {"name": "Branco Custodi Nos", "kennel": "Cane Corso", "country": "Nigeria", "path": "Sire → Dam"}
        self.assertEqual(safe_pedigree_csv_row(original), original)


class PublicPedigreeCsvInjectionTests(TestCase):
    def test_member_download_escapes_formula_dog_name(self):
        dog = Dog.objects.create(
            name="=HYPERLINK(\"https://example.test\",\"Click\")",
            slug="csv-formula-pedigree", is_public=True,
        )
        member = get_user_model().objects.create_user(
            username="safe-csv-member", password="pass123-Test!"
        )
        self.client.force_login(member)
        response = self.client.get(reverse("pedigrees:export", args=[dog.slug]))
        self.assertEqual(response.status_code, 200)
        rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8"))))
        self.assertTrue(rows)
        self.assertEqual(rows[0]["name"], "'" + dog.name)
        self.assertEqual(rows[0]["generation"], "0")
