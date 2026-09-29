

# Planted: the archived cut asked for by hand after `for_tenant()` — which has
# already left every archived row out, so this answers nothing and says nothing.
def _canary81_hand_archived_cut(tenant):  # noqa: ANN001, ANN202
    return Widget.objects.for_tenant(tenant).filter(archived_at__isnull=False)  # noqa: F821
