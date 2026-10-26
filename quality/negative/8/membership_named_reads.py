

# The two reads the fail-closed manager names, and their composition.
def neg_membership_named_reads(*, tenant: object, user: object) -> object:
    """One person's rows in one tenant, through the named reads."""
    from apps.core.models import Membership

    Membership.objects.of(user)
    return Membership.objects.for_tenant(tenant).of(user)
