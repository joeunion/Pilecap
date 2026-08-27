

# Planted: one capability, two texts. The REST route is documented properly and
# the machine door was given words of its own — which is where two doors begin
# to disagree, prose first and behaviour second.


@router.get("/doohickey/{doohickey_id}/", url_name="doohickey-detail")
def canary_doohickey_detail(request, doohickey_id: str):
    """Retrieve a doohickey

    One doohickey by id, from the part of the tenant this hat covers.
    """
    return {"id": doohickey_id}
