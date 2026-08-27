

# Planted: the owner's screenshot, as a fixture. The docstring's first line is a
# SENTENCE with Markdown in it, so the navigation sidebar shows `**every
# version**` as those characters, in a column that is meant to be scannable
# names. Three faults in one line — Markdown, a full stop, and length past the
# cap — because that is exactly what a summary-shaped first line looks like.


@router.get("/knickknack/{knickknack_id}/", url_name="knickknack-detail")
def canary_knickknack_detail(request, knickknack_id: str):
    """Fetch one knickknack by id — **every version, including retired ones.**

    The body is fine. The first line is the problem: it is prose where a name
    belongs.
    """
    return {"id": knickknack_id}
