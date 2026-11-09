from unittest import TestCase
from scripts.public_accessibility_audit import ROUTES, validate_site


class PublicAccessibilityContractTests(TestCase):
    def test_only_public_routes_and_https_origin(self):
        self.assertEqual(validate_site("https://example.test/"), "https://example.test")
        self.assertIn("/accounts/login/", ROUTES)
        self.assertNotIn("/member/", ROUTES)
        for bad in ("http://example.test", "https://u:p@example.test",
                    "https://example.test/foo", "https://example.test?q=1",
                    "https://example.test:9443"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_site(bad)
