import json
import os
import subprocess
import sys

from django.test import SimpleTestCase


class ProductionSettingsTests(SimpleTestCase):
    def _production_env(self):
        env = os.environ.copy()
        env.update(
            {
                "DJANGO_SETTINGS_MODULE": "config.settings.production",
                "DJANGO_SECRET_KEY": "production-settings-test-secret-key-with-enough-entropy-123456",
                "DATABASE_URL": "postgresql://user:pass@db.example.com:5432/postgres",
                "DJANGO_ALLOWED_HOSTS": "example.com",
                "DJANGO_CSRF_TRUSTED_ORIGINS": "https://example.com",
                "DJANGO_DB_SCHEMA": "django_app",
                "DJANGO_DB_EXTRA_SCHEMAS": "public",
                "DJANGO_DB_SSLMODE": "require",
                "DJANGO_REQUIRE_OBJECT_STORAGE": "1",
                "AWS_STORAGE_BUCKET_NAME": "ancestry-private",
                "AWS_S3_REGION_NAME": "auto",
                "AWS_S3_ENDPOINT_URL": "https://objects.example.com",
                "AWS_ACCESS_KEY_ID": "access-key",
                "AWS_SECRET_ACCESS_KEY": "secret-key",
            }
        )
        return env

    def _run_settings_probe(self, env):
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
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.getcwd(),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_provider_neutral_database_and_storage_settings(self):
        result = self._run_settings_probe(self._production_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip())
        self.assertIn(
            "search_path=django_app,public",
            payload["options"]["options"],
        )
        self.assertEqual(payload["options"]["sslmode"], "require")
        self.assertEqual(payload["storage"]["bucket_name"], "ancestry-private")
        self.assertEqual(
            payload["storage"]["endpoint_url"],
            "https://objects.example.com",
        )

    def test_rejects_unsafe_database_schema_name(self):
        env = self._production_env()
        env["DJANGO_DB_SCHEMA"] = "django_app;drop schema public"
        result = self._run_settings_probe(env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("valid PostgreSQL identifier", result.stderr)

    def test_rejects_unsafe_extra_schema_name(self):
        env = self._production_env()
        env["DJANGO_DB_EXTRA_SCHEMAS"] = "public,extensions;drop schema public"
        result = self._run_settings_probe(env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("valid PostgreSQL identifiers", result.stderr)
