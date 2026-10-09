import hashlib
import hmac
import logging
import os
import time
import uuid
from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.storage import default_storage
from django.db import connection
from django.db.models import Prefetch, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.urls import reverse

from registry.models import Dog, DogImage, DogRegistration, DogSource, HealthRecord, Kennel, Litter, Submission
from registry.permissions import can_manage_verification, can_review_submissions, is_staff_identity
from registry.querysets import one_dog_per_kennel, with_card_image, with_card_registration, with_stored_images

from .seo import json_ld

logger = logging.getLogger(__name__)


def _display_dogs(queryset, *, include_sources=True, include_registrations=True, include_images=True):
    prefetches = []
    if include_images:
        prefetches.append(
            Prefetch("images", queryset=DogImage.objects.order_by("-is_primary", "sort_order", "created_at"), to_attr="display_images")
        )
    if include_registrations:
        prefetches.append(
            Prefetch("registrations", queryset=DogRegistration.objects.select_related("authority"), to_attr="display_registrations")
        )
    queryset = queryset.select_related("kennel").prefetch_related(*prefetches)
    if include_sources:
        queryset = queryset.prefetch_related(
            Prefetch("sources", queryset=DogSource.objects.order_by("-verified_at", "-created_at"), to_attr="display_source_media")
        )
    return queryset


def _source_image_url(sources):
    for source in sources:
        payload = source.raw_payload if isinstance(source.raw_payload, dict) else {}
        image_url = str(payload.get("image_url") or "").strip()
        if not image_url:
            continue
        parsed = urlparse(image_url)
        if (
            parsed.scheme == "https"
            and parsed.hostname in {"canecorsopedigree.com", "www.canecorsopedigree.com"}
            and parsed.path.startswith("/static/images/animal/")
        ):
            return image_url
    return ""


def _attach_source_image_urls(dogs):
    for dog in dogs:
        dog.source_image_url = ""
        if not getattr(dog, "display_images", []):
            dog.source_image_url = _source_image_url(
                getattr(dog, "display_source_media", [])
            )


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.exception("Health check database probe failed")
        response = JsonResponse({"status": "unhealthy"}, status=503)
    else:
        response = JsonResponse({
            "status": "ok",
            "service": "canecorsoancestry",
            # Used to prevent unsafe automatic rollback to a stale Supabase
            # origin after the Oracle-local database accepts production writes.
            "database_backend": (
                "oracle-local" if connection.settings_dict.get("HOST") == "cca-pg-shadow"
                else "supabase"
            ),
            "release": (
                os.getenv("RENDER_GIT_COMMIT")
                or os.getenv("GIT_COMMIT_SHA")
                or ""
            ),
        })
    response["Cache-Control"] = "no-store"
    return response


