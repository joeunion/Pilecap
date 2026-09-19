

# CANARY (rule 36, class status_writer): R4's F2, as the third operator service.
# A tenant put beyond use, with nothing registered to hang up on the sockets
# already open. The next HANDSHAKE is refused and every live connection goes on
# hearing — which is precisely what made the gap invisible for a cycle.
@service
def _canary_impound_tenant(*, tenant: Tenant, actor: Actor) -> Tenant:  # planted violation
    tenant.status = Tenant.Status.SUSPENDED
    tenant.save(update_fields=["status", "updated_at"])
    return tenant
