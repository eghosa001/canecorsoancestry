from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_paid_submission_payments"),
    ]

    operations = [
        migrations.AlterField(
            model_name="submissionpayment",
            name="package",
            field=models.CharField(
                choices=[
                    ("single_dog", "1 dog"),
                    ("multi_dog", "2–4 dogs"),
                    ("litter", "1 litter + its puppies"),
                ],
                max_length=20,
            ),
        ),
    ]
