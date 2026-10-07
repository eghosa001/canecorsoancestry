from django.conf import settings

from registry.permissions import admin_public_label, is_staff_identity, moderation_role

PRIVATE_PREFIXES = ("/member/", "/accounts/", "/admin/", "/dashboard/")


def site_metadata(request):
    account_name = ""
    staff_identity = False
    staff_role = None
    if request.user.is_authenticated:
        staff_identity = is_staff_identity(request.user)
        staff_role = moderation_role(request.user)
        if staff_identity:
            account_name = admin_public_label(request.user)
        else:
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
        "staff_identity": staff_identity,
        "staff_role": staff_role,
    }
