from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0015_kennel_publication_controls"),
    ]

    operations = [
        migrations.AddField(
            model_name="kennel",
            name="is_archive_hypothesis",
            field=models.BooleanField(default=False, db_index=True),
        ),
        migrations.AddField(
            model_name="dog",
            name="inferred_kennel",
            field=models.ForeignKey(
                to="registry.kennel",
                null=True, blank=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="inferred_dogs",
            ),
        ),
        migrations.AddField(
            model_name="dog",
            name="inferred_kennel_evidence",
            field=models.JSONField(default=dict, blank=True),
        ),

    ]
