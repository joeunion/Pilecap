

# The parameter says exactly what it is — a row one part of a tenant
# owns, any of them — and until 2026-08-29 that made it INVISIBLE here: rule
# 26's population came from a transitive walk that discards its own seed, so
# every concrete model was in it and `OrgScopedModel` itself was not. The most
# honest annotation a service can write was the one annotation nobody asked the
# reachability question about. The population now carries the base.
@service
def _canary_touch_any_org_row(
    *, tenant: Tenant, actor: Actor, row: OrgScopedModel, label: str
) -> OrgScopedModel:
    require(actor, "widget.update")
    row.name = label
    row.save(update_fields=["name", "updated_at"])
    return row
