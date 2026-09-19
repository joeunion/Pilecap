

@service
def canary_touch_in_order(*, tenant: Tenant, actor: Actor, widget: Widget, label: str):
    """The order canary's pair: the same two lines, the right way round.

    Kept as a negative rather than left to the positive above, because the
    order clause reads STATEMENT POSITIONS and a check that read them wrongly
    would fire here as readily as it fires on the canary — which is the one way
    anybody would find out.
    """
    if not may_be_named(actor, widget):
        raise NotFound()
    require(actor, "widget.update", widget)
    widget.label = label
    widget.save(update_fields=["label"])
    return widget
