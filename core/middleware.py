import hashlib
import hmac
import os
import uuid

from django.conf import settings
from django.http import HttpResponseForbidden
from django.utils.cache import patch_cache_control

PRIVATE_PREFIXES = ("/member/", "/accounts/", "/admin/", "/dashboard/")


class RequestSecurityMiddleware:
    """Add request tracing/security headers and keep private pages out of caches/indexes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.request_id = request_id
        response = self.get_response(request)
        response.setdefault("X-Request-ID", request_id)
        response.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        response.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        if request.path.startswith(PRIVATE_PREFIXES):
            response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
            patch_cache_control(response, private=True, no_store=True)
        return response


class CloudRunEdgeMiddleware:
    """Reject direct Cloud Run traffic when the Cloudflare edge gate is enabled."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.enabled = os.getenv("REQUIRE_CLOUDFLARE_EDGE", "0") == "1"
        self.expected = hmac.new(
            settings.SECRET_KEY.encode("utf-8"),
            b"canecorsoancestry-cloud-run-edge",
            hashlib.sha256,
        ).hexdigest()

    def __call__(self, request):
        if (
            self.enabled
            and request.path != "/healthz/"
            and not hmac.compare_digest(
                request.headers.get("X-Cane-Edge-Auth", ""),
                self.expected,
            )
        ):
            return HttpResponseForbidden("Cloudflare edge authorization required.")
        return self.get_response(request)
