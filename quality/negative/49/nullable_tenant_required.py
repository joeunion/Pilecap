

@service
def canary_negative_nullable_tenant(*, tenant: Tenant | None, actor: Actor, note: str) -> Widget:
    """**Required-but-NULLABLE is conformant, and this is the negative that says so.**

    `accounts.revoke_token`'s own shape. `None` is a real declared population —
    the deployment's own actions, ADR core-8 (b) — and a service pinned to no
    workspace is a product state rather than an absence. What the rule refuses
    is a DEFAULT, because a default is the one shape where a caller can leave
    the question unanswered and nothing records that they did. If this ever
    fires, the rule has started reading nullability instead of defaultedness and
    would force every platform-population service to lie about its own shape.
    """
    return Widget.objects.create(tenant=tenant, name=note)
