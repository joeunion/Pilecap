

# Planted: the same trap on a second archivable class — a service named for the
# policy row it retitles, and never asking whether it is live.
@service  # noqa: F821
def retitle_widget_policy(*, tenant, actor, widget_policy: WidgetPolicy):  # noqa: ANN001, ANN201, F821
    """Retitle a widget policy."""
    widget_policy.name = "retitled"
    widget_policy.save(update_fields=["name", "updated_at"])
    return widget_policy
