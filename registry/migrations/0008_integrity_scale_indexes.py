from django.db import migrations, models


def create_postgres_search_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    statements = (
        "CREATE EXTENSION IF NOT EXISTS pg_trgm",
        "CREATE INDEX IF NOT EXISTS dog_name_trgm_idx ON registry_dog USING gin (name gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS dog_bloodline_trgm_idx ON registry_dog USING gin (bloodline gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS dogalias_name_trgm_idx ON registry_dogalias USING gin (name gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS dogreg_number_trgm_idx ON registry_dogregistration USING gin (number gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS kennel_name_trgm_idx ON registry_kennel USING gin (name gin_trgm_ops)",
    )
    with schema_editor.connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0007_alter_submission_kind"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="dog",
            index=models.Index(
                fields=["is_public", "name"],
                name="dog_public_name_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="dog",
            index=models.Index(
                fields=["is_public", "-search_count"],
                name="dog_public_popularity_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="submission",
            index=models.Index(
                fields=["status", "-priority", "created_at"],
                name="submission_queue_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="submission",
            index=models.Index(
                fields=["submitted_by", "status"],
                name="submission_member_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="healthrecord",
            index=models.Index(
                fields=["dog", "test_type", "-tested_on"],
                name="health_dog_test_idx",
            ),
        ),
        migrations.RunPython(
            create_postgres_search_indexes,
            migrations.RunPython.noop,
        ),
    ]
