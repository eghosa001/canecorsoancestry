from .models import KennelMembership, Submission


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
