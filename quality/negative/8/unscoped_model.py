# A model outside both populations reads bare and stays silent: `Tenant` is not
# a TenantScopedModel and its manager names no fail-closed read. (`Membership`
# was this negative's model until its manager's population joined the rule.)
def _neg_unscoped_read():
    return Tenant.objects.filter(pk=None).exists()
