

@service
def canary_negative_conformant(*, tenant: Tenant, actor: Actor, note: str) -> Widget:
    """The shape the rule exists to leave alone: both declared, neither defaulted."""
    return Widget.objects.create(tenant=tenant, name=note)
