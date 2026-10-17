from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("registry", "0019_staff_health_evidence_privacy")]

    operations = [
        migrations.AddField(
            model_name="healthrecord",
            name="is_public",
            field=models.BooleanField(default=True),
        ),
    ]
