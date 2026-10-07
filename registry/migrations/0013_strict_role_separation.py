from django.db import migrations, models


def separate_member_and_staff_accounts(apps, schema_editor):
    User = apps.get_model("auth", "User")
    KennelMembership = apps.get_model("registry", "KennelMembership")
    Submission = apps.get_model("registry", "Submission")
    ModerationRoleAssignment = apps.get_model("registry", "ModerationRoleAssignment")

    member_ids = set(
        KennelMembership.objects.values_list("user_id", flat=True)
    )
    member_ids.update(
        Submission.objects.values_list("submitted_by_id", flat=True)
    )
    member_ids.discard(None)

    conflicting_superusers = User.objects.filter(
        pk__in=member_ids,
        is_superuser=True,
    )
    if conflicting_superusers.exists():
        clean_superuser_exists = User.objects.filter(
            is_superuser=True,
        ).exclude(pk__in=member_ids).exists()
        if not clean_superuser_exists:
            raise RuntimeError(
                "Cannot separate member/staff identities safely: the only Super Admin account has member activity. "
                "Create a separate Super Admin account before applying this migration."
            )

    ModerationRoleAssignment.objects.filter(user_id__in=member_ids).delete()
    User.objects.filter(pk__in=member_ids).update(
        is_staff=False,
        is_superuser=False,
    )

    moderation_user_ids = ModerationRoleAssignment.objects.exclude(
        role="none"
    ).values_list("user_id", flat=True)
    User.objects.filter(
        pk__in=moderation_user_ids,
        is_superuser=False,
    ).update(is_staff=False)

    for user in User.objects.filter(is_superuser=True):
        ModerationRoleAssignment.objects.update_or_create(
            user_id=user.pk,
            defaults={
                "role": "owner",
                "assigned_by_id": user.pk,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("registry", "0012_submission_health_kind"),
    ]

    operations = [
        migrations.AlterField(
            model_name="moderationroleassignment",
            name="role",
            field=models.CharField(
                choices=[
                    ("none", "Suspended staff"),
                    ("owner", "Super Admin"),
                    ("senior", "Senior Moderator"),
                    ("reviewer", "Moderator"),
                ],
                max_length=16,
            ),
        ),
        migrations.RunPython(
            separate_member_and_staff_accounts,
            migrations.RunPython.noop,
        ),
    ]
