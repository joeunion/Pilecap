@service
def canary_bare_authz_valve(*, tenant: Tenant, actor: Actor) -> None:
    """A planted violation: the authz valve written with no sentence after it."""
    # authz:
    return None
