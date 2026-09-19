

def canary_may_edit_the_role(actor, role):
    """Planted: `allows`, not `require` — the same fall-back, read rather than raised.

    A capability QUESTION resolves at the same node the refusal would, so a
    door that branches on `allows` and never calls `require` has the identical
    hole. The rule reads both names for that reason.
    """
    return allows(actor, "role.update", role)
