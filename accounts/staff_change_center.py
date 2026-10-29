"""Role-aware directory for every supported staff change workflow.

Navigation is not authorization: every destination must enforce its own
server-side permission checks. Keep the directory limited to real routes.
"""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import reverse

from registry.permissions import (
    can_manage_verification,
    can_review_flagged_submissions,
    can_review_submissions,
)


def _action(title, route, steps, *, level=1, query="", fragment="", note=""):
    return {
        "title": title, "route": route, "steps": steps, "level": level,
        "query": query, "fragment": fragment, "note": note,
    }


CATEGORIES = (
    {
        "id": "submissions",
        "title": "Submissions, corrections and disputes",
        "description": "Changes submitted by members are checked against evidence before affecting canonical records.",
        "actions": (
            _action("Review all submissions", "accounts:moderation",
                    "Open a pending case, read the evidence and checks, then approve, reject or request more proof. High-risk cases have separate review rules."),
            _action("Dog applications and pedigree corrections", "accounts:moderation",
                    "Filter by dog or correction, open the exact submission and compare the proposed ancestry with the current record.",
                    query="?kind=dog"),
            _action("Photo uploads and incorrect-photo reports", "accounts:moderation",
                    "Approve uploaded images from the image queue; handle disputed photographs under Open dispute cases, with the original evidence preserved.",
                    query="?kind=image"),
            _action("Health and DNA uploads", "accounts:moderation",
                    "Inspect the private laboratory document, transcribe exact findings, approve and correct the verified values if needed.",
                    query="?kind=health"),
            _action("Documents and publication requests", "accounts:moderation",
                    "Inspect the document and consent request. Approve permitted visibility changes; health evidence and unconsented breed-DNA reports remain private.",
                    query="?kind=document"),
            _action("Kennel and ownership submissions", "accounts:moderation",
                    "Filter the queue for kennel creation, edits and ownership claims; verify entitlement before approval.",
                    query="?kind=kennel"),
            _action("Litter submissions and corrections", "accounts:moderation",
                    "Open new litter or correction submissions; confirm the linked parents, birth date and eligible payment before approval.",
                    query="?kind=litter_create"),
            _action("Resolve disputes and photo corrections", "accounts:moderation",
                    "Open dispute cases, assign one, check evidence and resolve, dismiss or correct an identified photograph with an audit reason.",
                    fragment="#open-disputes"),
            _action("Bulk assignments and priorities", "accounts:moderation",
                    "Select pending cases, choose a supported bulk assignment, priority or rejection, and record a review note.",
                    fragment="#pending-review"),
        ),
    },
    {
        "id": "dogs",
        "title": "Dogs, ancestry and public profiles",
        "description": "Edit existing canonical dogs without bypassing protected pedigree approval.",
        "actions": (
            _action("Find and edit any dog", "accounts:dog-edit-list",
                    "Search by dog name, registration or UUID and select Search records → Manage record. Use Identity & ancestry or Photos & related records, then Save or submit. Check the saved record and expand Revision history for its audit trail."),
            _action("Create a historical/research dog", "accounts:dog-direct-create",
                    "Add a private dog with documentary provenance. Publish only after satisfying the staff research attestation. Paid member listings use submission approval."),
            _action("Submit protected ancestry changes", "accounts:dog-edit-list",
                    "Find a published dog under Manage dogs → Manage record → Identity & ancestry. Submit protected sire, dam, birth, sex, kennel or litter changes separately, then check Revision history. A proposal remains private until Super Admin approval.",
                    note="All moderators can propose changes. Only a Super Admin may approve or reject protected proposals."),
            _action("Inspect dog verification and source fields", "accounts:moderation",
                    "Expand Advanced data tools, choose the exact dog and record the reviewed field, verification state and evidence.",
                    fragment="#record-verification"),
            _action("Merge verified duplicate dogs", "accounts:merge-dogs",
                    "Compare exact canonical and duplicate records, verify ancestry and provenance, then confirm the irreversible audited merge.",
                    level=3),
        ),
    },
    {
        "id": "kennels",
        "title": "Kennels and litters",
        "description": "Manage kennel publication and memberships without silently changing dog ownership.",
        "actions": (
            _action("Find and manage a kennel", "accounts:kennel-publication-list",
                    "Search a kennel, open its publication settings, select the required visibility mode and save the confirmed reason."),
            _action("Associate dogs with kennels", "accounts:kennel-publication-list",
                    "Open a kennel and select Find existing dog to associate. Confirm the dog's registration and submit the protected link for approval where required."),
            _action("Reconcile imported kennel candidates", "accounts:kennel-reconciliation-review",
                    "Review the documentary support for unlinked breeding kennels before confirming a proposed association."),
            _action("Edit kennel metadata and memberships", "admin:registry_kennel_changelist",
                    "Find the kennel in Advanced admin. Edit its descriptive fields; manage verified kennel membership separately. Publication still uses the protected kennel workflow.",
                    level=3),
            _action("Edit approved litter records", "admin:registry_litter_changelist",
                    "Find the litter in Advanced admin, inspect parentage and locks, edit permitted fields and save. Use the review queue for member-submitted changes.",
                    level=3),
            _action("Manage kennel member roles", "admin:registry_kennelmembership_changelist",
                    "Find the exact kennel and user membership. Confirm authority before changing owner, editor or contributor access.",
                    level=3),
        ),
    },
    {
        "id": "health",
        "title": "Health, DNA and supporting evidence",
        "description": "A verified result means an actual finding was checked against accepted evidence; it does not validate unrelated facts.",
        "actions": (
            _action("Enter or change verified health numbers", "accounts:dog-edit-list",
                    "Manage dogs → Search records → Health values. Under Add a condition from an approved report, select one accepted source, enter each exact grade or numeric value and unit, attest to the original certificate, then Save reviewed result."),
            _action("Correct or hide published health results", "accounts:dog-edit-list",
                    "Open Health values for the exact dog. Under Approved health results · Edit as needed, choose Edit & preview, compare the original evidence and Save corrections; use Hide incorrect result to suppress the public summary."),
            _action("Upload reviewed historical laboratory evidence", "accounts:health-genetic-list",
                    "Search the dog and attach the original laboratory evidence with its source and exact result. Unconsented DNA breed composition stays private.",
                    level=3),
            _action("Review submitted certificates", "accounts:moderation",
                    "Filter health uploads, check the original certificate and any extracted marker statuses, and record the final review decision.",
                    query="?kind=health"),
        ),
    },
    {
        "id": "governance",
        "title": "Verification, publication and oversight",
        "description": "Protected edits, exceptions and publication choices must remain auditable.",
        "actions": (
            _action("View all moderation history", "accounts:moderation-audit",
                    "Search changes by record, reviewer or event and compare recorded before/after facts. History is not editable."),
            _action("Review data integrity warnings", "accounts:data-health",
                    "Inspect inconsistencies, then open the appropriate canonical record or submission to make a supported correction."),
            _action("Approve high-risk or second reviews", "accounts:moderation",
                    "Filter red cases, document independent evidence and use the designated override or second-review action. The same person cannot perform both reviews.",
                    level=2, query="?risk=red"),
            _action("Change verification rules", "accounts:verification-dashboard",
                    "Open Verification rules. Change the enabled state, risk level and second-approval requirement, then save the specific rule.",
                    level=3, fragment="#verification-rules"),
            _action("Lock or unlock protected dogs and litters", "accounts:verification-dashboard",
                    "Open Record locking. Enter the exact dog or litter UUID, choose lock/unlock and give a recorded reason.",
                    level=3, fragment="#record-locks"),
            _action("Review and approve protected dog proposals", "accounts:dog-edit-list",
                    "Select Review protected proposals, compare old and proposed ancestry facts and approve or reject the specific change.",
                    level=3, query="?proposals=1"),
        ),
    },
    {
        "id": "team",
        "title": "Staff, member accounts and advanced administration",
        "description": "Only the Super Admin can change moderator authority or remove staff access.",
        "actions": (
            _action("Create a Moderator or Senior Moderator", "accounts:verification-dashboard",
                    "Open Staff accounts, enter a unique dedicated username, email and password, choose the role and create the account.",
                    level=3, fragment="#staff-accounts"),
            _action("Change moderator permissions", "accounts:verification-dashboard",
                    "Open Staff accounts, find the correct Admin number and username, change Authority and select Update role. Never promote member identities.",
                    level=3, fragment="#staff-accounts"),
            _action("Suspend or reactivate a moderator", "accounts:verification-dashboard",
                    "Open Moderator access, select the exact account, choose deactivate/activate and enter a reason. Historical activity remains recorded.",
                    level=3, fragment="#staff-access"),
            _action("Permanently deregister a moderator", "accounts:verification-dashboard",
                    "Under Staff accounts, open Remove moderator permanently for the exact account. Type DEREGISTER, provide an evidence-based reason and confirm. Login is revoked and anonymized; audit history remains.",
                    level=3, fragment="#staff-accounts"),
            _action("Edit member profiles", "admin:accounts_profile_changelist",
                    "Find the correct member profile in Advanced admin, review identity and update only permitted profile details.",
                    level=3),
            _action("Inspect payments and transaction records", "admin:accounts_submissionpayment_changelist",
                    "Review payment status and source references. Payment transactions are intentionally read-only here and must not be fabricated or overwritten.",
                    level=3),
            _action("Advanced model administration", "admin:index",
                    "Open the restricted Django admin to manage supported models and search existing records. Protected actions and immutable audit records remain restricted.",
                    level=3),
        ),
    },
)


@login_required
def staff_change_center(request):
    """Permission-filtered destination map; mutation permissions stay in views."""
    if not can_review_submissions(request.user):
        raise PermissionDenied
    is_super_admin = bool(request.user.is_superuser and can_manage_verification(request.user))
    level = 3 if is_super_admin else 2 if can_review_flagged_submissions(request.user) else 1
    categories = []
    for section in CATEGORIES:
        entries = []
        for action in section["actions"]:
            if action["level"] > level:
                continue
            entries.append({
                **action,
                "url": reverse(action["route"]) + action["query"] + action["fragment"],
                "authority": "Super Admin" if action["level"] == 3 else (
                    "Senior Moderator or Super Admin" if action["level"] == 2
                    else "All active staff reviewers"
                ),
            })
        if entries:
            categories.append({**section, "actions": entries})
    return render(request, "accounts/staff_change_center.html", {
        "categories": categories,
        "staff_level": level,
        "is_super_admin": is_super_admin,
        "workspace_section": "change_center",
    })
