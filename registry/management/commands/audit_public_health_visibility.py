"""Read-only audit for health results marked public but absent from public profiles.

Run against the production primary after deployment. No private certificates,
laboratory results, member data or DNA breed percentages are printed.
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.db.models import Q

from registry.health_publication import publication_status
from registry.models import HealthRecord


class Command(BaseCommand):
    help = "Find health-publication flag/display mismatches across all dog records (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=25)
        parser.add_argument("--dog", type=str, default="",
                            help="Optional dog name, slug or UUID fragment (read-only).")

    def handle(self, *args, **options):
        limit = max(0, min(options["limit"], 100))
        dog_query = (options["dog"] or "").strip()[:100]
        qs = (
            HealthRecord.objects.filter(is_public=True)
            .select_related("dog", "dog__kennel", "breed_dna_report")
            .order_by("dog_id", "pk")
        )
        if dog_query:
            qs = qs.filter(
                Q(dog__name__icontains=dog_query) |
                Q(dog__slug__icontains=dog_query)
            )
        counts = Counter()
        displayed = 0
        shown = 0
        for record in qs.iterator(chunk_size=400):
            code, _, _ = publication_status(record, dog=record.dog)
            counts[code] += 1
            if code == "published":
                displayed += 1
                continue
            if shown < limit:
                self.stdout.write(
                    f"NOT_ON_SITE dog_slug={record.dog.slug} "
                    f"dog_id={record.dog_id} record_id={record.pk} reason={code}"
                )
                shown += 1
        self.stdout.write(
            "PUBLIC_HEALTH_AUDIT "
            f"eligible={displayed} mismatches={sum(counts.values()) - displayed} "
            "reasons=" + ",".join(
                f"{key}:{value}" for key, value in sorted(counts.items()) if key != "published"
            )
        )
        self.stdout.write("READ ONLY: No health flags, certificates, or records changed.")
