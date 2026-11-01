"""Private, in-browser preview of an accepted canine health certificate.

Unlike a generic public media URL, this endpoint checks the exact dog,
acceptance state, and reviewer authority on every request. PDF and image files
are streamed inline; other file types are safely offered as downloads.
"""
import mimetypes

from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from registry.models import Dog
from registry.permissions import can_review_submissions

from .health_sources import approved_health_submissions, accepted_health_documents


def _stream_private_evidence(file_field):
    if not file_field or not file_field.name:
        raise Http404("The approved report has no uploaded file.")
    try:
        handle = default_storage.open(file_field.name, "rb")
    except (FileNotFoundError, OSError) as exc:
        raise Http404("The uploaded report is no longer in storage.") from exc
    name = file_field.name.rsplit("/", 1)[-1]
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    inline = media_type == "application/pdf" or media_type.startswith("image/")
    response = FileResponse(
        handle, content_type=media_type, as_attachment=not inline, filename=name,
    )
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@login_required
@never_cache
@require_GET
def preview_health_submission(request, pk, submission_id):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    dog = get_object_or_404(Dog, pk=pk)
    submission = get_object_or_404(
        approved_health_submissions(dog), pk=submission_id,
    )
    return _stream_private_evidence(submission.attachment)


@login_required
@never_cache
@require_GET
def preview_health_document(request, pk, document_id):
    if not can_review_submissions(request.user):
        raise PermissionDenied
    dog = get_object_or_404(Dog, pk=pk)
    document = get_object_or_404(
        accepted_health_documents(dog), pk=document_id,
    )
    return _stream_private_evidence(document.file)
