

@service
def canary_touch_a_membership(*, tenant: Tenant, actor: Actor, membership):
    """Out of the population: `Membership` names its organization by column.

    The derivation is the tree's, not a list here — a model that carries an
    `organization` foreign key has a node, so `allows` resolves at the row and
    never falls back. The day somebody drops that column this negative starts
    firing, which is the point of keeping it.
    """
    require(actor, "membership.update", membership.organization)
    return None
