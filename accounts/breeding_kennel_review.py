"""Read-only, staff-only review of historically unlinked breeding kennels."""
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render

from registry.archive_breeder_hints import archive_name_clusters, archive_pattern_hints
from registry.management.commands.reconcile_breeding_kennels import (
    _kennel_maps, assess,
)
from registry.models import Dog, DogSource, Kennel
from registry.permissions import can_manage_verification, can_review_submissions


@login_required
def kennel_reconciliation_review(request):
    if not can_review_submissions(request.user):
        raise PermissionDenied("Only authorized moderators may review missing breeding kennels.")
    query = request.GET.get("q", "").strip()[:120]
    dogs = (
        Dog.objects.filter(kennel__isnull=True)
        .select_related("litter__kennel")
        .order_by("name", "pk")
    )
    if query:
        dogs = dogs.filter(name__icontains=query)
    page = Paginator(dogs, 60).get_page(request.GET.get("page"))
    ids = [dog.pk for dog in page.object_list]
    source_groups = defaultdict(list)
    for source in DogSource.objects.filter(dog_id__in=ids).only(
        "dog_id", "title", "raw_payload"
    ):
        source_groups[source.dog_id].append(source)
    by_name, patterns = _kennel_maps(list(
        Kennel.objects.only("pk", "name", "slug", "verified_at")
    ))
    rows = []
    for dog in page.object_list:
        category, match, reason, hints = assess(
            dog, source_groups.get(dog.pk, ()), by_name, patterns
        )
        rows.append({
            "dog": dog,
            "category": category,
            "reason": reason.replace("_", " "),
            "hints": ([match] if match else hints)[:3],
            "archive_name_hypotheses": archive_pattern_hints(dog.name, limit=3),
        })
    cluster_catalog = archive_name_clusters()
    show_all_clusters = request.GET.get("clusters") == "all"
    return render(request, "accounts/breeding_kennel_reconciliation.html", {
        "page_obj": page,
        "rows": rows,
        "query": query,
        "unlinked_total": Dog.objects.filter(kennel__isnull=True).count(),
        "is_superadmin": can_manage_verification(request.user),
        "archive_clusters": (
            cluster_catalog if show_all_clusters else cluster_catalog[:24]
        ),
        "archive_cluster_total": len(cluster_catalog),
        "show_all_clusters": show_all_clusters,
    })
