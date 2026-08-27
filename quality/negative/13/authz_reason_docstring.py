

@service
def neg_guarded_by_reason(*, tenant: Tenant, actor: Actor) -> None:
    """A no-op proving the marker form.

    # authz: the system acting for itself; there is no object to guard.
    """
    return None
