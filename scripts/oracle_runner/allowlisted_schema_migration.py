"""Read-only gate for exactly specified, owner-reviewed Oracle migrations.

No arbitrary migration may modify the Oracle-local production PostgreSQL database.
An approved migration may run only with its exact model, field and operation shapes.
"""
from django.db import models
from django.db.migrations.operations.fields import AddField
from django.db.migrations.operations.models import AddConstraint, CreateModel

SAVED_PAIRING = ("accounts", "0005_saved_pairing")
KENNEL_PUBLICATION = ("registry", "0015_kennel_publication_controls")
ARCHIVE_HYPOTHESIS = ("registry", "0016_unverified_breeding_kennel_hypotheses")
STAFF_DEREGISTRATION = ("registry", "0017_moderation_staff_deregistration")
BREED_DNA_REPORT = ("registry", "0018_breed_dna_report")
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


def _archive_hypothesis_is_exact(migration):
    ops = migration.operations
    if (
        len(ops) != 3
        or migration.dependencies != [("registry", "0015_kennel_publication_controls")]
        or any(not isinstance(op, AddField) for op in ops)
    ):
        return False
    flag, candidate_fk, metadata = ops
    flag_field = flag.field
    fk_field = candidate_fk.field
    meta_field = metadata.field
    return (
        flag.model_name == "kennel"
        and flag.name == "is_archive_hypothesis"
        and type(flag_field) is models.BooleanField
        and flag_field.default is False
        and flag_field.db_index
        and not flag_field.null
        and candidate_fk.model_name == "dog"
        and candidate_fk.name == "inferred_kennel"
        and type(fk_field) is models.ForeignKey
        and str(fk_field.remote_field.model).lower() == "registry.kennel"
        and fk_field.null
        and fk_field.blank
        and fk_field.remote_field.related_name == "inferred_dogs"
        and fk_field.remote_field.on_delete is models.SET_NULL
        and metadata.model_name == "dog"
        and metadata.name == "inferred_kennel_evidence"
        and type(meta_field) is models.JSONField
        and meta_field.default is dict
        and meta_field.blank
        and not meta_field.null
    )


def _staff_deregistration_is_exact(migration):
    """Only the single additive inactive/deregistered-role marker is authorized."""
    if (
        migration.dependencies != [ARCHIVE_HYPOTHESIS]
        or len(migration.operations) != 1
    ):
        return False
    operation = migration.operations[0]
    if not isinstance(operation, AddField):
        return False
    field = operation.field
    return (
        operation.model_name == "moderationroleassignment"
        and operation.name == "is_deregistered"
        and type(field) is models.BooleanField
        and field.default is False
        and field.db_index is True
        and not field.null
        and not field.unique
        and not field.primary_key
        and operation.preserve_default is not False
    )


def _breed_dna_is_exact(migration):
    """Approve only the additive, consent-aware third-party DNA report table."""
    if (
        migration.dependencies != [STAFF_DEREGISTRATION]
        or len(migration.operations) != 1
        or not isinstance(migration.operations[0], CreateModel)
        or migration.operations[0].name != "BreedDNAReport"
    ):
        return False
    fields = dict(migration.operations[0].fields)
    if set(fields) != {
        "id", "provider", "cane_corso_percentage", "composition",
        "consent_full_report", "created_at", "evidence_document", "health_record",
    }:
        return False
    id_field = fields["id"]
    provider = fields["provider"]
    percentage = fields["cane_corso_percentage"]
    composition = fields["composition"]
    consent = fields["consent_full_report"]
    created = fields["created_at"]
    return (
        type(id_field) is models.BigAutoField
        and id_field.primary_key and not id_field.null
        and type(provider) is models.CharField and provider.max_length == 100
        and not provider.null and not provider.blank
        and type(percentage) is models.DecimalField
        and percentage.max_digits == 5 and percentage.decimal_places == 2
        and not percentage.null
        and type(composition) is models.JSONField and composition.default is list
        and not composition.null
        and type(consent) is models.BooleanField and consent.default is False
        and not consent.null
        and type(created) is models.DateTimeField and created.auto_now_add
        and _breed_dna_reference_is_exact(
            fields["evidence_document"], "registry.dogdocument", models.PROTECT
        )
        and _breed_dna_reference_is_exact(
            fields["health_record"], "registry.healthrecord", models.CASCADE
        )
    )


def _breed_dna_reference_is_exact(field, target, on_delete):
    return (
        type(field) is models.OneToOneField
        and str(field.remote_field.model).lower() == target
        and field.remote_field.on_delete is on_delete
        and field.remote_field.related_name == "breed_dna_report"
        and not field.null
        and not field.blank
    )


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
    if identity == ARCHIVE_HYPOTHESIS and _archive_hypothesis_is_exact(migration):
        return True
    if identity == STAFF_DEREGISTRATION and _staff_deregistration_is_exact(migration):
        return True
    if identity == BREED_DNA_REPORT and _breed_dna_is_exact(migration):
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
