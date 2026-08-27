

# The recorded valve, with a sentence in it. Some services should not have a
# door — an operator act, a spine primitive services call inside their own
# transaction — and saying so is the answer, not an exemption list somewhere else.


# door: emitted by services inside their own transaction; there is no door that
# emits an event directly, and one would be a door onto somebody else's write.
@service
def publish_widget_signal(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    """A spine primitive. Called from services, never from a door."""
    return widget
