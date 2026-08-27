

def _neg_materialised(*, tenant):
    return list(Widget.objects.for_tenant(tenant))
