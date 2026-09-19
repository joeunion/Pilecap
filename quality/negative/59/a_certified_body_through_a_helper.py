

def _negative_certified_body(entry: object) -> dict[str, object]:
    """NEGATIVE (rule 59): the `comms._payload(message)` shape, one hop away."""
    return dict(UsageEntryOut.from_orm(entry).model_dump(mode="json"))


# NEGATIVE (rule 59): the helper hop, honest. Thirteen emit sites on this tree
# build their body in a module-local helper, so a walk that could not follow one
# would call every one of them a violation — which is the false positive this
# form exists to pin.
@service
def _negative_announce_through_a_helper(*, tenant: Tenant, actor: Actor, entry: object) -> None:
    emit(
        name=THRESHOLD_CROSSED,
        tenant=tenant,
        payload=_negative_certified_body(entry),
        actor=actor,
    )
