

def _negative_certified_widget_body(widget: object) -> dict[str, object]:
    """NEGATIVE (rule 59): the `comms._payload(message)` shape, one hop away."""
    return dict(WidgetOut.from_orm(widget).model_dump(mode="json"))


# NEGATIVE (rule 59): the helper hop, honest. Thirteen emit sites on this tree
# build their body in a module-local helper, so a walk that could not follow one
# would call every one of them a violation — which is the false positive this
# form exists to pin. It is the control for
# `a_body_laundered_through_a_helper.py`: same hop, a certified body instead of
# a bare dict.
@service
def _negative_announce_a_widget_through_a_helper(
    *, tenant: Tenant, actor: Actor, widget: object
) -> None:
    emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=_negative_certified_widget_body(widget),
        actor=actor,
    )
