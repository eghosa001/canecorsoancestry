from django.test import SimpleTestCase

from core.db.backends.cloudflare_pg8000.base import DatabaseWrapper


class CloudflarePg8000BackendTests(SimpleTestCase):
    def test_backend_imports_without_psycopg_and_identifies_postgres(self):
        self.assertEqual(DatabaseWrapper.vendor, "postgresql_pg8000")
        self.assertEqual(DatabaseWrapper.display_name, "PostgreSQL")
