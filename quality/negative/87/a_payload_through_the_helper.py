

# The shape the rule asks for: the route's `Out` through the helper, directly
# and through a module helper whose every return is the helper's.
def _neg_frob_payload(row: object) -> object:
    return event_payload(row)


def neg_payload_through_the_helper(*, tenant: object, row: object) -> None:
    """Emit through the helper, three ways."""
    emit(name="zzz_canary.frob.created", tenant=tenant, payload=event_payload(row))
    emit(name="zzz_canary.frob.updated", tenant=tenant, payload=_neg_frob_payload(row))
    said = event_payload(row)
    emit(name="zzz_canary.frob.archived", tenant=tenant, payload=said)
