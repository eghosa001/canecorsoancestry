"""Reserve unverified archive identities without assigning ownership or inventing dogs."""
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from registry.models import Kennel


HISTORICAL_KENNELS = ("Pet Palace Kennels", "Ofreelife Kennels")


class Command(BaseCommand):
    help = "Prepare unverified Nigerian kennel archive profiles for a source-backed claim workflow."

    def handle(self, *args, **options):
        for name in HISTORICAL_KENNELS:
            slug = slugify(name)
            existing = Kennel.objects.filter(slug=slug).first()
            if existing:
                self.stdout.write(f"Existing: {name} — preserved (no ownership or pedigree changes).")
                continue
            Kennel.objects.create(
                name=name,
                slug=slug,
                country="Nigeria",
                is_public=False,
                description=(
                    "Historical kennel archive awaiting verified ownership and "
                    "source-backed pedigree reconciliation. No imported dogs "
                    "are claimed as verified members of this kennel."
                ),
            )
            self.stdout.write(f"Private archive placeholder created: {name}")
