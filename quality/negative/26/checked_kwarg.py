

# The right form, and the one the rule is pushing everything towards: the verb
# is authorized, the REFERENCE is checked, and a row the actor could not have
# reached is not-there rather than not-yours.
@service
def _neg_rename_widget(*, tenant: Tenant, actor: Actor, widget: Widget, name: str) -> Widget:
    require(actor, "widget.update", widget)
    if not may_be_named(actor, widget):
        raise NotFound()
    widget.name = name
    widget.save(update_fields=["name", "updated_at"])
    return widget
