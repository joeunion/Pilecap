

@service
def canary_promote_checked(*, tenant: Tenant, actor: Actor, membership: Membership, role: str):
    """The right form: reach asked first, then the capability, then the write.

    `set_role`'s shape on this tree, and the order is the whole of it: a row
    the actor cannot name is `not_found` before any capability is consulted,
    so the refusal says nothing about whether the row exists.
    """
    if not may_be_named(actor, membership):
        raise NotFound()
    require(actor, "membership.update", membership.organization)
    membership.role = role
    membership.save(update_fields=["role"])
    return membership
