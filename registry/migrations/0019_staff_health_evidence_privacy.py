from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("registry", "0018_breed_dna_report")]

    operations = [
        migrations.AddField(
            model_name="healthrecord",
            name="evidence_document",
            field=models.OneToOneField(
                to="registry.dogdocument", related_name="staff_health_record",
                null=True, blank=True, on_delete=django.db.models.deletion.PROTECT,
            ),
        ),
        migrations.AddField(
            model_name="dogdocument",
            name="staff_review_only",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="breeddnareport",
            name="consent_public_summary",
            field=models.BooleanField(default=True),
        ),
    ]
