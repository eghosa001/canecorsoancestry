from django.conf import settings

PRIVATE_PREFIXES = ("/member/", "/accounts/", "/admin/", "/dashboard/")


def site_metadata(request):
    return {
        "site_name": settings.SITE_NAME,
        "site_url": settings.SITE_URL,
        "canonical_url": f"{settings.SITE_URL}{request.path}",
        "page_noindex": request.path.startswith(PRIVATE_PREFIXES),
        "account_email_enabled": getattr(settings, "ACCOUNT_EMAIL_ENABLED", False),
    }
