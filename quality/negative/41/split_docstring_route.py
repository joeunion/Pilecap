

# A docstring split into its two halves. The workshop half below the `---` is
# for the next person who edits the file and belongs nowhere near the contract —
# and its absence from the document is the whole point of the divider, not a
# missing description.


@router.get("/thingummy/{thingummy_id}/", url_name="thingummy-detail")
def canary_thingummy_detail(request, thingummy_id: str):
    """Retrieve a thingummy

    One thingummy by id.

    The id is a UUID; anything else is refused before a query runs.

    ---
    Declared before the collection route so the reading order matches the
    matching order. Nothing below this line reaches a caller.
    """
    return {"id": thingummy_id}
