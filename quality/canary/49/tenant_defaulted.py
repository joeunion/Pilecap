

@service
def canary_defaulted_tenant(*, actor: Actor, tenant: Tenant | None = None, note: str) -> Widget:
    """The tenant half of the sync_workforce lesson.

    `Tenant | None` is a legitimate DECLARATION — the platform population, ADR
    core-8 (b). The `= None` is what makes it a defect: the caller can leave the
    question unanswered, and the row lands in the platform ledger by accident
    rather than by anybody's decision. The negative beside this one plants the
    same annotation with no default and must stay silent.
    """
    return Widget.objects.create(tenant=tenant, name=note)
