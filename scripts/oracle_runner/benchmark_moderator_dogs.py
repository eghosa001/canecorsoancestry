"""Read-only, anonymized timings for indexed moderator dog lookups in Oracle."""
import os
import statistics
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scripts.oracle_runner.oracle_settings")
import django
django.setup()

from django.db import connection
from registry.models import Dog, DogAlias, DogRegistration
from registry.services import moderation_dog_ids

def median_probe(label, value):
    if not value:
        print(f"SEARCH_BENCH_{label}=no_sample", flush=True)
        return
    timings = []
    for _ in range(5):
        start = time.perf_counter()
        rows = moderation_dog_ids(value, limit=12)
        elapsed = (time.perf_counter() - start) * 1000
        timings.append(elapsed)
    print(
        f"SEARCH_BENCH_{label}_median_ms={statistics.median(timings):.1f} "
        f"results={len(rows)}",
        flush=True,
    )

# Names not logged. Reads a few rows from authoritative Oracle-local PostgreSQL.
row = Dog.objects.order_by("name").values_list("name", flat=True).first()
alias = DogAlias.objects.order_by("pk").values_list("name", flat=True).first()
reg = DogRegistration.objects.order_by("pk").values_list("number", flat=True).first()
print("SEARCH_BENCH_BACKEND=" + connection.vendor, flush=True)
assert connection.vendor == "postgresql", "Only measure the authoritative PostgreSQL backend"
median_probe("exact", row)
median_probe("prefix", row[:7] if row else "")
median_probe("alias", alias)
median_probe("registration", reg)
