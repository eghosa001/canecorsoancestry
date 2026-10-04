from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


DEFAULT_RULES = [
    ("payment_entitlement", "Paid package entitlement mismatch", "red", True),
    ("duplicate_registration", "Duplicate external registration number", "red", True),
    ("duplicate_microchip", "Duplicate microchip number", "red", True),
    ("duplicate_identity", "Possible duplicate dog identity", "red", True),
    ("duplicate_submission", "Possible duplicate pending submission", "yellow", False),
    ("existing_identity_conflict", "Existing dog identity conflict", "red", True),
    ("duplicate_photo", "Duplicate identity photograph", "yellow", False),
    ("litter_dob_conflict", "Litter date-of-birth conflict", "red", True),
    ("litter_parent_conflict", "Litter parentage conflict", "red", True),
    ("litter_id_conflict", "Litter identity conflict", "red", True),
    ("litter_kennel_conflict", "Litter kennel conflict", "red", True),
    ("litter_kennel_conflict", "Litter kennel conflict", "red", True),
    ("litter_count_exceeded", "Submitted puppies exceed declared litter size", "red", True),
    ("unusually_large_litter", "Unusually large declared litter", "red", True),
    ("duplicate_litter", "Possible duplicate litter", "yellow", False),
    ("missing_litter_core_data", "Incomplete litter identity data", "yellow", False),
    ("pedigree_chronology", "Pedigree chronology conflict", "red", True),
    ("young_parent", "Unusually young parent", "yellow", False),
    ("locked_ancestry_change", "Published ancestry field change", "red", True),
]


def seed_verification_rules(apps, schema_editor):
    VerificationRule = apps.get_model("registry", "VerificationRule")
    for code, title, risk_level, second_approval_required in DEFAULT_RULES:
        VerificationRule.objects.get_or_create(
            code=code,
            defaults={
                "title": title,
                "risk_level": risk_level,
                "second_approval_required": second_approval_required,
                "enabled": True,
            },
        )


def backfill_audit_snapshots(apps, schema_editor):
    ModerationAudit = apps.get_model("registry", "ModerationAudit")
    for event in ModerationAudit.objects.all().iterator(chunk_size=500):
        event.actor_id_snapshot = str(event.actor_id or "")
        event.submission_id_snapshot = str(event.submission_id or "")
        event.dog_id_snapshot = str(event.dog_id or "")
        event.kennel_id_snapshot = str(event.kennel_id or "")
        event.litter_id_snapshot = str(event.litter_id or "")
        event.save(
            update_fields=(
                "actor_id_snapshot",
                "submission_id_snapshot",
                "dog_id_snapshot",
                "kennel_id_snapshot",
                "litter_id_snapshot",
            )
        )


