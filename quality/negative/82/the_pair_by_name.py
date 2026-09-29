

# The pair by name: a restore is the one write an archived row takes, so it
# never calls `require_live`.
@service  # noqa: F821
def restore_zzz82_widget(*, tenant, actor, widget: Widget):  # noqa: ANN001, ANN201, F821
    """Put a widget back."""
    return widget
