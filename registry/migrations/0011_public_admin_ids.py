from django.conf import settings
from django.db import migrations, models


def backfill_public_admin_ids(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Assignment = apps.get_model("registry", "ModerationRoleAssignment")
    Audit = apps.get_model("registry", "ModerationAudit")
    Review = apps.get_model("registry", "SubmissionReview")
    EvidenceRequest = apps.get_model("registry", "EvidenceRequest")
    VerificationEvent = apps.get_model("registry", "VerificationEvent")
    Dog = apps.get_model("registry", "Dog")
    Litter = apps.get_model("registry", "Litter")

    user_ids = set(User.objects.filter(is_staff=True).values_list("pk", flat=True))
    user_ids.update(
        Audit.objects.exclude(actor_id=None).values_list("actor_id", flat=True)
    )
    user_ids.update(
        Review.objects.values_list("reviewer_id", flat=True)
    )
    user_ids.update(
        EvidenceRequest.objects.values_list("requested_by_id", flat=True)
    )
    user_ids.update(
        VerificationEvent.objects.exclude(reviewer_id=None).values_list("reviewer_id", flat=True)
    )
    user_ids.update(
        Dog.objects.exclude(record_locked_by_id=None).values_list("record_locked_by_id", flat=True)
    )
    user_ids.update(
        Litter.objects.exclude(record_locked_by_id=None).values_list("record_locked_by_id", flat=True)
    )

    users = {
        user.pk: user
        for user in User.objects.filter(pk__in=user_ids)
    }
    for user_id in sorted(user_ids):
        user = users.get(user_id)
        if user is None:
            continue
        if user.is_superuser:
            role = "owner"
        elif user.is_staff:
            role = "reviewer"
        else:
            role = "none"
        Assignment.objects.get_or_create(
            user_id=user_id,
            defaults={"role": role},
        )

    for assignment in Assignment.objects.order_by("pk").iterator(chunk_size=500):
        if assignment.admin_number is None:
            assignment.admin_number = 10000 + assignment.pk
            assignment.save(update_fields=("admin_number",))

    admin_numbers = dict(
        Assignment.objects.exclude(admin_number=None).values_list(
            "user_id", "admin_number"
        )
    )

    for event in Audit.objects.filter(actor_admin_number_snapshot=None).exclude(
        actor_id=None
    ).iterator(chunk_size=500):
        number = admin_numbers.get(event.actor_id)
        if number:
            Audit.objects.filter(pk=event.pk).update(
                actor_admin_number_snapshot=number
            )

    for review in Review.objects.filter(
        reviewer_admin_number_snapshot=None
    ).iterator(chunk_size=500):
        number = admin_numbers.get(review.reviewer_id)
        if number:
            Review.objects.filter(pk=review.pk).update(
                reviewer_admin_number_snapshot=number
            )


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0010_verification_governance"),
    ]

    operations = [
        migrations.AddField(
            model_name="moderationroleassignment",
            name="admin_number",
            field=models.PositiveIntegerField(
                blank=True,
                db_index=True,
                editable=False,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name="moderationaudit",
            name="actor_admin_number_snapshot",
            field=models.PositiveIntegerField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="submissionreview",
            name="reviewer_admin_number_snapshot",
            field=models.PositiveIntegerField(
                blank=True,
                editable=False,
                null=True,
            ),
        ),
        migrations.RunPython(
            backfill_public_admin_ids,
            migrations.RunPython.noop,
        ),
    ]
