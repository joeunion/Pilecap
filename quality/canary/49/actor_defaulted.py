

@service
def canary_defaulted_actor(*, tenant: Tenant, actor: Actor | None = None, note: str) -> Widget:
    """The worse half: a signature that CLAIMS to record a person.

    A reviewer reading this signature sees an audited, attributed service. Every
    caller that leaves `actor` out files its row under nobody, and nothing
    anywhere records which callers did — which is exactly how
    `accounts.sync_workforce_identity_config` went unaudited under ADR core-8
    with a signature that looked correct.
    """
    return Widget.objects.create(tenant=tenant, name=note)
