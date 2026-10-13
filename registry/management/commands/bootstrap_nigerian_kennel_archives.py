"""Prepare private kennel archive placeholders without asserting ownership.

The default examples are not a fixed list; any named kennel can use this.
Existing records are preserved.
"""
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from registry.models import Kennel


DEFAULT_KENNELS = ("Pet Palace Kennels", "Ofreelife Kennels")


class Command(BaseCommand):
    help = "Reserve private unverified archive profiles for any named kennel."

    def add_arguments(self, parser):
        parser.add_argument(
            "--kennel", "--kennel-name",
            action="append", dest="kennel_names", metavar="NAME",
            help="Repeat for additional kennels. Omit for the initial examples.",
        )

    def handle(self, *args, **options):
        names = options["kennel_names"]
        if names is None:
            names = DEFAULT_KENNELS
        seen = set()
        for supplied in names:
            name = " ".join(supplied.split())
            if not name or len(name) > 180:
                raise CommandError("Kennel name must contain 1–180 characters.")
            slug = slugify(name)[:190]
            if not slug:
                raise CommandError("Kennel name has no usable URL slug.")
            if slug in seen:
                continue
            seen.add(slug)

            existing = Kennel.objects.filter(slug=slug).first()
            if existing:
                self.stdout.write(
                    f"Existing: {existing.name} — preserved (no ownership or pedigree changes)."
                )
                continue
            kennel, created = Kennel.objects.get_or_create(
                slug=slug,
                defaults={
                    "name": name,
                    "country": "Nigeria",
                    "is_public": False,
                    "description": (
                        "Historical kennel archive awaiting verified ownership "
                        "and source-backed pedigree reconciliation. No imported "
                        "dogs are claimed as verified members of this kennel."
                    ),
                },
            )
            if created:
                self.stdout.write(f"Private archive placeholder created: {kennel.name}")
            else:
                self.stdout.write(
                    f"Existing: {kennel.name} — preserved (no ownership or pedigree changes)."
                )
