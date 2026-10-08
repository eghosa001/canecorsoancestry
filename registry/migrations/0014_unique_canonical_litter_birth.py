from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0013_strict_role_separation"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="litter",
            constraint=models.UniqueConstraint(
                fields=("sire", "dam", "date_of_birth"),
                condition=Q(
                    sire__isnull=False,
                    dam__isnull=False,
                    date_of_birth__isnull=False,
                ),
                name="unique_canonical_litter_birth",
            ),
        ),
    ]
