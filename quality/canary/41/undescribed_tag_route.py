

# Planted: a documented route carrying a tag nobody described. The prose is
# there and the group it lands in is a blank heading — which is what a reader
# meets before they meet a single route.


@router.get("/gimcrack/{gimcrack_id}/", url_name="gimcrack-detail", tags=["zzz-undescribed"])
def canary_gimcrack_detail(request, gimcrack_id: str):
    """Retrieve a gimcrack

    One gimcrack by id, from the caller's tenant.
    """
    return {"id": gimcrack_id}
