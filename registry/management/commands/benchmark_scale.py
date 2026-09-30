import time
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from pedigrees.services import descendant_generations
from registry.models import Dog, normalize_identity_name


class Command(BaseCommand):
    help = "Run a rollback-only scale benchmark with synthetic public pedigree records."

    def add_arguments(self, parser):
        parser.add_argument("--dogs", type=int, default=10000)
        parser.add_argument("--max-search-ms", type=float, default=750.0)
        parser.add_argument("--max-popular-ms", type=float, default=500.0)
        parser.add_argument("--allow-production", action="store_true")

    def handle(self, *args, **options):
        total = options["dogs"]
        if total < 100 or total > 100000:
            raise CommandError("--dogs must be between 100 and 100000.")
        if not settings.DEBUG and not options["allow_production"]:
            raise CommandError(
                "Scale benchmarks are disabled outside DEBUG unless --allow-production is explicit."
            )

        token = uuid.uuid4().hex[:10]
        prefix = f"ScaleBench-{token}"

        with transaction.atomic():
            sire = Dog.objects.create(
                name=f"{prefix} Sire",
                slug=f"{prefix.lower()}-sire",
                sex=Dog.Sex.MALE,
                is_public=True,
            )
            dam = Dog.objects.create(
                name=f"{prefix} Dam",
                slug=f"{prefix.lower()}-dam",
                sex=Dog.Sex.FEMALE,
                is_public=True,
            )

            batch = []
            for index in range(total):
                name = f"{prefix} Dog {index:06d}"
                batch.append(
                    Dog(
                        name=name,
                        normalized_name=normalize_identity_name(name),
                        slug=f"{prefix.lower()}-dog-{index:06d}",
                        sex=Dog.Sex.MALE if index % 2 == 0 else Dog.Sex.FEMALE,
                        sire=sire if index < min(total, 5000) else None,
                        dam=dam if index < min(total, 5000) else None,
                        is_public=True,
                        search_count=index % 1000,
                    )
                )
                if len(batch) >= 2000:
                    Dog.objects.bulk_create(batch, batch_size=2000)
                    batch.clear()
            if batch:
                Dog.objects.bulk_create(batch, batch_size=2000)

            started = time.perf_counter()
            search_rows = list(
                Dog.objects.filter(
                    is_public=True,
                    name__icontains=f"{prefix} Dog 000",
                )
                .only("id", "name", "slug")
                .order_by("name")[:24]
            )
            search_ms = (time.perf_counter() - started) * 1000

            started = time.perf_counter()
            popular_rows = list(
                Dog.objects.filter(is_public=True)
                .only("id", "name", "slug", "search_count")
                .order_by("-search_count", "name")[:24]
            )
            popular_ms = (time.perf_counter() - started) * 1000

            started = time.perf_counter()
            descendants = descendant_generations(
                sire, generations=4, public_only=True
            )
            descendant_ms = (time.perf_counter() - started) * 1000
            descendant_count = sum(len(layer["dogs"]) for layer in descendants)

            self.stdout.write(
                self.style.SUCCESS(
                    f"Scale benchmark ({total:,} synthetic dogs; rollback-only)"
                )
            )
            self.stdout.write(
                f"search: {search_ms:.1f} ms ({len(search_rows)} rows)"
            )
            self.stdout.write(
                f"popular: {popular_ms:.1f} ms ({len(popular_rows)} rows)"
            )
            self.stdout.write(
                f"reverse pedigree: {descendant_ms:.1f} ms ({descendant_count} descendants)"
            )

            failures = []
            if search_ms > options["max_search_ms"]:
                failures.append(
                    f"search {search_ms:.1f}ms > {options['max_search_ms']:.1f}ms"
                )
            if popular_ms > options["max_popular_ms"]:
                failures.append(
                    f"popular {popular_ms:.1f}ms > {options['max_popular_ms']:.1f}ms"
                )

            transaction.set_rollback(True)

        if failures:
            raise CommandError("Scale budget exceeded: " + "; ".join(failures))
