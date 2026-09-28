from .models import KennelMembership


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
    return bool(dog and can_contribute_to_kennel(user, dog.kennel))
