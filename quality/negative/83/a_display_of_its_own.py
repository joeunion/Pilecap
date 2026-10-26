# Negative: a new key titled in words of its own. A display title another
# app's key does not carry is a new heading, and growth is free — the title
# clause refuses only a heading two apps' keys share. Appended to the probe's
# api.py after its base; the entry is ADDED to `TAGS` so every other form
# planted beside it keeps its description.

TAGS["zzz_canary_field_notes"] = Tag(
    "Field notes",
    "A section of the quality gate's probe app titled in its own words, for one run.",
)


@router.get(
    "/zzz-canary-field-notes/{note_id}/",
    url_name="zzz_canary_field_note-detail",
    tags=["zzz_canary_field_notes"],
)
def zzz_canary_field_note_detail(request, note_id: str):
    """Retrieve a field note

    One field note by id, from the part of the tenant this hat covers.

    A field note in a sibling branch answers `not_found`, exactly as one in
    another tenant does.
    """
    return {"id": note_id}
