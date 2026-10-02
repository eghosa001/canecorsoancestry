from django.conf import settings

PRIVATE_PREFIXES = ("/member/", "/accounts/", "/admin/", "/dashboard/")


def site_metadata(request):
    account_name = ""
    if request.user.is_authenticated:
        try:
            account_name = request.user.profile.display_name
        except Exception:
            account_name = ""
        if not account_name:
            membership = (
                request.user.kennel_memberships.select_related("kennel")
                .order_by("created_at")
                .first()
            )
            account_name = (
                membership.kennel.name if membership else request.user.get_username()
            )

    public_root = request.build_absolute_uri("/").rstrip("/")
    return {
        "site_name": settings.SITE_NAME,
        "site_url": public_root,
        "canonical_url": request.build_absolute_uri(request.path),
        "page_noindex": request.path.startswith(PRIVATE_PREFIXES),
        "account_email_enabled": getattr(settings, "ACCOUNT_EMAIL_ENABLED", False),
        "account_name": account_name,
    }
