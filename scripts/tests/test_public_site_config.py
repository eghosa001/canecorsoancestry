import unittest
from scripts.oracle_runner.public_site_config import public_site, DEFAULT_SITE

class PublicSiteConfigurationTests(unittest.TestCase):
    def test_default_keeps_current_cloudflare_hostname(self):
        self.assertEqual(public_site("")[0], DEFAULT_SITE)

    def test_custom_domain_is_normalized(self):
        self.assertEqual(public_site("https://Pedigree.Example/"), ("https://pedigree.example", "pedigree.example"))

    def test_rejects_unsafe_or_unready_addresses(self):
        for url in (
            "http://pedigree.example", "https://pedigree.example:8443",
            "https://pedigree.example/evil", "https://user:pass@pedigree.example",
            "https://pedigree.example?broken=1", "https://evil.example,foo.bar",
            "https://pedigree.example.", "https://127.0.0.1",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                public_site(url)
