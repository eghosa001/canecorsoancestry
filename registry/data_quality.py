from datetime import timedelta

from django.db.models import F, Q
from django.utils import timezone

from .models import DisputeCase, Dog, Submission, VerificationState


def quick_quality_report(sample_limit=12):
    public = Dog.objects.filter(is_public=True)
    total_public = public.count()
    source_backed = public.filter(sources__isnull=False).distinct().count()
    verified_source_backed = public.filter(
        sources__verified_at__isnull=False
    ).distinct().count()
    pedigree_linked = public.filter(Q(sire__isnull=False) | Q(dam__isnull=False)).count()

    issue_sets = {
        "public_without_sources": public.filter(sources__isnull=True).distinct(),
        "community_only_public": public.filter(
            verification_state=VerificationState.COMMUNITY
        ),
        "unknown_sex_public": public.filter(sex=Dog.Sex.UNKNOWN),
        "sire_sex_conflicts": Dog.objects.filter(sire__sex=Dog.Sex.FEMALE),
        "dam_sex_conflicts": Dog.objects.filter(dam__sex=Dog.Sex.MALE),
        "same_parent_conflicts": Dog.objects.filter(
            sire__isnull=False, sire=F("dam")
        ),
        "parent_date_conflicts": Dog.objects.filter(
            date_of_birth__isnull=False
        ).filter(
            Q(sire__date_of_birth__gte=F("date_of_birth"))
            | Q(dam__date_of_birth__gte=F("date_of_birth"))
        ),
    }

    counts = {key: queryset.count() for key, queryset in issue_sets.items()}
    counts.update(
        {
            "public_dogs": total_public,
            "source_backed_public": source_backed,
            "verified_source_backed_public": verified_source_backed,
            "pedigree_linked_public": pedigree_linked,
            "pending_submissions": Submission.objects.filter(
                status=Submission.Status.PENDING
            ).count(),
            "aging_submissions": Submission.objects.filter(
                status=Submission.Status.PENDING,
                created_at__lt=timezone.now() - timedelta(days=7),
            ).count(),
            "open_disputes": DisputeCase.objects.filter(
                status__in=[
                    DisputeCase.Status.OPEN,
                    DisputeCase.Status.REVIEWING,
                ]
            ).count(),
        }
    )

    return {
        "counts": counts,
        "source_coverage_percent": (
            source_backed / total_public * 100 if total_public else 100.0
        ),
        "verified_source_coverage_percent": (
            verified_source_backed / total_public * 100 if total_public else 100.0
        ),
        "pedigree_linkage_percent": (
            pedigree_linked / total_public * 100 if total_public else 100.0
        ),
        "samples": {
            key: list(
                queryset.select_related("sire", "dam", "kennel")
                .only(
                    "id",
                    "name",
                    "slug",
                    "sex",
                    "date_of_birth",
                    "sire__id",
                    "sire__name",
                    "sire__sex",
                    "sire__date_of_birth",
                    "dam__id",
                    "dam__name",
                    "dam__sex",
                    "dam__date_of_birth",
                    "kennel__id",
                    "kennel__name",
                )[:sample_limit]
            )
            for key, queryset in issue_sets.items()
        },
    }


def pedigree_cycles(limit=50):
    graph = {
        dog_id: tuple(parent for parent in (sire_id, dam_id) if parent)
        for dog_id, sire_id, dam_id in Dog.objects.values_list(
            "id", "sire_id", "dam_id"
        )
    }
    state = {}
    stack = []
    found = []

    def visit(node):
        marker = state.get(node, 0)
        if marker == 1:
            if node in stack:
                cycle = stack[stack.index(node):] + [node]
                found.append(cycle)
            return
        if marker == 2 or len(found) >= limit:
            return
        state[node] = 1
        stack.append(node)
        for parent in graph.get(node, ()):
            visit(parent)
            if len(found) >= limit:
                break
        stack.pop()
        state[node] = 2

    for node in graph:
        if state.get(node, 0) == 0:
            visit(node)
        if len(found) >= limit:
            break
    return found


def full_quality_report(sample_limit=12, cycle_limit=50):
    report = quick_quality_report(sample_limit=sample_limit)
    cycles = pedigree_cycles(limit=cycle_limit)
    report["cycles"] = cycles
    report["counts"]["pedigree_cycles"] = len(cycles)
    report["critical_count"] = sum(
        report["counts"].get(key, 0)
        for key in (
            "sire_sex_conflicts",
            "dam_sex_conflicts",
            "same_parent_conflicts",
            "parent_date_conflicts",
            "pedigree_cycles",
        )
    )
    return report
