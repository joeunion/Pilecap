# The reference is "checked" through an ATTRIBUTE of itself: the call asks
# about `widget.parent`, and until this canary the check counted every Name
# anywhere in the arguments — so `widget`, the parameter that actually names the
# row being written, came out marked checked without anybody having asked about
# it. A different row cleared, and the rule read it as compliance.
@service
def _canary_relabel_widget(*, tenant: Tenant, actor: Actor, widget: Widget, label: str) -> Widget:
    require(actor, "widget.update", widget)
    if not may_be_named(actor, widget.parent):
        raise NotFound()
    widget.name = label
    widget.save(update_fields=["name", "updated_at"])
    return widget
