

# `approve_widget`'s real shape, found on the tree at measurement time: it takes
# an org-scoped row and writes nothing — the approval IS the signal, and the row
# changes out in the workflow's own activity. The rule asks only about services
# that write, so this is not in the population and must stay out of it.
@service
def _neg_approve_widget(*, tenant: Tenant, actor: Actor, widget: Widget) -> Widget:
    require(actor, "widget.approve", widget)
    signal_workflow(
        tenant=tenant,
        actor=actor,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key=str(widget.pk)),
        signal=WIDGET_APPROVAL_SIGNAL,
    )
    return widget
