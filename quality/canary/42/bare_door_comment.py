

# Planted: the valve with nothing in it. An escape hatch nobody has to justify
# is an off switch, and this engine says so about its own overrides too.
#
# The name is one no app serves, on purpose. Rule 42 keys a service by its
# (module, name), and this plant is appended into a real services.py: named
# after a service that module already has, it inherits that service's doors,
# reads as reached, and the empty valve is never judged. It was once named
# after a service the example did not yet have, and died the day it did.


# door:
@service
def shelve_widget_behind_a_bare_valve(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """Put a widget beyond reach of the list, with no door and no reason given."""
    widget.notes = "archived"
    widget.save(update_fields=["notes", "updated_at"])
    return widget
