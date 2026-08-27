

# The right shape since 2026-08-24: a docstring whose FIRST LINE is a nav-safe
# title — a short phrase, no Markdown, no full stop — and whose body opens with
# the sentence, on a tag the app both described and named. A rule that fired here
# would be a tax on writing a route.


@router.get("/doodad/{doodad_id}/", url_name="doodad-detail")
def canary_doodad_detail(request, doodad_id: str):
    """Retrieve a doodad

    One doodad by id, from the part of the tenant this hat covers.

    A doodad in a sibling branch answers `not_found`, exactly as one in another
    tenant does.
    """
    return {"id": doodad_id}
