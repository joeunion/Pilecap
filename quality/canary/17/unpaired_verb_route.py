

@router.post("/thing/{thing_id}/void/", url_name="thing-void")
def canary_thing_void(request, thing_id: str):
    return {"id": thing_id}
