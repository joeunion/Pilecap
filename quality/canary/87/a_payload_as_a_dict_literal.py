

# Planted: an event whose payload is a dict literal typed at the emit.
def canary_dict_literal_payload(*, tenant: object, row: object) -> None:
    """Emit a payload typed by hand."""
    emit(name="zzz_canary.frob.created", tenant=tenant, payload={"id": str(row)})
