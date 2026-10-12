"""Oracle deployment must never silently apply unapproved production changes."""
import importlib
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.oracle_runner.allowlisted_schema_migration import validate_pending_schema_changes


class ApprovedSchemaMigrationTests(unittest.TestCase):
    def setUp(self):
        mod = importlib.import_module("accounts.migrations.0005_saved_pairing")
        self.migration = mod.Migration("0005_saved_pairing", "accounts")

    def test_already_migrated_production_is_valid(self):
        self.assertFalse(validate_pending_schema_changes([]))

    def test_exact_additive_saved_research_table_is_allowlisted(self):
        self.assertTrue(validate_pending_schema_changes([(self.migration, False)]))

    def test_reverse_migration_and_other_version_are_forbidden(self):
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(self.migration, True)])
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([
                (SimpleNamespace(
                    app_label="registry", name="9999_bulk_import",
                    operations=self.migration.operations,
                ), False),
            ])

    def test_any_other_pending_migration_blocks_production(self):
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([
                (self.migration, False),
                (SimpleNamespace(
                    app_label="registry", name="9999_bulk_import",
                    operations=[],
                ), False),
            ])

    def test_exact_kennel_publication_migration_is_allowlisted(self):
        module = importlib.import_module("registry.migrations.0015_kennel_publication_controls")
        migration = module.Migration("0015_kennel_publication_controls", "registry")
        self.assertTrue(validate_pending_schema_changes([(migration, False)]))
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(migration, True)])
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(self.migration, False), (migration, False)])

    def test_only_five_unchanged_boolean_fields_are_permitted(self):
        module = importlib.import_module("registry.migrations.0015_kennel_publication_controls")
        migration = module.Migration("0015_kennel_publication_controls", "registry")
        first = migration.operations[0]
        original = first.field.default
        try:
            first.field.default = False
            with self.assertRaises(ValueError):
                validate_pending_schema_changes([(migration, False)])
        finally:
            first.field.default = original
        original_ops = migration.operations
        try:
            migration.operations = original_ops[:-1]
            with self.assertRaises(ValueError):
                validate_pending_schema_changes([(migration, False)])
        finally:
            migration.operations = original_ops

    def test_atomic_publication_script_has_backups_and_no_app_alter_grants(self):
        root = Path(__file__).resolve().parents[1] / "oracle_runner"
        stage = (root / "stage_django.sh").read_text()
        sql = (root / "approved_registry_0015.sql").read_text()
        self.assertIn("registry.0015_kennel_publication_controls", stage)
        self.assertIn("approved_registry_0015.sql", stage)
        self.assertIn("bash scripts/oracle_runner/backup_local_postgres.sh", stage)
        self.assertLess(
            stage.index("bash scripts/oracle_runner/backup_local_postgres.sh"),
            stage.index("< scripts/oracle_runner/approved_registry_0015.sql"),
        )
        self.assertIn("BEGIN;", sql)
        self.assertIn("COMMIT;", sql)
        self.assertIn("ON_ERROR_STOP=1", stage)
        self.assertIn("django_app.django_migrations", sql)
        self.assertIn("current_user <> 'cca_shadow_admin'", sql)
        self.assertEqual(sql.count("ADD COLUMN "), 5)
        self.assertNotIn("GRANT ALTER", stage + sql)
        self.assertNotIn("GRANT ALL", stage + sql)

    def test_oracle_stage_invokes_preflight_as_importable_package(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "oracle_runner"
            / "stage_django.sh"
        ).read_text()
        self.assertIn(
            "python -m scripts.oracle_runner.allowlisted_schema_migration",
            script,
        )

    def test_migration_privileges_are_temporary_and_reclaimed_on_exit(self):
        script = (
            Path(__file__).resolve().parents[1] / "oracle_runner"
            / "stage_django.sh"
        ).read_text()
        self.assertIn("schema_privilege_armed=0", script)
        self.assertIn("trap cleanup_stage EXIT", script)
        self.assertIn("revoke_temporary_migration_permissions", script)
        self.assertIn("REVOKE REFERENCES ON TABLE django_app.registry_dog FROM cca_app", script)
        self.assertIn("REVOKE REFERENCES ON TABLE django_app.auth_user FROM cca_app", script)
        self.assertIn("has_table_privilege('cca_app', 'django_app.$reference_table', 'REFERENCES')", script)
        self.assertIn("GRANT CREATE ON SCHEMA django_app TO cca_app", script)
        self.assertIn("REVOKE CREATE ON SCHEMA django_app FROM cca_app", script)
        self.assertIn("has_schema_privilege('cca_app', 'django_app', 'CREATE')", script)
        self.assertLess(
            script.index("bash scripts/oracle_runner/backup_local_postgres.sh"),
            script.index("GRANT CREATE ON SCHEMA django_app TO cca_app"),
        )
        self.assertLess(
            script.index("REVOKE CREATE ON SCHEMA django_app FROM cca_app"),
            script.index('sudo -n install -d -m 700 /etc/cca'),
        )

    def test_unreviewed_operation_change_is_forbidden(self):
        changed = SimpleNamespace(
            app_label="accounts", name="0005_saved_pairing",
            operations=self.migration.operations[:1],
        )
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(changed, False)])


if __name__ == "__main__":
    unittest.main()
