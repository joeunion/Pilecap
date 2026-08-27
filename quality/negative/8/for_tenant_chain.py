

def _neg_scoped_read(*, tenant):
    return Widget.objects.for_tenant(tenant).filter(name="x").count()
