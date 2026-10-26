

def neg_engine_event_payload(*, tenant: object) -> None:
    """An event about the platform itself, with no `Out` to carry."""
    # payload: the search engine's own state change has no route and no Out schema
    emit(name="zzz_canary.engine.switched", tenant=tenant, payload={"v": 1})
