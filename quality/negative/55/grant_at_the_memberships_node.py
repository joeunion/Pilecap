

@service
def canary_grant_at_the_membership(*, tenant: Tenant, actor: Actor, membership, permission: str):
    """The right form for a kind whose node lives one hop away.

    A `Grant` names no organization of its own, and the node it belongs to is
    its membership's. `.organization` is the caller resolving that node and
    saying so — which is exactly what `create_grant` does on this tree.
    """
    require(actor, "grant.create", membership.organization)
    return None
