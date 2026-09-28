import uuid

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
