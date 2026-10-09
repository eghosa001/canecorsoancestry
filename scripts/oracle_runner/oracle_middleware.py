"""Require an authenticated Cloudflare edge for Oracle application endpoints."""

import hmac

from django.conf import settings
from django.http import HttpResponseForbidden


class OracleEdgeOnlyMiddleware:
    """Block direct-origin access even if forwarded Host headers are forged."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Public, unauthenticated DB-backed readiness probe for the local host.
        if request.path == "/healthz/" and request.method in {"GET", "HEAD"}:
            return self.get_response(request)

        signature = request.headers.get("X-CCA-Origin-Secret", "")
        marker = request.headers.get("X-CCA-Edge", "")
        if not (
            marker == "1"
            and signature
            and hmac.compare_digest(signature, settings.SECRET_KEY)
        ):
            response = HttpResponseForbidden("Origin access denied.")
            response["Cache-Control"] = "no-store"
            response["X-Robots-Tag"] = "noindex, nofollow"
            return response

        return self.get_response(request)
