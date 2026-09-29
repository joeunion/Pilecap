

# The two roads to archived rows, used as they are meant to be.
def _negative81_the_widenings(tenant):  # noqa: ANN001, ANN202
    live_and_archived = Widget.objects.for_tenant(tenant).including_archived()  # noqa: F821
    archived = Widget.objects.for_tenant(tenant).archived_only()  # noqa: F821
    return live_and_archived, archived
