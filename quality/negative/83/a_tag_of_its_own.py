# Negative: an operation on a tag key of its own, declared by its own app and
# by no other. A new tag is a new scope family and growth is free — the rule
# refuses only a key two apps carry, never a key one app adds. Appended to the
# probe's api.py after its base, so `router` and `TAGS` are the probe's own;
# the entry is ADDED to `TAGS` rather than rebinding it, so every other form
# planted beside it keeps its description.

TAGS["zzz_canary_things"] = Tag(
    "Gate probe things",
    "A second section of the quality gate's probe app, for the length of one run.",
)


@router.get(
    "/zzz-canary-gadgets/{gadget_id}/",
    url_name="zzz_canary_gadget-detail",
    tags=["zzz_canary_things"],
)
def zzz_canary_gadget_detail(request, gadget_id: str):
    """Retrieve a gadget

    One gadget by id, from the part of the tenant this hat covers.

    A gadget in a sibling branch answers `not_found`, exactly as one in another
    tenant does.
    """
    return {"id": gadget_id}
