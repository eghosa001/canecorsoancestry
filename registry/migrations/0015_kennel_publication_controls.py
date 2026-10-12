from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0014_unique_canonical_litter_birth"),
    ]

    operations = [
        migrations.AddField(
            model_name="kennel",
            name="is_public",
            field=models.BooleanField(default=True, db_index=True),
        ),
        migrations.AddField(
            model_name="kennel",
            name="hide_dogs",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="kennel",
            name="publication_locked_by_superadmin",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="dog",
            name="visibility_locked_by_superadmin",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="dog",
            name="hidden_by_moderation",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
