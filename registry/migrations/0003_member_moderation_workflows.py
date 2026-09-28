import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0002_import_provenance"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Submission",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("dog", "New dog"), ("correction", "Dog correction"), ("image", "Dog image"), ("document", "Dog document"), ("kennel", "Kennel update")], max_length=20)),
                ("status", models.CharField(choices=[("pending", "Pending review"), ("approved", "Approved"), ("rejected", "Rejected")], db_index=True, default="pending", max_length=20)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("attachment", models.FileField(blank=True, upload_to="submissions/%Y/%m/")),
                ("notes", models.TextField(blank=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("resolution_notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("dog", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="submissions", to="registry.dog")),
                ("kennel", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="submissions", to="registry.kennel")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="reviewed_ancestry_submissions", to=settings.AUTH_USER_MODEL)),
                ("submitted_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ancestry_submissions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="DogDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=220)),
                ("document_type", models.CharField(choices=[("pedigree", "Pedigree"), ("health", "Health"), ("registration", "External registration"), ("dna", "DNA"), ("other", "Other")], default="other", max_length=20)),
                ("file", models.FileField(upload_to="documents/%Y/%m/")),
                ("is_public", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("dog", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="documents", to="registry.dog")),
                ("source_submission", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_document", to="registry.submission")),
                ("submitted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="dog_documents", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="DogRedirect",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("old_slug", models.SlugField(max_length=230, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("dog", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="redirects", to="registry.dog")),
            ],
        ),
        migrations.CreateModel(
            name="MergeHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("retired_dog_id", models.UUIDField()),
                ("retired_slug", models.CharField(max_length=230)),
                ("retired_name", models.CharField(max_length=220)),
                ("summary", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("canonical_dog", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="merge_history", to="registry.dog")),
                ("performed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="dog_merges", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=180)),
                ("message", models.TextField()),
                ("link", models.CharField(blank=True, max_length=300)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ancestry_notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="VerificationEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("field_name", models.CharField(blank=True, max_length=80)),
                ("state", models.CharField(choices=[("community", "Community submitted"), ("source", "Source attached"), ("identity", "Identity reviewed"), ("pedigree", "Pedigree reviewed"), ("health", "Health/DNA verified")], max_length=20)),
                ("note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("dog", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="verification_events", to="registry.dog")),
                ("health_record", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="verification_events", to="registry.healthrecord")),
                ("kennel", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="verification_events", to="registry.kennel")),
                ("reviewer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ancestry_verification_events", to=settings.AUTH_USER_MODEL)),
                ("source", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="verification_events", to="registry.dogsource")),
            ],
            options={"ordering": ("-created_at",)},
        ),
    ]
