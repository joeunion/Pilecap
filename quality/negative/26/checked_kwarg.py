# The right form, and the one the rule is pushing everything towards: the
# REFERENCE is checked, then the verb is authorized, and a row the actor could
# not have reached is not-there rather than not-yours.
#
# REORDERED 2026-09-16, and the reorder is the finding. This fixture stood for
# months with the `require` ABOVE the `may_be_named` while its own comment
# claimed the property that order destroys: with the capability asked first, a
# row inside the tenant and outside the actor's subtree answers `forbidden` —
# which tells the caller it exists — and the `may_be_named` below it never runs.
# The corpus was teaching the inverted order, and six live services wear it
# (`exports` three, `files` three, both ratcheted in this rule's entry). The
# order clause is what found this, on the run it was born.
@service
def _neg_rename_widget(*, tenant: Tenant, actor: Actor, widget: Widget, name: str) -> Widget:
    if not may_be_named(actor, widget):
        raise NotFound()
    require(actor, "widget.update", widget)
    widget.name = name
    widget.save(update_fields=["name", "updated_at"])
    return widget
