import mimetypes
import time

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.media_migration import body_sha256, valid_migration_signature
from registry.models import DisputeCase, DogDocument, DogImage, DogSource, Submission


def _member_kennel_ids(user):
    if not user.is_authenticated:
        return []
    return list(user.kennel_memberships.values_list("kennel_id", flat=True))


def _known_media_path(path):
    return (
        DogImage.objects.filter(image=path).exists()
        or DogDocument.objects.filter(file=path).exists()
        or DogSource.objects.filter(document=path).exists()
        or Submission.objects.filter(attachment=path).exists()
        or DisputeCase.objects.filter(attachment=path).exists()
    )


def _can_read_media(user, path):
    public = (
        DogImage.objects.filter(image=path, dog__is_public=True).exists()
        or DogDocument.objects.filter(
            file=path,
            is_public=True,
            dog__is_public=True,
        ).exists()
    )
    if public:
        return True, True

    if not user.is_authenticated:
        return False, False
    if user.is_staff:
        return True, False

    kennel_ids = _member_kennel_ids(user)
    allowed = (
        DogDocument.objects.filter(
            file=path,
        )
        .filter(
            submitted_by=user
        )
        .exists()
        or DogDocument.objects.filter(
            file=path,
            dog__kennel_id__in=kennel_ids,
        ).exists()
        or Submission.objects.filter(
            attachment=path,
        )
        .filter(
            submitted_by=user
        )
        .exists()
        or Submission.objects.filter(
            attachment=path,
            kennel_id__in=kennel_ids,
        ).exists()
        or DisputeCase.objects.filter(
            attachment=path,
            opened_by=user,
        ).exists()
        or DogSource.objects.filter(
            document=path,
            dog__kennel_id__in=kennel_ids,
        ).exists()
    )
    return allowed, False


def media_file(request, path):
    allowed, public = _can_read_media(request.user, path)
    if not allowed:
        raise Http404

    try:
        handle = default_storage.open(path, "rb")
    except FileNotFoundError as exc:
        raise Http404 from exc

    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    response = FileResponse(handle, content_type=content_type)
    response["Content-Disposition"] = 'inline; filename="' + path.rsplit("/", 1)[-1] + '"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = (
        "public, max-age=86400" if public else "private, no-store"
    )
    return response


@csrf_exempt
@require_POST
def media_import(request, path):
    if not getattr(settings, "MEDIA_MIGRATION_ENABLED", False):
        raise Http404

    if not _known_media_path(path):
        raise Http404

    raw_timestamp = request.headers.get("X-Migration-Timestamp", "")
    provided_signature = request.headers.get("X-Migration-Signature", "")
    try:
        timestamp = int(raw_timestamp)
    except (TypeError, ValueError):
        return HttpResponseForbidden("Invalid migration timestamp.")

    if abs(int(time.time()) - timestamp) > 300:
        return HttpResponseForbidden("Expired migration request.")

    body = request.body
    digest = body_sha256(body)
    if not valid_migration_signature(
        settings.SECRET_KEY,
        raw_timestamp,
        path,
        digest,
        provided_signature,
    ):
        return HttpResponseForbidden("Invalid migration signature.")

    max_size = int(getattr(settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 25 * 1024 * 1024))
    if len(body) > max_size:
        return JsonResponse({"error": "Object exceeds migration size limit."}, status=413)

    if default_storage.exists(path) and default_storage.size(path) == len(body):
        with default_storage.open(path, "rb") as existing:
            existing_digest = body_sha256(existing.read())
        if existing_digest == digest:
            return JsonResponse(
                {
                    "status": "exists",
                    "path": path,
                    "size": len(body),
                    "sha256": digest,
                }
            )

    save_exact = getattr(default_storage, "save_exact", None)
    if save_exact is None:
        return JsonResponse({"error": "Exact-key storage is unavailable."}, status=500)

    save_exact(path, ContentFile(body, name=path))
    return JsonResponse(
        {
            "status": "stored",
            "path": path,
            "size": len(body),
            "sha256": digest,
        },
        status=201,
    )
