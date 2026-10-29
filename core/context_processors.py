from django.conf import settings

from registry.permissions import admin_public_label, is_staff_identity, moderation_role

PRIVATE_PREFIXES = ("/member/", "/accounts/", "/admin/", "/dashboard/")


def _private_research_path(request):
    if request.path == "/pedigrees/virtual-mating/":
        return request.user.is_authenticated
    return request.path.startswith("/pedigrees/") and request.path != "/pedigrees/"


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
        staff_sections = {
            "accounts:verification-dashboard": "verification",
            "accounts:staff-change-center": "change_center",
            "accounts:moderation": "queue",
            "accounts:moderation-submission": "queue",
            "accounts:dog-edit-list": "dogs",
            "accounts:dog-direct-edit": "dogs",
            "accounts:dog-review-edit": "dogs",
            "accounts:dog-direct-create": "dog_new",
            "accounts:kennel-publication-list": "kennels",
            "accounts:kennel-publication-detail": "kennels",
            "accounts:kennel-publication-change": "kennels",
            "accounts:kennel-dogs-visibility-change": "kennels",
            "accounts:kennel-reconciliation-review": "kennels",
            "accounts:moderation-audit": "audit",
            "accounts:data-health": "health",
            "accounts:data-health-evidence": "health",
            "accounts:health-genetic-list": "health_dna",
            "accounts:health-genetic-dog": "health_dna",
            "accounts:reviewed-dog-health": "health_dna",
            "accounts:merge-dogs": "merge",
        }
        workspace_section = staff_sections.get(view_name, "queue")
    else:
        member_sections = {
            "accounts:my-pedigrees": "dogs",
            "accounts:member-pedigree": "dogs",
            "accounts:member-pedigree-export": "dogs",
            "accounts:saved-pairings": "research",
            "accounts:compare-saved-pairings": "research",
            "accounts:my-litters": "litters",
            "accounts:edit-litter": "litters",
            "accounts:submit-litter": "litters",
            "accounts:submissions": "submissions",
            "accounts:draft-checkout": "submissions",
            "accounts:submit-dog": "submissions",
            "accounts:submit-image": "submissions",
            "accounts:submit-correction": "submissions",
            "accounts:submit-health-record": "submissions",
            "accounts:submit-document": "submissions",
            "accounts:submission-evidence-upload": "submissions",
            "accounts:documents": "documents",
            "accounts:document-visibility": "documents",
            "accounts:my-disputes": "disputes",
            "accounts:open-dispute": "disputes",
            "accounts:profile": "profile",
            "accounts:notifications": "notifications",
            "accounts:new-payment": "payments",
            "accounts:payment-detail": "payments",
        }
        workspace_section = member_sections.get(view_name, "overview")

    # A canonical URL must not depend on a visitor's Host header or the
    # temporary workers.dev hostname once SITE_URL moves to a custom domain.
    public_root = settings.SITE_URL
    return {
        "site_name": settings.SITE_NAME,
        "support_email": getattr(settings, "SUPPORT_EMAIL", ""),
        "site_url": public_root,
        "canonical_url": f"{settings.SITE_URL}{request.path}",
        "page_noindex": request.path.startswith(PRIVATE_PREFIXES) or _private_research_path(request),
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
