

# NEGATIVE (rule 36, class status_writer): the demanded shape — a tenant put
# beyond use AND the kick registered on the same body's commit.
@service
def _negative_impound_tenant(*, tenant: Tenant, actor: Actor) -> Tenant:
    tenant.status = Tenant.Status.SUSPENDED
    tenant.save(update_fields=["status", "updated_at"])
    close_tenant_sockets_on_commit(tenant_id=tenant.pk, reason=KICK_TENANT_SUSPENDED)
    return tenant


# NEGATIVE (rule 36, class status_writer): a WIDENING kicks nobody. Nothing a
# socket is delivering has been taken away by a tenant coming back, and hanging
# somebody up to give them more is a reconnect storm with no security content —
# the asymmetry `kick_if_reads_narrowed` states one level down.
@service
def _negative_reinstate_tenant(*, tenant: Tenant, actor: Actor) -> Tenant:
    tenant.status = Tenant.Status.ACTIVE
    tenant.save(update_fields=["status", "updated_at"])
    return tenant
