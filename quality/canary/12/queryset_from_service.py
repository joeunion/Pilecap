

def _canary_list_for_display(*, tenant):
    return Widget.objects.for_tenant(tenant).filter(name="planted")
