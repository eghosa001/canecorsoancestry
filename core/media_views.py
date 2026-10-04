import mimetypes

from django.conf import settings
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponseRedirect

from core.cloudflare_media import signed_media_url
from registry.models import DisputeCase, DogDocument, DogImage, DogSource, Submission, SubmissionEvidence


def _member_kennel_ids(user):
    if not user.is_authenticated:
        return []
    return list(user.kennel_memberships.values_list("kennel_id", flat=True))


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
            submitted_by=user,
        ).exists()
        or DogDocument.objects.filter(
            file=path,
            dog__kennel_id__in=kennel_ids,
        ).exists()
        or Submission.objects.filter(
            attachment=path,
            submitted_by=user,
        ).exists()
        or Submission.objects.filter(
            attachment=path,
            kennel_id__in=kennel_ids,
        ).exists()
        or SubmissionEvidence.objects.filter(
            file=path,
            submission__submitted_by=user,
        ).exists()
        or SubmissionEvidence.objects.filter(
            file=path,
            submission__kennel_id__in=kennel_ids,
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

    media_base = getattr(settings, "MEDIA_EDGE_BASE_URL", "").strip()
    if media_base:
        response = HttpResponseRedirect(
            signed_media_url(
                media_base,
                path,
                settings.SECRET_KEY,
                ttl=getattr(settings, "MEDIA_EDGE_URL_TTL", 300),
            )
        )
        response["Cache-Control"] = (
            "public, max-age=60" if public else "private, no-store"
        )
        return response

    try:
        handle = default_storage.open(path, "rb")
    except FileNotFoundError as exc:
        raise Http404 from exc

    content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    response = FileResponse(handle, content_type=content_type)
    disposition = "inline" if content_type.startswith("image/") else "attachment"
    response["Content-Disposition"] = (
        disposition + '; filename="' + path.rsplit("/", 1)[-1] + '"'
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = (
        "public, max-age=86400" if public else "private, no-store"
    )
    return response
