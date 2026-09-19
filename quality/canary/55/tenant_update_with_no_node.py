

@service
def canary_set_a_tenant_setting(*, tenant: Tenant, actor: Actor, key: str, value: str) -> Tenant:
    """Planted: the LOW edge — a tenant-wide kind asked with no node at all.

    `require(actor, "tenant.update")` reads as the most ordinary line in the
    tree, and it is the same defect as the row-shaped one above wearing fewer
    characters: no node in the question means the hat answers it.
    """
    require(actor, "tenant.update")
    tenant.settings = {**(tenant.settings or {}), key: value}
    tenant.save(update_fields=["settings", "updated_at"])
    return tenant
