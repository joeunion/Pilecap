

@service
def neg_guarded_by_reason(*, tenant: Tenant, actor: Actor) -> None:
    """A no-op proving the marker form: the reason is a comment line in the body."""
    # authz: the system acting for itself; there is no object to guard.
    return None
