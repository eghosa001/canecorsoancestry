from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0011_public_admin_ids"),
    ]

    operations = [
        migrations.AlterField(
            model_name="submission",
            name="kind",
            field=models.CharField(
                choices=[
                    ("dog", "New dog"),
                    ("correction", "Dog correction"),
                    ("image", "Dog image"),
                    ("document", "Dog document"),
                    ("health", "Health/DNA record"),
                    ("kennel", "Kennel update"),
                    ("kennel_create", "New kennel profile"),
                    ("kennel_claim", "Kennel ownership claim"),
                    ("litter_create", "New litter"),
                    ("litter_edit", "Litter correction"),
                    ("document_visibility", "Document visibility"),
                ],
                max_length=20,
            ),
        ),
    ]
