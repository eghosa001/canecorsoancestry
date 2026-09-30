import hashlib
import logging
import time
import uuid

from django.core.cache import cache
from django.http import JsonResponse
from django.utils.cache import patch_cache_control

logger = logging.getLogger(__name__)

PRIVATE_PREFIXES = ("/member/", "/accounts/", "/admin/", "/dashboard/")

CSP = "; ".join(
    [
        "default-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "img-src 'self' data: https:",
        "media-src 'self' https:",
        "font-src 'self' data:",
        "style-src 'self' 'unsafe-inline'",
        "script-src 'self' 'unsafe-inline'",
        "connect-src 'self'",
    ]
)


class RequestSecurityMiddleware:
    """Add request tracing/security headers and keep private pages out of caches/indexes."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.request_id = request_id
        started = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.setdefault("X-Request-ID", request_id)
        response.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        response.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        response.setdefault("Content-Security-Policy", CSP)
        response.setdefault("Cross-Origin-Resource-Policy", "same-site")
        response.setdefault("Server-Timing", f"app;dur={elapsed_ms:.1f}")
        if elapsed_ms >= 1000:
            logger.warning(
                "slow_request path=%s method=%s status=%s duration_ms=%.1f request_id=%s",
                request.path,
                request.method,
                response.status_code,
                elapsed_ms,
                request_id,
            )
        if request.path.startswith(PRIVATE_PREFIXES):
            response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
            patch_cache_control(response, private=True, no_store=True)
        return response



class AbuseProtectionMiddleware:
    """Small cache-backed guard for authentication and contribution abuse.

    This is intentionally dependency-free so it works on the current Render
    deployment. A shared cache can replace LocMem later without changing the
    middleware.
    """

    RULES = (
        ("/accounts/login/", 10, 600),
        ("/member/signup/", 5, 3600),
        ("/member/resend-verification/", 5, 3600),
        ("/member/submit/", 60, 3600),
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "POST":
            rule = next(
                (
                    (limit, window)
                    for prefix, limit, window in self.RULES
                    if request.path.startswith(prefix)
                ),
                None,
            )
            if not rule and request.path.startswith("/member/"):
                user = getattr(request, "user", None)
                if user and user.is_authenticated and not user.is_staff:
                    rule = (120, 3600)
            if rule:
                limit, window = rule
                principal = self._principal(request)
                digest = hashlib.sha256(
                    f"{request.path}|{principal}".encode("utf-8")
                ).hexdigest()
                key = f"abuse:{digest}"
                if cache.add(key, 1, timeout=window):
                    count = 1
                else:
                    try:
                        count = cache.incr(key)
                    except ValueError:
                        cache.set(key, 1, timeout=window)
                        count = 1
                if count > limit:
                    response = JsonResponse(
                        {
                            "detail": (
                                "Too many attempts. Please wait before trying again."
                            )
                        },
                        status=429,
                    )
                    response["Retry-After"] = str(window)
                    response["Cache-Control"] = "no-store"
                    return response
        return self.get_response(request)

    @staticmethod
    def _principal(request):
        if getattr(request, "user", None) and request.user.is_authenticated:
            return f"user:{request.user.pk}"
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        remote = (
            forwarded.split(",", 1)[0].strip()
            if forwarded
            else request.META.get("REMOTE_ADDR", "unknown")
        )
        return f"anon:{remote}"
