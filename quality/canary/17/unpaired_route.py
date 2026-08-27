

@router.get("/thing/{thing_id}/", url_name="thing-detail")
def canary_thing_detail(request, thing_id: str):
    return {"id": thing_id}
