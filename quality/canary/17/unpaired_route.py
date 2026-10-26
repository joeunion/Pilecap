@router.get("/zzz-canary-thing/{thing_id}/", url_name="zzz_canary_thing-detail")
def zzz_canary_thing_detail(request, thing_id: str):
    return {"id": thing_id}
