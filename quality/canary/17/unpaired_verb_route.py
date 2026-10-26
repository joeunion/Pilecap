@router.post("/zzz-canary-thing/{thing_id}/void/", url_name="zzz_canary_thing-void")
def zzz_canary_thing_void(request, thing_id: str):
    return {"id": thing_id}
