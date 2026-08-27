

# Planted: the ordinary miss — a route born with no docstring, so the OpenAPI
# document describes it with a prettified function name and nothing else.


@router.get("/doodad/{doodad_id}/", url_name="doodad-detail")
def canary_doodad_detail(request, doodad_id: str):
    return {"id": doodad_id}
