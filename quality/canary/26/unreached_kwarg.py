

# The ordinary shape rule 26 exists for: an org-scoped row arrives by reference
# and the write lands without anybody asking whether the actor could have
# reached it. `require` runs — and answers a different question.
@service
def _canary_rename_widget(*, tenant: Tenant, actor: Actor, widget: Widget, name: str) -> Widget:
    require(actor, "widget.update", widget)
    widget.name = name
    widget.save(update_fields=["name", "updated_at"])
    return widget
