

# The right shape: a service, and a route that calls it. This is what the rule
# wants, and a rule that fired here would be a tax on adding a capability.


@service
def suspend_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Pause a widget. Reached from the HTTP door below."""
    widget.notes = "suspended"
    widget.save(update_fields=["notes", "updated_at"])
    return widget
