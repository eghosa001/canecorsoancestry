from django.test import SimpleTestCase

from registry.management.commands.backfill_canecorso_metadata import (
    infer_country,
    kennel_affix_candidates,
)


class CaneCorsoMetadataInferenceTests(SimpleTestCase):
    def test_country_uses_unambiguous_registry_country(self):
        self.assertEqual(infer_country("LO24146024"), "Italy")
        self.assertEqual(infer_country("JR 705488 CC"), "Serbia")
        self.assertEqual(infer_country("LO1811330 ; WS72510701"), "")

    def test_kennel_affix_candidates_are_conservative(self):
        candidates = kennel_affix_candidates("GOLD FIONA CUSTODI NOS")
        self.assertIn("CUSTODI NOS", candidates)
        self.assertNotIn("GOLD FIONA", candidates)