class Migration(migrations.Migration):

    dependencies = [
        ("registry", "0009_database_hot_path_indexes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="dog",
            name="is_record_locked",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="dog",
            name="record_locked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dog",
            name="record_locked_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="locked_ancestry_dogs", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="dogimage",
            name="content_sha256",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="moderationaudit",
            name="actor_id_snapshot",
            field=models.CharField(blank=True, editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name="moderationaudit",
            name="submission_id_snapshot",
            field=models.CharField(blank=True, editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name="moderationaudit",
            name="dog_id_snapshot",
            field=models.CharField(blank=True, editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name="moderationaudit",
            name="kennel_id_snapshot",
            field=models.CharField(blank=True, editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name="moderationaudit",
            name="litter_id_snapshot",
            field=models.CharField(blank=True, editable=False, max_length=64),
        ),
        migrations.AddField(
            model_name="litter",
            name="is_record_locked",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="litter",
            name="record_locked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="litter",
            name="record_locked_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="locked_ancestry_litters", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="litter",
            name="country",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="litter",
            name="declared_puppy_count",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="submission",
            name="requires_second_review",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="submission",
            name="risk_level",
            field=models.CharField(
                choices=[
                    ("green", "Green — pass"),
                    ("yellow", "Yellow — review"),
                    ("red", "Red — high risk"),
                ],
                db_index=True,
                default="green",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="submission",
            name="verification_checked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="submission",
            name="verification_status",
            field=models.CharField(
                choices=[
                    ("unchecked", "Not yet checked"),
                    ("pass", "Pass"),
                    ("review", "Requires admin review"),
                    ("awaiting_evidence", "Awaiting evidence"),
                    ("awaiting_second", "Second review required"),
                ],
                db_index=True,
                default="unchecked",
                max_length=24,
            ),
        ),
        migrations.AddIndex(
            model_name="submission",
            index=models.Index(
                fields=["status", "risk_level", "verification_status"],
                name="submission_verify_queue_idx",
            ),
        ),
        migrations.CreateModel(
            name="DogIdentityNumber",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("microchip", "Microchip")], default="microchip", max_length=24)),
                ("value", models.CharField(max_length=160)),
                ("normalized_value", models.CharField(db_index=True, editable=False, max_length=160)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("dog", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="identity_numbers", to="registry.dog")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("kind", "normalized_value"), name="unique_dog_identity_number")
                ]
            },
        ),
        migrations.CreateModel(
            name="ModerationRoleAssignment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("none", "No verification role"), ("owner", "Owner / Super Admin"), ("senior", "Senior Reviewer"), ("reviewer", "Reviewer")], max_length=16)),
                ("assigned_at", models.DateTimeField(auto_now_add=True)),
                ("assigned_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ancestry_roles_assigned", to=settings.AUTH_USER_MODEL)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="ancestry_moderation_role", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="VerificationRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=80, unique=True)),
                ("title", models.CharField(max_length=180)),
                ("description", models.TextField(blank=True)),
                ("enabled", models.BooleanField(default=True)),
                ("risk_level", models.CharField(choices=[("green", "Green — pass"), ("yellow", "Yellow — review"), ("red", "Red — high risk")], default="yellow", max_length=12)),
                ("second_approval_required", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="verification_rules_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("code",)},
        ),
        migrations.CreateModel(
            name="EvidenceRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("note", models.TextField()),
                ("status", models.CharField(choices=[("open", "Open"), ("fulfilled", "Fulfilled"), ("cancelled", "Cancelled")], db_index=True, default="open", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("fulfilled_at", models.DateTimeField(blank=True, null=True)),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="verification_evidence_requests", to=settings.AUTH_USER_MODEL)),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="evidence_requests", to="registry.submission")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="SubmissionEvidence",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("evidence_type", models.CharField(choices=[("pedigree", "Pedigree certificate"), ("registration", "Registration certificate"), ("breeding", "Breeding record"), ("litter", "Litter record"), ("kennel", "Kennel documentation"), ("dna", "DNA / parentage documentation"), ("photo", "Identity photograph"), ("other", "Other supporting document")], default="other", max_length=20)),
                ("file", models.FileField(upload_to="verification-private/%Y/%m/")),
                ("note", models.TextField(blank=True)),
                ("sha256", models.CharField(blank=True, db_index=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("evidence_request", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="evidence", to="registry.evidencerequest")),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="verification_evidence", to="registry.submission")),
                ("uploaded_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="verification_evidence_uploaded", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="SubmissionReview",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action", models.CharField(choices=[("approved", "Approved"), ("rejected", "Rejected"), ("evidence_requested", "Evidence requested"), ("override_approved", "Approved with override"), ("override_requested", "High-risk override requested"), ("second_approved", "Second reviewer approved"), ("second_rejected", "Second reviewer rejected")], db_index=True, max_length=24)),
                ("reason", models.TextField(blank=True)),
                ("warnings_snapshot", models.JSONField(blank=True, default=list)),
                ("evidence_snapshot", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("reviewer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ancestry_review_decisions", to=settings.AUTH_USER_MODEL)),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="review_decisions", to="registry.submission")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="VerificationFinding",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("run_id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False)),
                ("code", models.CharField(db_index=True, max_length=80)),
                ("risk_level", models.CharField(choices=[("green", "Green — pass"), ("yellow", "Yellow — review"), ("red", "Red — high risk")], db_index=True, max_length=12)),
                ("message", models.TextField()),
                ("expected_value", models.TextField(blank=True)),
                ("submitted_value", models.TextField(blank=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("is_current", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("rule", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="findings", to="registry.verificationrule")),
                ("submission", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="verification_findings", to="registry.submission")),
            ],
            options={
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(fields=["submission", "is_current", "risk_level"], name="finding_current_risk_idx")
                ],
            },
        ),
        migrations.AlterField(
            model_name="moderationaudit",
            name="action",
            field=models.CharField(
                choices=[
                    ("submission_approved", "Submission approved"),
                    ("submission_rejected", "Submission rejected"),
                    ("submission_bulk", "Bulk moderation update"),
                    ("dog_merged", "Dog records merged"),
                    ("verification", "Verification recorded"),
                    ("dispute_opened", "Dispute opened"),
                    ("dispute_updated", "Dispute updated"),
                    ("verification_run", "Verification run"),
                    ("evidence_requested", "Evidence requested"),
                    ("evidence_uploaded", "Evidence uploaded"),
                    ("override_requested", "Override requested"),
                    ("second_approval", "Second approval"),
                    ("record_changed", "Locked record changed"),
                    ("record_lock_changed", "Record lock changed"),
                ],
                db_index=True,
                max_length=40,
            ),
        ),
        migrations.RunPython(backfill_audit_snapshots, migrations.RunPython.noop),
        migrations.RunPython(seed_verification_rules, migrations.RunPython.noop),
    ]
