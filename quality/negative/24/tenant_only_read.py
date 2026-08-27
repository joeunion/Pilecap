def _neg_tenant_scoped_read(*, tenant):
    # WebhookEndpoint is TenantScopedModel and NOT org-scoped: every member of
    # the tenant may see every endpoint, so `for_tenant` IS the whole read here
    # and demanding `visible_to` would be the false positive this negative
    # exists to catch.
    #
    # It used to name `Invitation`, which INV-1 (be303b4, 2026-08-23, ADR
    # core-20) re-based onto `OrgScopedModel` — an invitation now belongs to the
    # branch it was sent from. The fixture's comment kept asserting the old
    # fact, so this negative fired for 66 commits and the self-test stood at
    # exit 2 the whole time. Found and re-pointed by CORE-11. If the model named
    # here ever gains an `organization`, this fixture moves with it.
    return WebhookEndpoint.objects.for_tenant(tenant).filter(is_active=True).count()