@csrf_exempt
@require_POST
def storage_probe(request):
    """Private deploy-time check of the exact Django -> R2 media path."""
    supplied = request.headers.get("X-CCA-Storage-Probe", "")
    if not supplied or not hmac.compare_digest(supplied, settings.SECRET_KEY):
        raise Http404

    key = f"smoke/runtime/{uuid.uuid4().hex}.jpg"
    payload = b"\xff\xd8\xff\xe0cca-runtime-r2-probe\xff\xd9"
    saved_name = ""
    stage = "exists"
    signing_key = getattr(settings, "R2_GATEWAY_SIGNING_KEY", "")
    diagnostics = {
        "server_epoch": int(time.time()),
        "signing_fingerprint": hashlib.sha256(
            signing_key.encode("utf-8")
        ).hexdigest()[:16],
    }

    try:
        # Exercise each storage operation separately so a 403 can be attributed
        # to the exact signed request instead of a generic save failure.
        default_storage.exists(key)

        stage = "put"
        if hasattr(default_storage, "save_exact"):
            saved_name = default_storage.save_exact(
                key,
                ContentFile(payload, name="probe.jpg"),
            )
        else:
            saved_name = default_storage.save(
                key,
                ContentFile(payload, name="probe.jpg"),
            )

        stage = "get"
        with default_storage.open(saved_name, "rb") as handle:
            restored = handle.read()
        if restored != payload:
            raise OSError("R2 read-back did not match the uploaded bytes.")
    except Exception as exc:
        logger.exception("Live storage probe failed at stage=%s", stage)
        response = JsonResponse(
            {
                "status": "unhealthy",
                "storage": "r2",
                "stage": stage,
                "error_type": type(exc).__name__,
                "http_status": getattr(exc, "code", None),
                "reason": str(getattr(exc, "reason", "") or "")[:120],
                "auth_reason": (
                    getattr(exc, "headers", {}).get("X-R2-Auth-Reason", "")
                    if getattr(exc, "headers", None)
                    else ""
                ),
                "auth_method": (
                    getattr(exc, "headers", {}).get("X-R2-Auth-Method", "")
                    if getattr(exc, "headers", None)
                    else ""
                ),
                **diagnostics,
            },
            status=503,
        )
    else:
        response = JsonResponse(
            {
                "status": "ok",
                "storage": "r2",
                "stage": "complete",
                **diagnostics,
            }
        )
    finally:
        if saved_name:
            try:
                default_storage.delete(saved_name)
            except Exception:
                logger.exception("Live storage probe cleanup failed")

    response["Cache-Control"] = "no-store"
    return response

def branded_not_found(request, exception=None):
    """Render the customer-facing 404 explicitly in hosted production."""
    return render(request, "404.html", status=404)


def branded_server_error(request):
    """Render the customer-facing 500 explicitly in hosted production."""
    return render(request, "500.html", status=500)


def robots_txt(request):
    body = "\n".join([
        "User-agent: *", "Allow: /",
        "Disallow: /member/", "Disallow: /accounts/", "Disallow: /admin/", "Disallow: /dashboard/",
        f"Sitemap: {request.build_absolute_uri(reverse('sitemap'))}", "",
    ])
    return HttpResponse(body, content_type="text/plain; charset=utf-8")


def _load_featured_dogs():
    """Return four popular imaged dogs without a whole-table window sort."""
    cache_key = "cca:home:featured-dog-ids:v1"
    featured_ids = cache.get(cache_key)

    def load(ids):
        if not ids:
            return []
        rows = list(
            with_card_image(with_card_registration(
                _display_dogs(
                    Dog.objects.filter(pk__in=ids, is_public=True),
                    include_sources=False,
                    include_registrations=False,
                    include_images=False,
                )
            ))
        )
        for dog in rows:
            dog.card_image_url = default_storage.url(dog.card_image_name) if dog.card_image_name else ""
        by_id = {dog.pk: dog for dog in rows}
        return [by_id[dog_id] for dog_id in ids if dog_id in by_id]

    if featured_ids:
        featured = load(featured_ids)
        if len(featured) == len(featured_ids):
            return featured

    candidate_rows = list(
        with_stored_images(Dog.objects.filter(is_public=True))
        .order_by("-search_count", "-updated_at", "name")
        .values_list("pk", "kennel_id")[:96]
    )
    seen_groups = set()
    featured_ids = []
    for dog_id, kennel_id in candidate_rows:
        group_id = kennel_id or dog_id
        if group_id in seen_groups:
            continue
        seen_groups.add(group_id)
        featured_ids.append(dog_id)
        if len(featured_ids) == 4:
            break

    if len(featured_ids) < 4 and len(candidate_rows) == 96:
        # The fast candidate set normally finds four kennel-diverse cards.
        # If one kennel dominates that entire slice, preserve correctness with
        # the exact per-kennel query rather than showing a short homepage row.
        featured_ids = list(
            one_dog_per_kennel(
                with_stored_images(Dog.objects.filter(is_public=True))
            )
            .order_by("-search_count", "-updated_at", "name")
            .values_list("pk", flat=True)[:4]
        )

    cache.set(cache_key, featured_ids, 300)
    return load(featured_ids)


