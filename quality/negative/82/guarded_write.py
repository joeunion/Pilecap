

# A service on the row that asks first.
@service  # noqa: F821
def polish82_widget(*, tenant, actor, widget: Widget):  # noqa: ANN001, ANN201, F821
    """Polish a live widget."""
    require_live(widget, noun="widget")  # noqa: F821
    return widget
