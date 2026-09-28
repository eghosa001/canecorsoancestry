import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def enable_pg_trgm(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0004_member_kennel_phase"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(enable_pg_trgm, migrations.RunPython.noop),
        migrations.AddField(
            model_name="submission",
            name="assigned_to",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_ancestry_submissions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="submission",
            name="priority",
            field=models.PositiveSmallIntegerField(
                choices=[(10, "Low"), (20, "Normal"), (30, "High"), (40, "Urgent")],
                db_index=True,
                default=20,
            ),
        ),
        migrations.AddField(
            model_name="submission",
            name="review_started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="DisputeCase",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("reason", models.CharField(choices=[("pedigree", "Pedigree relationship"), ("identity", "Dog identity"), ("health", "Health/DNA information"), ("ownership", "Kennel/ownership information"), ("duplicate", "Possible duplicate dog"), ("other", "Other")], max_length=20)),
                ("status", models.CharField(choices=[("open", "Open"), ("reviewing", "Under review"), ("resolved", "Resolved"), ("dismissed", "Dismissed")], db_index=True, default="open", max_length=20)),
                ("details", models.TextField()),
                ("attachment", models.FileField(blank=True, upload_to="disputes/%Y/%m/")),
                ("resolution_notes", models.TextField(blank=True)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("assigned_to", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="assigned_ancestry_disputes", to=settings.AUTH_USER_MODEL)),
                ("closed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="closed_ancestry_disputes", to=settings.AUTH_USER_MODEL)),
                ("dog", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="disputes", to="registry.dog")),
                ("opened_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="opened_ancestry_disputes", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("status", "-created_at")},
        ),
        migrations.CreateModel(
            name="ModerationAudit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("submission_approved", "Submission approved"), ("submission_rejected", "Submission rejected"), ("submission_bulk", "Bulk moderation update"), ("dog_merged", "Dog records merged"), ("verification", "Verification recorded"), ("dispute_opened", "Dispute opened"), ("dispute_updated", "Dispute updated")], db_index=True, max_length=40)),
                ("summary", models.JSONField(blank=True, default=dict)),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ancestry_moderation_audit", to=settings.AUTH_USER_MODEL)),
                ("dispute", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_events", to="registry.disputecase")),
                ("dog", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="moderation_audit", to="registry.dog")),
                ("kennel", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="moderation_audit", to="registry.kennel")),
                ("litter", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="moderation_audit", to="registry.litter")),
                ("submission", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="audit_events", to="registry.submission")),
            ],
            options={"ordering": ("-created_at",)},
        ),
    ]
