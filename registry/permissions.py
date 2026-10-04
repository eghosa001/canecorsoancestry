from .models import KennelMembership, ModerationRoleAssignment, Submission


def membership_for(user, kennel):
    if not user.is_authenticated or kennel is None:
        return None
    return KennelMembership.objects.filter(user=user, kennel=kennel).first()


def can_contribute_to_kennel(user, kennel):
    return membership_for(user, kennel) is not None


def can_edit_kennel(user, kennel):
    membership = membership_for(user, kennel)
    return bool(
        membership
        and membership.role
        in {KennelMembership.Role.OWNER, KennelMembership.Role.EDITOR}
    )


def can_contribute_to_dog(user, dog):
    if not user.is_authenticated or dog is None:
        return False
    if can_contribute_to_kennel(user, dog.kennel):
        return True
    return Submission.objects.filter(
        kind=Submission.Kind.DOG,
        status=Submission.Status.APPROVED,
        submitted_by=user,
        dog=dog,
    ).exists()


def moderation_role(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "is_superuser", False):
        return ModerationRoleAssignment.Role.OWNER
    assignment = getattr(user, "ancestry_moderation_role", None)
    if assignment:
        return assignment.role
    if getattr(user, "is_staff", False):
        # Backward compatibility for existing moderators. Owners can explicitly
        # promote/demote them from the verification dashboard.
        return ModerationRoleAssignment.Role.REVIEWER
    return None


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
