

@service
def canary_touch_out_of_order(*, tenant: Tenant, actor: Actor, widget: Widget, label: str):
    """Planted: both halves present, in the wrong order.

    This is the shape that is hardest to see, because everything the rule used
    to ask for is here: the row is cleared, the capability is asked, the write
    happens. What is wrong is the SEQUENCE — a capability answered about a row
    the actor could never have named answers `forbidden` where the honest
    answer is `not_found`, and the difference tells a caller that a row outside
    their branch exists.
    """
    require(actor, "widget.update", widget)
    if not may_be_named(actor, widget):
        raise NotFound()
    widget.label = label
    widget.save(update_fields=["label"])
    return widget
