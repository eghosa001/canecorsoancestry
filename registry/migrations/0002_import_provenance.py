import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="dog",
            name="bloodline",
            field=models.CharField(blank=True, max_length=220),
        ),
        migrations.AddField(
            model_name="dogsource",
            name="raw_payload",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="dogregistration",
            name="authority",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="registrations",
                to="registry.registrationauthority",
            ),
        ),
        migrations.CreateModel(
            name="DogExternalKey",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("namespace", models.CharField(max_length=80)),
                ("key", models.CharField(max_length=230)),
                (
                    "dog",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="external_keys",
                        to="registry.dog",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="DogTitle",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=160)),
                ("source_text", models.CharField(blank=True, max_length=220)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "dog",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="titles",
                        to="registry.dog",
                    ),
                ),
            ],
            options={"ordering": ("name",)},
        ),
        migrations.AddConstraint(
            model_name="dogexternalkey",
            constraint=models.UniqueConstraint(
                fields=("namespace", "key"),
                name="unique_external_dog_key",
            ),
        ),
        migrations.AddConstraint(
            model_name="dogtitle",
            constraint=models.UniqueConstraint(
                fields=("dog", "name"),
                name="unique_dog_title",
            ),
        ),
        migrations.AddConstraint(
            model_name="dogregistration",
            constraint=models.UniqueConstraint(
                condition=models.Q(("authority__isnull", True)),
                fields=("number",),
                name="unique_registration_number_without_authority",
            ),
        ),
    ]
