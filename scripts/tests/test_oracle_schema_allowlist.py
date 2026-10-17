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

    def test_exact_archive_research_migration_is_strictly_allowlisted(self):
        import copy
        module = importlib.import_module(
            "registry.migrations.0016_unverified_breeding_kennel_hypotheses"
        )
        migration = module.Migration(
            "0016_unverified_breeding_kennel_hypotheses", "registry"
        )
        self.assertTrue(validate_pending_schema_changes([(migration, False)]))
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(migration, True)])
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(self.migration, False), (migration, False)])
        changed = copy.deepcopy(migration)
        changed.operations[0].field.default = True
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(changed, False)])
        changed = copy.deepcopy(migration)
        changed.operations[1].field.null = False
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(changed, False)])
        changed = copy.deepcopy(migration)
        changed.operations[2].field.default = list
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(changed, False)])

    def test_exact_staff_deregistration_field_can_migrate(self):
        import copy
        module = importlib.import_module(
            "registry.migrations.0017_moderation_staff_deregistration"
        )
        migration = module.Migration("0017_moderation_staff_deregistration", "registry")
        self.assertTrue(validate_pending_schema_changes([(migration, False)]))
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(migration, True)])
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(self.migration, False), (migration, False)])
        for mutation in ("name", "default", "db_index", "null", "model_name"):
            changed = copy.deepcopy(migration)
            op = changed.operations[0]
            if mutation == "name":
                op.name = "is_active"
            elif mutation == "default":
                op.field.default = True
            elif mutation == "db_index":
                op.field.db_index = False
            elif mutation == "null":
                op.field.null = True
            elif mutation == "model_name":
                op.model_name = "dog"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_pending_schema_changes([(changed, False)])

    def test_staff_deregistration_production_script_is_backed_up_and_atomic(self):
        root = Path(__file__).resolve().parents[1] / "oracle_runner"
        stage = (root / "stage_django.sh").read_text()
        sql = (root / "approved_registry_0017.sql").read_text()
        self.assertIn("registry.0017_moderation_staff_deregistration", stage)
        self.assertIn("approved_registry_0017.sql", stage)
        self.assertLess(
            stage.index("bash scripts/oracle_runner/backup_local_postgres.sh"),
            stage.index("< scripts/oracle_runner/approved_registry_0017.sql"),
        )
        self.assertIn("BEGIN;", sql)
        self.assertIn("COMMIT;", sql)
        self.assertIn("ON_ERROR_STOP=1", stage)
        self.assertIn("current_user <> 'cca_shadow_admin'", sql)
        self.assertIn("django_app.django_migrations", sql)
        self.assertEqual(sql.count("ADD COLUMN "), 1)
        self.assertIn("ADD COLUMN is_deregistered boolean NOT NULL DEFAULT false", sql)
        self.assertNotIn("UPDATE django_app.auth_user", sql)
        self.assertNotIn("INSERT INTO django_app.registry_dog", sql)
        self.assertNotIn("GRANT ALTER", stage + sql)
        self.assertNotIn("GRANT ALL", stage + sql)

    def test_unverified_kennel_schema_sql_still_requires_backup_and_admin(self):
        root = Path(__file__).resolve().parents[1] / "oracle_runner"
        stage = (root / "stage_django.sh").read_text()
        sql = (root / "approved_registry_0016.sql").read_text()
        self.assertIn("registry.0016_unverified_breeding_kennel_hypotheses", stage)
        self.assertIn("approved_registry_0016.sql", stage)
        self.assertIn("BEGIN;", sql)
        self.assertIn("COMMIT;", sql)
        self.assertIn("ON_ERROR_STOP=1", stage)
        self.assertIn("current_user <> 'cca_shadow_admin'", sql)
        self.assertIn("django_app.django_migrations", sql)
        self.assertEqual(sql.count("ADD COLUMN "), 3)
        self.assertIn("inferred_kennel_evidence", sql)
        self.assertNotIn("INSERT INTO django_app.registry_dog", sql)
        self.assertNotIn("GRANT ALTER", stage + sql)
        self.assertNotIn("GRANT ALL", stage + sql)
        self.assertLess(
            stage.index("bash scripts/oracle_runner/backup_local_postgres.sh"),
            stage.index("< scripts/oracle_runner/approved_registry_0016.sql"),
        )

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


    def test_breed_dna_migration_needs_exact_consent_schema(self):
        import copy
        mod = importlib.import_module("registry.migrations.0018_breed_dna_report")
        migration = mod.Migration("0018_breed_dna_report", "registry")
        self.assertTrue(validate_pending_schema_changes([(migration, False)]))
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(migration, True)])
        changed = copy.deepcopy(migration)
        for name, field in changed.operations[0].fields:
            if name == "consent_full_report":
                field.default = True
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(changed, False)])
        changed = copy.deepcopy(migration)
        changed.operations[0].name = "OtherTable"
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(changed, False)])

    def test_breed_dna_production_sql_is_backed_up_and_admin_only(self):
        root = Path(__file__).resolve().parents[1] / "oracle_runner"
        stage = (root / "stage_django.sh").read_text()
        sql = (root / "approved_registry_0018.sql").read_text()
        self.assertIn("registry.0018_breed_dna_report", stage)
        self.assertLess(
            stage.index("bash scripts/oracle_runner/backup_local_postgres.sh"),
            stage.index("< scripts/oracle_runner/approved_registry_0018.sql"),
        )
        for required in ("BEGIN;", "COMMIT;", "cca_shadow_admin",
                         "django_app.django_migrations", "CREATE TABLE django_app.registry_breeddnareport"):
            self.assertIn(required, sql)
        self.assertNotIn("GRANT ALTER", sql + stage)
        self.assertNotIn("GRANT ALL", sql + stage)
        self.assertNotIn("UPDATE django_app.registry_dog", sql)


    def test_historical_health_privacy_is_exactly_three_additive_fields(self):
        import copy
        mod = importlib.import_module("registry.migrations.0019_staff_health_evidence_privacy")
        migration = mod.Migration("0019_staff_health_evidence_privacy", "registry")
        self.assertTrue(validate_pending_schema_changes([(migration, False)]))
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(migration, True)])
        for index, key, value in (
            (0, "related_name", "faked_owner_consent"),
            (1, "default", True),
            (2, "default", False),
        ):
            changed = copy.deepcopy(migration)
            if index == 0:
                changed.operations[index].field.remote_field.related_name = value
            else:
                setattr(changed.operations[index].field, key, value)
            with self.subTest(index=index), self.assertRaises(ValueError):
                validate_pending_schema_changes([(changed, False)])
        changed = copy.deepcopy(migration)
        changed.operations.pop()
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(changed, False)])

    def test_historical_privacy_sql_is_admin_only_atomic_and_backed_up(self):
        root = Path(__file__).resolve().parents[1] / "oracle_runner"
        stage = (root / "stage_django.sh").read_text()
        sql = (root / "approved_registry_0019.sql").read_text()
        self.assertIn("registry.0019_staff_health_evidence_privacy", stage)
        self.assertLess(
            stage.index("bash scripts/oracle_runner/backup_local_postgres.sh"),
            stage.index("< scripts/oracle_runner/approved_registry_0019.sql"),
        )
        for expected in (
            "BEGIN;", "COMMIT;", "cca_shadow_admin", "django_app.django_migrations",
            "ADD COLUMN evidence_document_id bigint NULL",
            "ADD COLUMN staff_review_only boolean NOT NULL DEFAULT false",
            "ADD COLUMN consent_public_summary boolean NOT NULL DEFAULT true",
        ):
            self.assertIn(expected, sql)
        self.assertEqual(sql.count("ADD COLUMN "), 3)
        self.assertNotIn("UPDATE django_app.registry_dog", sql)
        self.assertNotIn("GRANT ALTER", stage + sql)
        self.assertNotIn("GRANT ALL", stage + sql)

    def test_exact_additive_health_visibility_and_oracle_backup(self):
        import copy
        mod = importlib.import_module("registry.migrations.0020_health_record_public_visibility")
        migration = mod.Migration("0020_health_record_public_visibility", "registry")
        self.assertTrue(validate_pending_schema_changes([(migration, False)]))
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(migration, True)])
        altered = copy.deepcopy(migration)
        altered.operations[0].field.default = False
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(altered, False)])
        altered = copy.deepcopy(migration)
        altered.operations[0].name = "consent_public_summary"
        with self.assertRaises(ValueError):
            validate_pending_schema_changes([(altered, False)])
        root = Path(__file__).resolve().parents[1] / "oracle_runner"
        stage = (root / "stage_django.sh").read_text()
        sql = (root / "approved_registry_0020.sql").read_text()
        self.assertIn("registry.0020_health_record_public_visibility", stage)
        self.assertLess(stage.index("bash scripts/oracle_runner/backup_local_postgres.sh"),
                        stage.index("< scripts/oracle_runner/approved_registry_0020.sql"))
        self.assertEqual(sql.count("ADD COLUMN "), 1)
        self.assertIn("ADD COLUMN is_public boolean NOT NULL DEFAULT true", sql)
        self.assertIn("BEGIN;", sql)
        self.assertIn("COMMIT;", sql)
        self.assertIn("cca_shadow_admin", sql)
        self.assertNotIn("GRANT ALTER", sql)
        self.assertNotIn("GRANT ALL", sql)


if __name__ == "__main__":
    unittest.main()
