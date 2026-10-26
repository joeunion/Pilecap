

# Planted: a membership read through the bare manager — every tenant's rows.
def canary_bare_membership_read(*, user: object) -> object:
    """Every membership of everyone, filtered by hand."""
    from apps.core.models import Membership

    return Membership.objects.filter(user=user)
