"""Backfill approved public-text health summaries across existing dog profiles.

Never publish the underlying DogDocument or bypass owner DNA-summary consent.
Respect explicit staff decisions to hide erroneous results.
"""
from django.db import migrations


def publish_approved_health_summaries(apps, schema_editor):
    HealthRecord = apps.get_model("registry", "HealthRecord")
    ModerationAudit = apps.get_model("registry", "ModerationAudit")
    alias = schema_editor.connection.alias

    # Last explicit staff decision per health record wins. A one-off migration
    # must not accidentally undo a previous emergency privacy/correction hold.
    explicit_visibility = {}
    audits = (
        ModerationAudit.objects.using(alias)
        .filter(action="verification")
        .order_by("pk")
        .values_list("summary", flat=True)
    )
    for summary in audits.iterator(chunk_size=1000):
        if not isinstance(summary, dict):
            continue
        kind = summary.get("kind")
        if kind == "health_summary_visibility":
            public = summary.get("public")
        elif kind == "moderator_post_approval_health_editor":
            public = (summary.get("after") or {}).get("public")
        else:
            continue
        record_id = summary.get("health_record_id")
        if record_id is not None and isinstance(public, bool):
            explicit_visibility[int(record_id)] = public
    keep_private = [pk for pk, public in explicit_visibility.items() if not public]

    eligible = (
        HealthRecord.objects.using(alias)
        .filter(verification_state="health", is_public=False)
        .exclude(breed_dna_report__consent_public_summary=False)
    )
    if keep_private:
        eligible = eligible.exclude(pk__in=keep_private)
    eligible.update(is_public=True)


class Migration(migrations.Migration):
    dependencies = [("registry", "0020_health_record_public_visibility")]

    operations = [
        migrations.RunPython(
            publish_approved_health_summaries,
            migrations.RunPython.noop,
        ),
    ]
