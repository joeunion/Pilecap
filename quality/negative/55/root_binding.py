

@service
def canary_rename_at_a_bound_root(*, tenant: Tenant, actor: Actor, name: str) -> None:
    """The right form, one line apart: the root resolved, then asked at.

    Most real call sites need the root twice — once for the question and once
    for the write — so the binding is the ordinary spelling and reading only
    the inline call would have made the rule refuse the shape it is asking for.
    """
    root = root_organization(tenant=tenant)
    require(actor, "sso_connection.update", root)
    return None
