

@service
def _neg_platform_touch_widget(
    *,
    tenant: Tenant,
    actor: Actor,
    # reach: the retention sweep runs for the product itself, holds no hat, and
    # is handed rows by a selector that already scoped them tenant-wide
    widget: Widget,
) -> Widget:
    widget.save(update_fields=["updated_at"])
    return widget
