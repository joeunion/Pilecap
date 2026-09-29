

# Planted: a service ON an archivable row that never asks whether it is live —
# it edits an archived widget in place, a change nobody can see in the book.
@service  # noqa: F821
def frob_widget(*, tenant, actor, widget: Widget):  # noqa: ANN001, ANN201, F821
    """Frob a widget."""
    widget.notes = "frobbed"
    widget.save(update_fields=["notes", "updated_at"])
    return widget
