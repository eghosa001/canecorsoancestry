"""Read-only production audit of moderator-approved publication and R2 files.

Executed inside the existing production Django container via stdin; does not
create, edit or approve a submission. Reports aggregates, not user metadata.
"""
import collections
import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scripts.oracle_runner.oracle_settings")
import django
django.setup()

from django.core.files.storage import default_storage
from django.db.models import Count
from registry.models import (
    DogImage, DogDocument, DogRegistration, HealthRecord,
    Submission, DogIdentityNumber,
)

approved = Submission.objects.filter(status=Submission.Status.APPROVED)
totals = dict(approved.values_list("kind").annotate(n=Count("id")))
print("APPROVED_TYPE_COUNTS", dict(sorted(totals.items())), flush=True)

failures = collections.Counter()
sampled = collections.Counter()
sample_images = []
# Old approved content may subsequently be amended or deliberately removed.
# Collect all current mismatches; only recent live-image R2 probes are strict.
for item in approved.select_related("dog", "kennel", "litter", "document").order_by("-reviewed_at").iterator(chunk_size=100):
    kind = item.kind
    sampled[kind] += 1
    payload = item.payload or {}
    dog = item.dog

    if kind in (Submission.Kind.DOG, Submission.Kind.IMAGE):
        if dog is None:
            failures[kind + ":missing_dog"] += 1
            continue
        if not dog.is_public:
            failures[kind + ":dog_no_longer_public"] += 1
        if item.attachment:
            name = item.attachment.name
            if not DogImage.objects.filter(dog=dog, image=name).exists():
                failures[kind + ":photo_no_longer_linked"] += 1
            elif dog.is_public and len(sample_images) < 12 and name not in sample_images:
                sample_images.append(name)
        elif kind == Submission.Kind.IMAGE:
            failures["image:missing_attachment"] += 1

    elif kind == Submission.Kind.DOCUMENT:
        if not DogDocument.objects.filter(source_submission=item).exists():
            failures["document:no_linked_document"] += 1
        elif bool(payload.get("is_public")) and not DogDocument.objects.filter(
            source_submission=item, is_public=True,
        ).exists():
            failures["document:public_visibility_changed"] += 1

    elif kind == Submission.Kind.HEALTH:
        if not dog or not HealthRecord.objects.filter(
            dog=dog,
            test_type=payload.get("test_type", ""),
            result=payload.get("result", ""),
        ).exists():
            failures["health:no_matching_current_result"] += 1
        if not DogDocument.objects.filter(source_submission=item).exists():
            failures["health:missing_evidence_document"] += 1

    elif kind == Submission.Kind.CORRECTION:
        if dog is None:
            failures["correction:missing_dog"] += 1

    elif kind in (Submission.Kind.KENNEL, Submission.Kind.KENNEL_CREATE, Submission.Kind.KENNEL_CLAIM):
        if item.kennel_id is None:
            failures[kind + ":missing_kennel"] += 1

    elif kind in (Submission.Kind.LITTER_CREATE, Submission.Kind.LITTER_EDIT):
        if item.litter_id is None:
            failures[kind + ":missing_litter"] += 1

    elif kind == Submission.Kind.DOCUMENT_VISIBILITY:
        if item.document_id is None:
            failures["document_visibility:missing_document"] += 1

print("APPROVAL_ROWS_CHECKED", dict(sorted(sampled.items())), flush=True)
print("HISTORICAL_REFERENCE_MISMATCH_COUNTS", dict(sorted(failures.items())), flush=True)
# Also verify that actual approved new-dog records have HTML pages containing
# their approved photo reference, not just an orphaned media object.
import urllib.parse
import urllib.request
from html import escape
base = "https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev"
for index, row in enumerate(
    approved.filter(kind=Submission.Kind.DOG, dog__is_public=True)
    .select_related("dog").order_by("-reviewed_at")[:8], 1
):
    url = base + "/dogs/" + urllib.parse.quote(row.dog.slug) + "/"
    request = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 CCA-Publication-Audit/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=16) as response:
            body = response.read().decode("utf-8", errors="replace")
            name_found = escape(row.dog.name) in body
            image_found = (
                not row.attachment
                or urllib.parse.quote(row.attachment.name, safe="/") in body
            )
            print("APPROVED_DOG_PUBLIC_PROFILE", index,
                  "PASS" if response.status == 200 and name_found and image_found else "FAIL",
                  flush=True)
    except Exception as exc:
        print("APPROVED_DOG_PUBLIC_PROFILE_ERROR", index, type(exc).__name__, flush=True)

print("IMAGE_R2_SAMPLE_SIZE", len(sample_images), flush=True)
for i, name in enumerate(sample_images, 1):
    try:
        exists = default_storage.exists(name)
    except Exception as exc:
        print("IMAGE_R2_PROBE_ERROR", i, type(exc).__name__, flush=True)
        continue
    print("IMAGE_R2_EXISTS", i, "yes" if exists else "NO", flush=True)
    if exists and i <= 5:
        import urllib.request
        public_url = ("https://canecorsoancestry-site-edge.aighewieghosa111.workers.dev"
                      + default_storage.url(name))
        req = urllib.request.Request(
            public_url, headers={"User-Agent": "Mozilla/5.0 CCA-Publication-Audit/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=14) as response:
                content_type = response.headers.get("Content-Type", "")
                head = response.read(16)
                served = response.status == 200 and content_type.startswith("image/") and bool(head)
            print("IMAGE_PUBLIC_HTTP", i, "PASS" if served else "FAIL", flush=True)
        except Exception as exc:
            print("IMAGE_PUBLIC_HTTP_ERROR", i, type(exc).__name__, flush=True)

# The existence of a current public media DB reference and successful R2
# storage read is necessary, but browser rendering is tested separately.
print("READ_ONLY_AUDIT_DONE", flush=True)
