

@service
def canary_touch_the_tenant(*, tenant: Tenant, actor: Actor) -> Tenant:
    """Planted: the valve with nothing in it.

    An escape hatch nobody has to justify is an off switch, and the gate says
    the same about its own overrides. Rule 26's device, reused.
    """
    # hat-scoped:
    require(actor, "tenant.update")
    return tenant
