

@service
def canary_promote(*, tenant: Tenant, actor: Actor, membership: Membership, role: str):
    """Planted: `set_role`'s exact shape, before the population widened.

    A `Membership` carries an `organization` column and inherits `BaseModel`
    rather than the scoped base, so it sat OUTSIDE rule 26's population and a
    service handed one from anywhere — `Membership.objects.get(pk=...)` in a
    door, a row from another branch — could write a role on the strength of it
    with the gate green. The capability was asked at the row's own node, which
    is the right node and the wrong question: the actor may never have been
    able to name that row at all.
    """
    require(actor, "membership.update", membership.organization)
    membership.role = role
    membership.save(update_fields=["role"])
    return membership
