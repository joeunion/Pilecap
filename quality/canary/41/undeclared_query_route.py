

# Planted: a contract that documents a query parameter the route never declares —
# the replace-all shape that once pasted `?can=` onto routes that take none.


@router.get("/trinkets/{trinket_id}/", url_name="trinket-detail")
def canary_trinket_detail(request, trinket_id: str):
    """Retrieve a trinket

    One trinket by id. Narrow it with `?nope=gold` to read only gold ones.
    """
    return {"id": trinket_id}
