from django.core.management import get_commands
from django.test import SimpleTestCase


class CaneCorsoLatestCommandTests(SimpleTestCase):
    def test_refresh_command_is_registered(self):
        self.assertIn("refresh_canecorso_latest", get_commands())
