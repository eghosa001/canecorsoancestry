import json
import os
import subprocess
import sys

from django.test import SimpleTestCase


class SupabaseProductionSettingsTests(SimpleTestCase):
    def _production_env(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.production",
                "DJANGO_SECRET_KEY": "test-secret",
                "DATABASE_URL": "postgresql://user:pass@db.example.com:5432/postgres",
                "DJANGO_ALLOWED_HOSTS": "example.com",
                "DJANGO_CSRF_TRUSTED_ORIGINS": "https://example.com",
                "DJANGO_DB_SCHEMA": "django_app",
                "DJANGO_DB_SSLMODE": "require",
                "DJANGO_REQUIRE_OBJECT_STORAGE": "1",
                "SUPABASE_PROJECT_REF": "exampleprojectref",
                "SUPABASE_REGION": "eu-north-1",
                "SUPABASE_STORAGE_BUCKET": "ancestry-private",
                "SUPABASE_S3_ACCESS_KEY_ID": "access-key",
                "SUPABASE_S3_SECRET_ACCESS_KEY": "secret-key",
            }
        )
        return env

    def test_supabase_database_and_storage_settings(self):
        script = """
import json
import django

django.setup()
from django.conf import settings

print(json.dumps({
    "options": settings.DATABASES["default"]["OPTIONS"],
    "storage": settings.STORAGES["default"]["OPTIONS"],
}))
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.getcwd(),
            env=self._production_env(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip())
        self.assertIn(
            "search_path=django_app,extensions,public",
            payload["options"]["options"],
        )
        self.assertEqual(payload["options"]["sslmode"], "require")
        self.assertEqual(payload["storage"]["bucket_name"], "ancestry-private")
        self.assertEqual(
            payload["storage"]["endpoint_url"],
            "https://exampleprojectref.storage.supabase.co/storage/v1/s3",
        )

    def test_rejects_unsafe_database_schema_name(self):
        env = self._production_env()
        env["DJANGO_DB_SCHEMA"] = "django_app;drop schema public"
        result = subprocess.run(
            [sys.executable, "-c", "import django; django.setup()"],
            cwd=os.getcwd(),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("valid PostgreSQL identifier", result.stderr)
