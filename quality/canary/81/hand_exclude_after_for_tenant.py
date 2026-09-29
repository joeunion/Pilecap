

# Planted: the same trap spelled as an exclusion.
def _canary81_hand_exclusion(tenant):  # noqa: ANN001, ANN202
    return Widget.objects.for_tenant(tenant).exclude(archived_at=None)  # noqa: F821
