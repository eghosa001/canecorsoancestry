from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0006_dog_search_count"),
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
