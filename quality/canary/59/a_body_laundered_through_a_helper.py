

def _canary_bare_body(widget: object) -> dict[str, str]:
    """CANARY (rule 59): a helper one hop away that returns no narrowing key."""
    return {"id": str(widget), "name": "A widget"}


# CANARY (rule 59): the same omission one hop away. A rule that stopped at the
# call site would fail OPEN on exactly the shape this tree writes most often —
# `comms`' `_payload(message)` is a helper, and thirteen honest emit sites use
# one — so the walk follows a module-local helper's returns, and this is the
# form that proves it does not fail open when it gets there.
@service
def _canary_announce_through_a_helper(*, tenant: Tenant, actor: Actor, widget: object) -> None:
    emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=_canary_bare_body(widget),
        actor=actor,
    )
