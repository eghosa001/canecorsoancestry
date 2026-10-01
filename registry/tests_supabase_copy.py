import os
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from registry.management.commands.copy_to_supabase import (
    _copied_models,
    _target_database,
)


class SupabaseCopyCommandTests(SimpleTestCase):
    def test_target_database_uses_private_schema_and_ssl(self):
        with patch.dict(
            os.environ,
            {
                "SUPABASE_DATABASE_URL": (
                    "postgresql://user:pass@db.wsntfvpcqloqzwgmsfaz.supabase.co:5432/postgres"
                ),
                "SUPABASE_PROJECT_REF": "wsntfvpcqloqzwgmsfaz",
                "DJANGO_DB_SCHEMA": "django_app",
                "DJANGO_DB_SSLMODE": "require",
            },
            clear=False,
        ):
            database = _target_database()

        self.assertEqual(database["OPTIONS"]["sslmode"], "require")
        self.assertIn(
            "search_path=django_app,extensions,public",
            database["OPTIONS"]["options"],
        )
        self.assertIsNone(database["TIME_ZONE"])
        self.assertTrue(database["AUTOCOMMIT"])
        self.assertFalse(database["ATOMIC_REQUESTS"])
        self.assertIn("TEST", database)

    def test_rejects_non_supabase_target(self):
        with patch.dict(
            os.environ,
            {
                "SUPABASE_DATABASE_URL": "postgresql://user:pass@example.com/postgres",
                "SUPABASE_PROJECT_REF": "wsntfvpcqloqzwgmsfaz",
            },
            clear=False,
        ):
            with self.assertRaises(CommandError):
                _target_database()

    def test_copy_set_preserves_sessions_and_admin_audit(self):
        labels = {model._meta.label_lower for model in _copied_models()}

        self.assertIn("auth.user", labels)
        self.assertIn("auth.group", labels)
        self.assertIn("sessions.session", labels)
        self.assertIn("admin.logentry", labels)
        self.assertIn("accounts.profile", labels)
        self.assertIn("registry.dog", labels)
