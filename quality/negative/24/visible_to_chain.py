

def _neg_org_scoped_read(*, tenant, org):
    return Widget.objects.for_tenant(tenant).visible_to(org).filter(name="x").count()
