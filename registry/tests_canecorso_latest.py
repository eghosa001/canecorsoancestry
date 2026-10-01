from django.core.management import get_commands
from django.test import SimpleTestCase

from registry.management.commands import refresh_canecorso_latest as latest


class CaneCorsoLatestCommandTests(SimpleTestCase):
    def test_refresh_command_is_registered(self):
        self.assertIn("refresh_canecorso_latest", get_commands())

    def test_latest_page_extracts_unique_profile_ids(self):
        html = """
        <a href="/view_pedigree?id=120753">HERA</a>
        <a href="view_dog?id=120752">LUCIA</a>
        <a href="/view_pedigree?id=120753">HERA again</a>
        <a href="/user?id=99">user</a>
        """
        parser = getattr(latest, "parse_latest_ids", lambda html: [])
        self.assertEqual(parser(html), ["120753", "120752"])

    def test_profile_parser_keeps_identity_and_parents(self):
        html = """
        <div>Name</div><div><a href="/view_pedigree?id=120753">HERA</a></div>
        <div>Gender</div><div>female</div>
        <div>Father</div><div><a href="/view_dog?id=100">SIRE</a></div>
        <div>Mother</div><div><a href="/view_dog?id=200">DAM</a></div>
        <div>Ped#</div><div>JR 123</div>
        <div>DOB</div><div>2026/05/11</div>
        <div>Colour</div><div>Black/Nero</div>
        """
        parser = getattr(latest, "parse_profile", lambda source_id, html: {})
        self.assertEqual(
            parser("120753", html),
            {
                "id": "120753",
                "name": "HERA",
                "gender": "female",
                "father_id": "100",
                "mother_id": "200",
                "pedigree_number": "JR 123",
                "dob": "2026/05/11",
                "colour": "Black/Nero",
                "source_url": "https://www.canecorsopedigree.com/view_dog?id=120753",
            },
        )
