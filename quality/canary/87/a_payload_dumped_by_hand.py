

# Planted: an event whose payload is a hand dump of the row's schema — the
# per-viewer fields ride along, and nothing keeps it equal to the wire.
def canary_hand_dumped_payload(*, tenant: object, row: object, schema: object) -> None:
    """Emit a hand-dumped payload."""
    emit(name="zzz_canary.frob.created", tenant=tenant, payload=schema.model_dump(row))
