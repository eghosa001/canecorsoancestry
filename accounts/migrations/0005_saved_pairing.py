import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_restore_multi_dog_package_label"),
        ("registry", "0014_unique_canonical_litter_birth"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedPairing",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("label", models.CharField(blank=True, max_length=120)),
                ("notes", models.CharField(blank=True, max_length=700)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("dam", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="registry.dog")),
                ("member", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="saved_ancestry_pairings", to=settings.AUTH_USER_MODEL)),
                ("sire", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="registry.dog")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddConstraint(
            model_name="savedpairing",
            constraint=models.UniqueConstraint(
                fields=("member", "sire", "dam"),
                name="saved_pairing_member_parents_unique",
            ),
        ),
    ]
