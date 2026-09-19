

@service
def canary_hand_out(*, tenant: Tenant, actor: Actor, membership: Membership, permission: str):
    """Planted: the write is one hop away from the row that was handed in.

    A `Grant` is neither org-scoped nor FK-to-organization — it names its node
    through the very membership the caller passed. Reading only the direct
    population would stop one hop short of exactly the service this widening
    exists for, and `create_grant` would be outside a rule about handing out
    capabilities.
    """
    require(actor, "grant.create", membership.organization)
    return Grant.objects.create(
        tenant=tenant, membership=membership, permission=permission, effect="allow"
    )
