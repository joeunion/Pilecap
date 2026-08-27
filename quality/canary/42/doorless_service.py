

# Planted: the ordinary miss — a mechanism built and never given a door. It has
# a test, an audit row and a docstring, and nobody outside this tree can call it.


@service
def retire_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Take a widget out of service without deleting its ledger."""
    widget.notes = "retired"
    widget.save(update_fields=["notes", "updated_at"])
    return widget
