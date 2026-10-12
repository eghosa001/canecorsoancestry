from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0016_unverified_breeding_kennel_hypotheses"),
    ]

    operations = [
        migrations.AddField(
            model_name="moderationroleassignment",
            name="is_deregistered",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
