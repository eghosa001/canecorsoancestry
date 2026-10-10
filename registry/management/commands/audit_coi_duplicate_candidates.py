"""List source-proven identity duplicates for human review without merging."""
from django.core.management.base import BaseCommand

from registry.coi_identity_audit import audit_registration_backed_duplicates


class Command(BaseCommand):
    help = "Find potential registration-backed pedigree duplicates; never modifies data."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args, **options):
        report = audit_registration_backed_duplicates(
            max_display=options["limit"],
        )
        counts = report["counts"]
        self.stdout.write(
            "COI identity review: "
            f"{counts['matched']} evidence matches; "
            f"{counts['ready']} linked-ancestry candidates; "
            f"{counts['needs_review']} require extra review."
        )
        for row in report["candidates"]:
            self.stdout.write(
                f"{row['status'].upper()} "
                f"canonical={row['canonical_slug']} "
                f"archive={row['source_slug']} "
                f"registration_digits={row['registration_digits']} "
                f"reason={row['reason']}"
            )
        self.stdout.write("READ ONLY: No identities, ancestors or COI values changed.")
