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


def moderation_assignment(user):
    if not getattr(user, "is_authenticated", False):
        return None

    assignment = getattr(user, "ancestry_moderation_role", None)
    if assignment:
        return assignment

    if getattr(user, "is_superuser", False) or getattr(user, "is_staff", False):
        default_role = (
            ModerationRoleAssignment.Role.OWNER
            if getattr(user, "is_superuser", False)
            else ModerationRoleAssignment.Role.REVIEWER
        )
        assignment, _ = ModerationRoleAssignment.objects.get_or_create(
            user=user,
            defaults={"role": default_role},
        )
        return assignment
    return None


def admin_public_label(user):
    assignment = moderation_assignment(user)
    if assignment:
        return assignment.public_label
    return "Member" if getattr(user, "is_authenticated", False) else "System"


def moderation_role(user):
    if not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "is_superuser", False):
        moderation_assignment(user)
        return ModerationRoleAssignment.Role.OWNER
    assignment = moderation_assignment(user)
    return assignment.role if assignment else None


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
