

def _canary_bare_org_read_route(request):
    rows = Widget.objects.for_tenant(request.tenant).order_by("-created_at")
    return rows.count()
