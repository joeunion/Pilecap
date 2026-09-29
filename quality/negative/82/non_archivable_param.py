

# A service on a row of a class that never declared `Archivable`.
@service  # noqa: F821
def tally82_widget_entry(*, tenant, actor, widget_entry: WidgetEntry):  # noqa: ANN001, ANN201, F821
    """Tally one ledger line."""
    return widget_entry
