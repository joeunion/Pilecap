"""Planted: a door writing a permission exception with its own hands.

`Membership.role` stopped being the only way to change what somebody may do the
day the role tables landed, and this is the other way: a `Grant` row widens one
person in one branch, bounded by nothing at all when it is written here.
`create_grant` is the service, and what it carries that this does not is the
escalation wall — `allow` bounded by what the granter holds, `withhold` bounded
by what the target holds.
"""

from apps.core.models import Grant


@router.post("/canary-grants/")
def canary_hand_out_a_grant(request, membership_id, permission):
    """Planted wrongness: the row, straight from a door."""
    return Grant.objects.create(
        tenant=request.tenant,
        membership_id=membership_id,
        permission=permission,
        effect=Grant.Effect.ALLOW,
    )
