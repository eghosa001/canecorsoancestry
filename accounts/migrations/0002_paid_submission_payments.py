import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("registry", "0009_database_hot_path_indexes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SubmissionPayment",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "package",
                    models.CharField(
                        choices=[
                            ("single_dog", "1 dog"),
                            ("multi_dog", "2–6 dogs"),
                            ("litter", "1 litter + its puppies"),
                        ],
                        max_length=20,
                    ),
                ),
                ("dog_count", models.PositiveSmallIntegerField(default=1)),
                ("amount_kobo", models.PositiveIntegerField()),
                ("currency", models.CharField(default="NGN", max_length=3)),
                ("reference", models.CharField(max_length=80, unique=True)),
                ("access_code", models.CharField(blank=True, max_length=120)),
                ("authorization_url", models.URLField(blank=True, max_length=500)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("pending", "Awaiting payment"),
                            ("paid", "Paid"),
                            ("failed", "Failed"),
                        ],
                        db_index=True,
                        default="created",
                        max_length=20,
                    ),
                ),
                ("paystack_transaction_id", models.CharField(blank=True, max_length=40)),
                ("raw_response", models.JSONField(blank=True, default=dict)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "kennel",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="submission_payments",
                        to="registry.kennel",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ancestry_submission_payments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="PaymentSubmissionLink",
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
                (
                    "slot_kind",
                    models.CharField(
                        choices=[
                            ("dog", "Dog"),
                            ("litter", "Litter"),
                            ("puppy", "Litter puppy"),
                        ],
                        max_length=12,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "payment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="submission_links",
                        to="accounts.submissionpayment",
                    ),
                ),
                (
                    "submission",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payment_link",
                        to="registry.submission",
                    ),
                ),
            ],
            options={"ordering": ("created_at",)},
        ),
    ]
