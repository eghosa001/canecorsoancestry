"""Require an authenticated Cloudflare edge for Oracle application endpoints."""

import hmac
from pathlib import Path

from django.http import HttpResponse

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

class OracleMigrationMaintenanceMiddleware:
    """Root-managed write-freeze: block traffic while taking a final DB snapshot.

    The flag directory is a host bind mount presented read-only to Django.
    An authenticated secret-bearing local smoke probe may bypass during rollout.
    Ordinary users and payment webhooks receive 503 + Retry-After instead
    of risking writes to two different databases.
    """
    FLAG = Path("/run/cca/maintenance.flag")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/healthz/":
            return self.get_response(request)
        try:
            frozen = self.FLAG.exists()
        except PermissionError:
            # Fail closed rather than returning HTTP 500 and potentially
            # allowing writes during a split-brain database migration.
            frozen = True
        if not frozen:
            return self.get_response(request)
        probe = request.headers.get("X-CCA-Maintenance-Probe", "")
        if (probe and request.headers.get("X-CCA-Edge") == "1"
                and hmac.compare_digest(probe, settings.SECRET_KEY)):
            return self.get_response(request)
        response = HttpResponse(
            "<!doctype html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Brief Maintenance - Cane Corso Ancestry</title></head>"
            "<body style='font:16px system-ui;margin:12vh auto;max-width:38rem;padding:1.5rem'>"
            "<h1>Brief scheduled maintenance</h1>"
            "<p>Pedigrees and account services are temporarily unavailable while the database is updated.</p>"
            "<p>Please try again shortly. No submission has been accepted during maintenance.</p>"
            "</body></html>",
            status=503, content_type="text/html; charset=utf-8",
        )
        response["Retry-After"] = "120"
        response["Cache-Control"] = "no-store, max-age=0"
        response["X-Robots-Tag"] = "noindex, nofollow"
        return response
