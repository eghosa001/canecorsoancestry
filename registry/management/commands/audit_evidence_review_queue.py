"""Read-only, prioritized evidence-review triage for published dog records.

This command never infers verification, modifies records or exposes private dogs.
A dog can be reviewed through another evidence workflow, so a missing
timestamped DogSource is a review lead, not an accusation of false data.
"""
import json

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef, Q

from registry.models import DogSource, VerificationState
from registry.querysets import published_dogs


REVIEWED_STATES = (
    VerificationState.IDENTITY_REVIEWED,
    VerificationState.PEDIGREE_REVIEWED,
    VerificationState.HEALTH_VERIFIED,
)


def evidence_review_triage(limit=15, include_public_slugs=False):
    """Return bounded, independently actionable groups, with no database writes."""
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("Review limit must be between 1 and 100.")

    available_source = DogSource.objects.filter(dog_id=OuterRef("pk")).filter(
        Q(source_url__gt="") | Q(document__gt="")
    )
    reviewed_source = available_source.filter(verified_at__isnull=False)
    base = published_dogs().annotate(
        _has_source=Exists(available_source),
        _has_reviewed_source=Exists(reviewed_source),
    )
    groups = {
        "reviewed_status_without_timestamped_dogsource": base.filter(
            verification_state__in=REVIEWED_STATES,
            _has_reviewed_source=False,
        ),
        "unreviewed_with_source": base.exclude(
            verification_state__in=REVIEWED_STATES,
        ).filter(_has_source=True),
        "unreviewed_without_source": base.exclude(
            verification_state__in=REVIEWED_STATES,
        ).filter(_has_source=False),
    }
    report = {"selection": "published dogs only", "limit_per_group": limit}
    for name, candidates in groups.items():
        top = candidates.order_by("-search_count", "pk").values(
            "slug", "search_count"
        )[:limit]
        report[name] = {"total": candidates.count()}
        if include_public_slugs:
            report[name]["public_candidates"] = list(top)
    report["disclosure"] = (
        "This is a review worklist, not an evidence-verification or integrity "
        "finding. Missing DogSource review timestamps do not negate other "
        "documented human moderation. Existing dog and pedigree records are "
        "unchanged; private/hidden records are excluded."
    )
    return report


class Command(BaseCommand):
    help = "Prioritize provenance-review candidates without changing or revealing private dogs."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=15)
        parser.add_argument(
            "--include-public-slugs", action="store_true",
            help="Include a bounded public dog worklist for authorized staff; off by default.",
        )

    def handle(self, *args, **options):
        result = evidence_review_triage(
            limit=options["limit"],
            include_public_slugs=options["include_public_slugs"],
        )
        self.stdout.write(json.dumps(result, sort_keys=True))
