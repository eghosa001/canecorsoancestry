"""Read-only gate for the one approved, additive Oracle production migration.

Never allow an arbitrary pending migration to be applied by CI. This check
inspects Django's actual migration graph and operation list against an explicit
owner-reviewed allowlist. It does not run migrations or write to the database.
"""
from django.db.migrations.operations.constraints import AddConstraint
from django.db.migrations.operations.models import CreateModel

ALLOWED_MIGRATION = ("accounts", "0005_saved_pairing")


def validate_pending_schema_changes(plan):
    """Accept an already-updated schema or exactly the approved table addition."""
    if not plan:
        return False
    if len(plan) != 1:
        raise ValueError("Unexpected migration count; manual database review required.")
    migration, backwards = plan[0]
    if backwards or (migration.app_label, migration.name) != ALLOWED_MIGRATION:
        raise ValueError("Unapproved production schema migration; manual review required.")
    operations = migration.operations
    if (
        len(operations) != 2
        or not isinstance(operations[0], CreateModel)
        or operations[0].name != "SavedPairing"
        or not isinstance(operations[1], AddConstraint)
        or operations[1].model_name != "savedpairing"
        or operations[1].constraint.name != "saved_pairing_member_parents_unique"
        or tuple(operations[1].constraint.fields) != ("member", "sire", "dam")
    ):
        raise ValueError("Saved-pairing migration no longer matches approved additive schema.")
    # Never run data migrations, DeleteModel, RunSQL or schema rewrites here.
    return True


def main():
    import django
    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    allowed = validate_pending_schema_changes(plan)
    if allowed:
        print("PASS: Only the approved accounts.0005_saved_pairing table is pending.")
    else:
        print("PASS: No Django migrations pending.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")
