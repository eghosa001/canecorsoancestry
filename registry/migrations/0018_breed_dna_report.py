from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("registry", "0017_moderation_staff_deregistration")]
    operations = [
        migrations.CreateModel(
            name="BreedDNAReport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("provider", models.CharField(max_length=100)),
                ("cane_corso_percentage", models.DecimalField(max_digits=5, decimal_places=2)),
                ("composition", models.JSONField(default=list)),
                ("consent_full_report", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("evidence_document", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="breed_dna_report", to="registry.dogdocument")),
                ("health_record", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="breed_dna_report", to="registry.healthrecord")),
            ],
        ),
    ]
