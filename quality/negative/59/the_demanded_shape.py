

# NEGATIVE (rule 59): the shape the rule is pushing to — the row's own
# rule-38-certified `Out`, which carries `organization_id` because rule 38 keeps
# it there. Must stay silent, or the rule would refuse the form it demands.
@service
def _negative_announce_a_widget(*, tenant: Tenant, actor: Actor, widget: object) -> None:
    emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=WidgetOut.from_orm(widget).model_dump(mode="json"),
        actor=actor,
    )
