

# Planted: the valve with nothing in it. An escape hatch nobody has to justify
# is an off switch, and this engine says so about its own overrides too.


# door:
@service
def archive_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Put a widget beyond reach of the list, with no door and no reason given."""
    widget.notes = "archived"
    widget.save(update_fields=["notes", "updated_at"])
    return widget
