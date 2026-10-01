from django.db import migrations


INDEXES = (
    "CREATE INDEX IF NOT EXISTS dog_name_upper_trgm_idx ON registry_dog USING gin (upper(name) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS dog_bloodline_upper_trgm_idx ON registry_dog USING gin (upper(bloodline) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS dogalias_name_upper_trgm_idx ON registry_dogalias USING gin (upper(name) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS dogreg_number_upper_trgm_idx ON registry_dogregistration USING gin (upper(number) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS kennel_name_upper_trgm_idx ON registry_kennel USING gin (upper(name) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS dog_public_sex_name_idx ON registry_dog (sex, name) WHERE is_public",
    "CREATE INDEX IF NOT EXISTS dog_public_country_idx ON registry_dog (country) WHERE is_public AND country <> ''",
    "CREATE INDEX IF NOT EXISTS dog_public_sire_idx ON registry_dog (sire_id) WHERE is_public AND sire_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS dog_public_dam_idx ON registry_dog (dam_id) WHERE is_public AND dam_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS dogsource_verified_dog_idx ON registry_dogsource (dog_id) WHERE verified_at IS NOT NULL",
)

INDEX_NAMES = (
    "dog_name_upper_trgm_idx",
    "dog_bloodline_upper_trgm_idx",
    "dogalias_name_upper_trgm_idx",
    "dogreg_number_upper_trgm_idx",
    "kennel_name_upper_trgm_idx",
    "dog_public_sex_name_idx",
    "dog_public_country_idx",
    "dog_public_sire_idx",
    "dog_public_dam_idx",
    "dogsource_verified_dog_idx",
)


def create_hot_path_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        for statement in INDEXES:
            cursor.execute(statement)


def drop_hot_path_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for name in INDEX_NAMES:
            cursor.execute(f'DROP INDEX IF EXISTS "{name}"')


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0008_integrity_scale_indexes"),
    ]

    operations = [
        migrations.RunPython(create_hot_path_indexes, drop_hot_path_indexes),
    ]
