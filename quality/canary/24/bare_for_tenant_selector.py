

def _canary_bare_org_read(*, tenant):
    return Widget.objects.for_tenant(tenant).filter(name="planted")
