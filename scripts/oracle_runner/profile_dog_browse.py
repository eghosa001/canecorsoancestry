"""Read-only live Oracle PostgreSQL diagnostic for the unfiltered dog catalogue.

No objects are created, changed or deleted; aggregates and SQL plans only.
"""
import os
import time
from django.db import connection

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scripts.oracle_runner.oracle_settings")
import django
django.setup()

from django.db.models import Q
from registry.models import Dog
from registry.querysets import with_displayable_images, one_dog_per_kennel

assert connection.vendor == "postgresql", "Read-only diagnosis requires PostgreSQL"
assert connection.settings_dict.get("HOST") == "cca-pg-shadow", "Refusing nonlocal database"
assert connection.settings_dict.get("NAME") == "cca_live", "Refusing unexpected database"
public = Dog.objects.filter(is_public=True)
imaged = with_displayable_images(public)
grouped = one_dog_per_kennel(imaged)

def sample(label, thunk):
    started = time.perf_counter()
    result = thunk()
    elapsed = (time.perf_counter() - started) * 1000
    print(f"DOG_BROWSE_{label}_MS={elapsed:.1f}", flush=True)
    if isinstance(result, int):
        print(f"DOG_BROWSE_{label}_COUNT={result}", flush=True)

sample("public_count", lambda: public.count())
sample("image_filtered_count", lambda: imaged.count())
sample("grouped_count", lambda: grouped.count())
sample("imaged_page", lambda: list(imaged.order_by("-search_count", "-updated_at", "name").values_list("pk", flat=True)[:18]))
sample("grouped_page", lambda: list(grouped.order_by("-search_count", "-updated_at", "name").values_list("pk", flat=True)[:18]))
for label, queryset in (("imaged_page", imaged.order_by("-search_count", "-updated_at", "name").values_list("pk", flat=True)[:18]), ("grouped_page", grouped.order_by("-search_count", "-updated_at", "name").values_list("pk", flat=True)[:18])):
    # Django's explain() cannot wrap the qualified subselect used when filtering
    # a window function. EXPLAIN the compiled read-only SQL directly instead.
    sql, params = queryset.query.get_compiler(connection=connection).as_sql()
    with connection.cursor() as cursor:
        cursor.execute("EXPLAIN (COSTS TRUE) " + sql, params)
        plan = "\n".join(row[0] for row in cursor.fetchall())
    print(f"DOG_BROWSE_{label}_EXPLAIN_BEGIN", flush=True)
    print(plan[:12000], flush=True)
    print(f"DOG_BROWSE_{label}_EXPLAIN_END", flush=True)
print("DOG_BROWSE_READ_ONLY_DIAG_DONE", flush=True)