def home(request):
    featured_dogs = _load_featured_dogs()
    public_stats = cache.get("cca:home:public-stats:v4")
    if public_stats is None:
        public_stats = {
            "dog_count": Dog.objects.filter(is_public=True).count(),
            "kennel_count": Kennel.objects.count(),
            "litter_count": Litter.objects.filter(is_public=True).count(),
            "country_count": Dog.objects.filter(is_public=True)
            .exclude(country="")
            .values("country")
            .distinct()
            .count(),
        }
        cache.set("cca:home:public-stats:v4", public_stats, 300)

    public_root = request.build_absolute_uri("/").rstrip("/")
    context = {
        **public_stats,
        "featured_dogs": featured_dogs,
        "structured_data": json_ld({
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": settings.SITE_NAME,
            "url": public_root + "/",
            "description": "Cane Corso pedigree, bloodline, kennel and provenance research.",
            "potentialAction": {
                "@type": "SearchAction",
                "target": {"@type": "EntryPoint", "urlTemplate": public_root + "/dogs/?q={search_term_string}"},
                "query-input": "required name=search_term_string",
            },
        }),
    }
    return render(request, "core/home.html", context)


@login_required
def dashboard(request):
    if is_staff_identity(request.user):
        if can_manage_verification(request.user):
            return redirect("accounts:verification-dashboard")
        if can_review_submissions(request.user):
            return redirect("accounts:moderation")
        return redirect("home")

    memberships = list(
        request.user.kennel_memberships.select_related("kennel").order_by("created_at")
    )
    kennel_ids = [membership.kennel_id for membership in memberships]
    editable_memberships = [
        membership
        for membership in memberships
        if membership.role in {"owner", "editor"}
    ]
    verified_editable_memberships = [
        membership
        for membership in editable_memberships
        if membership.kennel.verified_at
    ]
    primary_membership = (
        verified_editable_memberships[0]
        if verified_editable_memberships
        else editable_memberships[0]
        if editable_memberships
        else memberships[0]
        if memberships
        else None
    )

    member_dogs = Dog.objects.filter(
        Q(kennel_id__in=kennel_ids)
        | Q(
            submissions__kind=Submission.Kind.DOG,
            submissions__status=Submission.Status.APPROVED,
            submissions__submitted_by=request.user,
        )
    ).distinct()
    dogs = list(_display_dogs(member_dogs.order_by("-updated_at"))[:8])
    _attach_source_image_urls(dogs)

    litters_qs = Litter.objects.filter(kennel_id__in=kennel_ids)
    litters = list(
        litters_qs.select_related("kennel", "sire", "dam")
        .order_by("-date_of_birth", "code")[:5]
    )
    health_records = list(
        HealthRecord.objects.filter(dog__in=member_dogs)
        .select_related("dog")
        .order_by("-created_at")[:6]
    )
    recent_submissions = list(
        request.user.ancestry_submissions.select_related(
            "dog", "kennel", "litter", "document"
        )[:5]
    )
    pending_submission_count = request.user.ancestry_submissions.filter(
        status=Submission.Status.PENDING
    ).count()
    recent_payments = list(
        request.user.ancestry_submission_payments.select_related("kennel")[:4]
    )

    return render(
        request,
        "core/dashboard.html",
        {
            "memberships": memberships,
            "primary_membership": primary_membership,
            "primary_kennel": primary_membership.kennel if primary_membership else None,
            "can_purchase_records": bool(verified_editable_memberships),
            "dogs": dogs,
            "litters": litters,
            "health_records": health_records,
            "recent_submissions": recent_submissions,
            "recent_payments": recent_payments,
            "pending_submission_count": pending_submission_count,
            "dog_total": member_dogs.count(),
            "public_dog_total": member_dogs.filter(is_public=True).count(),
            "litter_total": litters_qs.count(),
        },
    )
