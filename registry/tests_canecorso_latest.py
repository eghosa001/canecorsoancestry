from django.core.management import get_commands
from django.test import SimpleTestCase, TestCase

from registry.management.commands import refresh_canecorso_latest as latest
from registry.models import Dog, DogExternalKey


def profile(name, gender="", father="", mother="", dob="", pedigree=""):
    return f"""
    <div>Name</div><div><a href="/view_pedigree?id=999">{name}</a></div>
    <div>Gender</div><div>{gender}</div>
    <div>Father</div><div>{f'<a href="/view_dog?id={father}">SIRE</a>' if father else ''}</div>
    <div>Mother</div><div>{f'<a href="/view_dog?id={mother}">DAM</a>' if mother else ''}</div>
    <div>Ped#</div><div>{pedigree}</div>
    <div>Titles</div><div>CH.TEST</div>
    <div>DOB</div><div>{dob}</div>
    <div>Colour</div><div>Black/Nero</div>
    <div>HD</div><div>HD A</div>
    """


class CaneCorsoLatestParsingTests(SimpleTestCase):
    def test_refresh_command_is_registered(self):
        self.assertIn("refresh_canecorso_latest", get_commands())

    def test_latest_page_extracts_unique_profile_ids(self):
        html = """
        <a href="/view_pedigree?id=120753">HERA</a>
        <a href="view_dog?id=120752">LUCIA</a>
        <a href="/view_pedigree?id=120753">HERA again</a>
        <a href="/user?id=99">user</a>
        """
        self.assertEqual(latest.parse_latest_ids(html), ["120753", "120752"])

    def test_profile_parser_keeps_identity_and_parents(self):
        parsed = latest.parse_profile(
            "120753",
            profile(
                "HERA",
                gender="female",
                father="100",
                mother="200",
                dob="2026/05/11",
                pedigree="JR 123",
            ),
        )
        self.assertEqual(parsed["name"], "HERA")
        self.assertEqual(parsed["father_id"], "100")
        self.assertEqual(parsed["mother_id"], "200")
        self.assertEqual(parsed["dob"], "2026/05/11")
        self.assertEqual(parsed["pedigree_number"], "JR 123")
        self.assertEqual(parsed["titles"], "CH.TEST")
        self.assertEqual(parsed["hd"], "HD A")

    def test_crawler_fetches_only_missing_latest_and_ancestors(self):
        pages = {
            latest.LATEST_URL: (
                '<a href="/view_pedigree?id=10">NEW</a>'
                '<a href="/view_pedigree?id=20">KNOWN</a>'
            ),
            latest.PROFILE_URL.format("10"): profile(
                "NEW", gender="female", father="1", mother="2", dob="2026/01/01"
            ),
            latest.PROFILE_URL.format("1"): profile("SIRE", gender="male", dob="2020/01/01"),
        }
        calls = []

        def fetch_html(url):
            calls.append(url)
            return pages[url]

        crawler = getattr(latest, "collect_missing_profiles", lambda *args, **kwargs: {})
        records = crawler(fetch_html, known_ids={"20", "2"})

        self.assertEqual(set(records), {"10", "1"})
        self.assertNotIn(latest.PROFILE_URL.format("20"), calls)
        self.assertNotIn(latest.PROFILE_URL.format("2"), calls)


class CaneCorsoLatestImportTests(TestCase):
    def test_import_is_idempotent_and_links_parents(self):
        records = {
            "1": latest.parse_profile("1", profile("SIRE", gender="male", dob="2020/01/01")),
            "2": latest.parse_profile("2", profile("DAM", gender="female", dob="2020/02/01")),
            "3": latest.parse_profile(
                "3",
                profile(
                    "PUPPY",
                    gender="female",
                    father="1",
                    mother="2",
                    dob="2026/01/01",
                    pedigree="TEST-3",
                ),
            ),
        }
        importer = getattr(latest, "import_records", lambda *args, **kwargs: {"created": 0})
        importer(records, publish=True)
        importer(records, publish=True)

        puppy = Dog.objects.get(name="PUPPY")
        self.assertEqual(Dog.objects.count(), 3)
        self.assertEqual(puppy.sire.name, "SIRE")
        self.assertEqual(puppy.dam.name, "DAM")
        self.assertTrue(puppy.is_public)
        self.assertEqual(
            DogExternalKey.objects.filter(namespace="canecorsopedigree.com").count(),
            3,
        )

    def test_exact_registration_match_is_reused_without_forcing_public(self):
        existing = Dog.objects.create(name="Canonical", slug="canonical", is_public=False)
        from registry.models import DogRegistration

        DogRegistration.objects.create(dog=existing, authority=None, number="MATCH-1")
        records = {
            "50": latest.parse_profile(
                "50",
                profile("Canonical", gender="male", dob="2024/01/01", pedigree="MATCH-1"),
            )
        }
        importer = getattr(latest, "import_records", lambda *args, **kwargs: {"created": 0})
        importer(records, publish=True)

        existing.refresh_from_db()
        self.assertFalse(existing.is_public)
        self.assertEqual(Dog.objects.count(), 1)
        self.assertTrue(
            DogExternalKey.objects.filter(
                namespace="canecorsopedigree.com", key="50", dog=existing
            ).exists()
        )
