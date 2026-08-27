

# The other half of the negative: the door. `suspend_widget` is reached by name
# from a module the mounts discover, which is the whole of what the rule asks.


@router.post("/{widget_id}/suspend/", response=WidgetOut, url_name="widget-suspend")
def suspend_widget_route(request: TenantRequest, widget_id: UUID) -> Widget:
    """Pause a widget."""
    actor, tenant = _acting(request)
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org)
    return suspend_widget(tenant=tenant, actor=actor, widget=widget)
