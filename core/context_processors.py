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

    # Keep each signed-in workspace navigable across all its subpages.
    # Role-specific links are chosen on the server, never from a URL query.
    view_name = getattr(getattr(request, "resolver_match", None), "view_name", "") or ""
    workspace_nav = bool(
        request.user.is_authenticated
        and request.path.startswith("/member/")
        and request.path != "/member/signup/"
        and (staff_role or not staff_identity)
    )
    if staff_role:
        if view_name == "accounts:verification-dashboard":
            workspace_section = "verification"
        elif view_name in {"accounts:dog-edit-list", "accounts:dog-direct-edit", "accounts:dog-review-edit"}:
            workspace_section = "dogs"
        elif view_name == "accounts:moderation-audit":
            workspace_section = "audit"
        elif view_name == "accounts:data-health":
            workspace_section = "health"
        else:
            workspace_section = "queue"
    else:
        workspace_section = {
            "accounts:my-pedigrees": "dogs",
            "accounts:member-pedigree": "dogs",
            "accounts:my-litters": "litters",
            "accounts:edit-litter": "litters",
            "accounts:submissions": "submissions",
            "accounts:profile": "profile",
            "accounts:notifications": "notifications",
            "accounts:new-payment": "payments",
            "accounts:payment-detail": "payments",
        }.get(view_name, "overview")

    public_root = request.build_absolute_uri("/").rstrip("/")
    return {
        "site_name": settings.SITE_NAME,
        "site_url": public_root,
        "canonical_url": request.build_absolute_uri(request.path),
        "page_noindex": request.path.startswith(PRIVATE_PREFIXES),
        "account_email_enabled": getattr(settings, "ACCOUNT_EMAIL_ENABLED", False),
        "account_name": account_name,
        "staff_identity": staff_identity,
        "workspace_nav": workspace_nav,
        "workspace_section": workspace_section,
        "staff_role": staff_role,
        "staff_role_label": {
            "owner": "Super Admin",
            "senior": "Senior Moderator",
            "reviewer": "Moderator",
        }.get(staff_role, "Staff"),
    }
