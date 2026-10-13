"""Focused guard against unsafe custom hostname cutovers."""
from unittest import TestCase
from scripts.oracle_runner.site_domain import canonical_site, host_settings, PREVIEW_SITE

class DomainConfigTests(TestCase):
    def test_default_keeps_existing_public_worker(self):
        self.assertEqual(canonical_site(""), PREVIEW_SITE)

    def test_custom_host_preserves_preview_for_safe_migration(self):
        root, allowed, origins = host_settings("https://Pedigree.Example/")
        self.assertEqual(root, "https://pedigree.example")
        self.assertIn("pedigree.example", allowed)
        self.assertIn("canecorsoancestry-site-edge.aighewieghosa111.workers.dev", allowed)
        self.assertIn("https://pedigree.example", origins)

    def test_rejects_unsafe_or_malformed_input(self):
        for value in ("http://example.com", "https://example.com/x",
                      "https://example.com:8443", "https://example.com?x=1",
                      "https://user:pass@example.com", "https://@example.com",
                      "https://127.0.0.1", "https://bad..com"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_site(value)
