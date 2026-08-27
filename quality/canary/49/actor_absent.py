

@service
def canary_absent_actor(*, tenant: Tenant, note: str) -> Widget:
    """A write a tenant owns, audited, and recording nobody.

    It declares a `tenant`, so `@service` writes an `AuditEntry` for it — and it
    takes no `actor`, so `write_audit` has nothing to put in `actor_user`,
    `actor_token` or `actor_kind`. The row exists and answers AU-3's identity
    element with silence, which is the defect ADR core-22 was written after
    finding on every row of the live table.
    """
    return Widget.objects.create(tenant=tenant, name=note)
