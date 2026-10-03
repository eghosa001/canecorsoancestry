from django.test import SimpleTestCase

from registry.management.commands.backfill_canecorso_metadata import (
    explicit_kennel_name,
    infer_country,
    owner_page_kennel,
)


class CaneCorsoMetadataInferenceTests(SimpleTestCase):
    def test_country_uses_only_unambiguous_registry_country(self):
        self.assertEqual(infer_country("LO24146024"), "Italy")
        self.assertEqual(infer_country("JR 705488 CC"), "Serbia")
        self.assertEqual(infer_country("LO1811330 ; WS72510701"), "")
        self.assertEqual(infer_country("PKR.II-123579; EST-02036/17"), "")

    def test_kennel_requires_explicit_breeder_evidence(self):
        self.assertEqual(
            explicit_kennel_name("Sylwia Raznikiewicz (Cane d Oro)"),
            "Cane d Oro",
        )
        self.assertEqual(explicit_kennel_name("Loris Giavelli"), "")

    def test_owner_page_uses_explicit_kennel_field(self):
        html = """
        <div>Last name</div><div>Example</div>
        <div>First name</div><div>Breeder</div>
        <div>Kennel Name</div><div>Example Corso</div>
        <div>Email address</div><div>breeder@example.com</div>
        """
        self.assertEqual(owner_page_kennel(html), "Example Corso")
