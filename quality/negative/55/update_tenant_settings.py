

@service
def canary_settings_at_the_root(*, tenant: Tenant, actor: Actor, value: str) -> Tenant:
    """The right form: the node resolved in the call itself.

    `root_organization(tenant=tenant)` is what "the whole tenant" is spelled as
    here, and passing it makes the question the one the caller meant: may this
    person do this AT THE ROOT — which a branch administrator is not at.
    """
    require(actor, "tenant.update", root_organization(tenant=tenant))
    tenant.settings = {**(tenant.settings or {}), "canary": value}
    tenant.save(update_fields=["settings", "updated_at"])
    return tenant
