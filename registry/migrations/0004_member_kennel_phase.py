import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0003_member_moderation_workflows"),
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
                    ("kennel_claim", "Kennel ownership claim"),
                    ("litter_create", "New litter"),
                    ("litter_edit", "Litter correction"),
                    ("document_visibility", "Document visibility"),
                ],
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="submission",
            name="document",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="visibility_submissions",
                to="registry.dogdocument",
            ),
        ),
        migrations.AddField(
            model_name="submission",
            name="litter",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="submissions",
                to="registry.litter",
            ),
        ),
    ]
