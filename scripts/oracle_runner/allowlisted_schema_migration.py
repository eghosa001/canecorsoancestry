"""Read-only gate for exactly specified, owner-reviewed Oracle migrations.

No arbitrary migration may modify the Oracle-local production PostgreSQL database.
An approved migration may run only with its exact model, field and operation shapes.
"""
from django.db import models
from django.db.migrations.operations.fields import AddField
from django.db.migrations.operations.models import AddConstraint, CreateModel

SAVED_PAIRING = ("accounts", "0005_saved_pairing")
KENNEL_PUBLICATION = ("registry", "0015_kennel_publication_controls")
ALLOWED_MIGRATION = SAVED_PAIRING  # Backward compatibility for old tests/runbooks.

# Model, field, constant default, and whether the field creates a DB index.
PUBLICATION_FIELDS = (
    ("kennel", "is_public", True, True),
    ("kennel", "hide_dogs", False, False),
    ("kennel", "publication_locked_by_superadmin", False, False),
    ("dog", "visibility_locked_by_superadmin", False, False),
    ("dog", "hidden_by_moderation", False, True),
)


def _saved_pairing_is_exact(migration):
    ops = migration.operations
    return (
        len(ops) == 2
        and isinstance(ops[0], CreateModel)
        and ops[0].name == "SavedPairing"
        and isinstance(ops[1], AddConstraint)
        and ops[1].model_name == "savedpairing"
        and ops[1].constraint.name == "saved_pairing_member_parents_unique"
        and tuple(ops[1].constraint.fields) == ("member", "sire", "dam")
    )


def _publication_is_exact(migration):
    ops = migration.operations
    if (
        len(ops) != len(PUBLICATION_FIELDS)
        or migration.dependencies != [("registry", "0014_unique_canonical_litter_birth")]
    ):
        return False
    for operation, (model_name, name, default, indexed) in zip(ops, PUBLICATION_FIELDS):
        if not isinstance(operation, AddField):
            return False
        field = operation.field
        if (
            operation.model_name != model_name
            or operation.name != name
            or type(field) is not models.BooleanField
            or field.default is not default
            or field.db_index is not indexed
            or field.null
            or field.unique
            or field.primary_key
            or operation.preserve_default is False
        ):
            return False
    return True


def validate_pending_schema_changes(plan):
    """Reject other pending versions, combined plans, reversals, and drift."""
    if not plan:
        return False
    if len(plan) != 1:
        raise ValueError("Unexpected pending migration count; manual DB review required.")
    migration, backwards = plan[0]
    if backwards:
        raise ValueError("Reverse production migrations are not authorized.")
    identity = (migration.app_label, migration.name)
    if identity == SAVED_PAIRING and _saved_pairing_is_exact(migration):
        return True
    if identity == KENNEL_PUBLICATION and _publication_is_exact(migration):
        return True
    raise ValueError("Unapproved production migration or unexpected operations.")


def main():
    import django
    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    allowed = validate_pending_schema_changes(plan)
    if allowed:
        migration, _ = plan[0]
        print(f"PASS: Only approved {migration.app_label}.{migration.name} is pending.")
    else:
        print("PASS: No Django migrations pending.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")
