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
            }
        )
        return env

    def _run_settings_probe(self, env):
        script = """
import django

django.setup()
from django.conf import settings

print(settings.DATABASES["default"]["OPTIONS"])
print(settings.STORAGES["default"]["BACKEND"])
print(settings.EMAIL_BACKEND)
"""
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.getcwd(),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_aiven_database_settings_are_provider_focused(self):
        result = self._run_settings_probe(self._production_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("search_path=django_app,public", result.stdout)
        self.assertIn("'sslmode': 'require'", result.stdout)
        self.assertIn(
            "django.core.files.storage.FileSystemStorage",
            result.stdout,
        )

    def test_configured_account_email_uses_smtp_not_console(self):
        env = self._production_env()
        env.update(
            {
                "ACCOUNT_EMAIL_ENABLED": "1",
                "EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend",
                "EMAIL_HOST": "smtp.example.com",
                "EMAIL_HOST_USER": "mailer@example.com",
                "EMAIL_HOST_PASSWORD": "test-password",
            }
        )
        result = self._run_settings_probe(env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "django.core.mail.backends.smtp.EmailBackend",
            result.stdout,
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
