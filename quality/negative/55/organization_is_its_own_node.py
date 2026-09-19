

@service
def canary_make_a_child(*, tenant: Tenant, actor: Actor, parent: Organization, name: str):
    """Out of the population by construction: an organization IS a node.

    Asked with the row, this question is already at the node — there is no hat
    fall-back to close. Reading `organization` as a tenant-wide kind would make
    every legal hierarchy write in the product a finding.
    """
    require(actor, "organization.create", parent)
    return None
