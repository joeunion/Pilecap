

@service
def _canary_touch_widget(
    *,
    tenant: Tenant,
    actor: Actor,
    # reach:
    widget: Widget,
) -> Widget:
    require(actor, "widget.update", widget)
    widget.save(update_fields=["updated_at"])
    return widget
