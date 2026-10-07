from .models import KennelMembership, ModerationRoleAssignment, Submission


def membership_for(user, kennel):
    if not user.is_authenticated or kennel is None:
        return None
    return KennelMembership.objects.filter(user=user, kennel=kennel).first()


def has_member_identity(user):
    """Return True once an account has participated in member-owned workflows."""
    if not getattr(user, "is_authenticated", False):
        return False
    if KennelMembership.objects.filter(user=user).exists():
        return True
    return Submission.objects.filter(submitted_by=user).exists()


def moderation_assignment(user):
    """Return the explicit staff assignment; never infer moderation from is_staff."""
    if not getattr(user, "is_authenticated", False):
        return None
    if has_member_identity(user):
        return None

    try:
        assignment = user.ancestry_moderation_role
    except ModerationRoleAssignment.DoesNotExist:
        assignment = None

    if getattr(user, "is_superuser", False):
        if assignment is None:
            assignment = ModerationRoleAssignment.objects.create(
                user=user,
                role=ModerationRoleAssignment.Role.OWNER,
                assigned_by=user,
            )
        elif assignment.role != ModerationRoleAssignment.Role.OWNER:
            assignment.role = ModerationRoleAssignment.Role.OWNER
            assignment.save(update_fields=("role",))
        return assignment

    return assignment


def is_staff_identity(user):
    """Staff identities are permanently separate from member identities."""
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    try:
        user.ancestry_moderation_role
    except ModerationRoleAssignment.DoesNotExist:
        return False
    return True


def can_use_member_features(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and not is_staff_identity(user)
    )


def can_contribute_to_kennel(user, kennel):
    if not can_use_member_features(user):
        return False
    return membership_for(user, kennel) is not None


def can_edit_kennel(user, kennel):
    if not can_use_member_features(user):
        return False
    membership = membership_for(user, kennel)
    return bool(
        membership
        and membership.role
        in {KennelMembership.Role.OWNER, KennelMembership.Role.EDITOR}
    )


def can_contribute_to_dog(user, dog):
    if not can_use_member_features(user) or dog is None:
        return False
    if can_contribute_to_kennel(user, dog.kennel):
        return True
    return Submission.objects.filter(
        kind=Submission.Kind.DOG,
        status=Submission.Status.APPROVED,
        submitted_by=user,
        dog=dog,
    ).exists()


def admin_public_label(user):
    assignment = moderation_assignment(user)
    if assignment:
        return assignment.public_label
    return "Member" if can_use_member_features(user) else "Staff"


def moderation_role(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if has_member_identity(user):
        return None
    assignment = moderation_assignment(user)
    if assignment is None or assignment.role == ModerationRoleAssignment.Role.NONE:
        return None
    return assignment.role


def can_review_submissions(user):
    return moderation_role(user) in {
        ModerationRoleAssignment.Role.OWNER,
        ModerationRoleAssignment.Role.SENIOR,
        ModerationRoleAssignment.Role.REVIEWER,
    }


def can_review_flagged_submissions(user):
    return moderation_role(user) in {
        ModerationRoleAssignment.Role.OWNER,
        ModerationRoleAssignment.Role.SENIOR,
    }


def can_second_approve(user):
    return can_review_flagged_submissions(user)


def can_manage_verification(user):
    return moderation_role(user) == ModerationRoleAssignment.Role.OWNER
