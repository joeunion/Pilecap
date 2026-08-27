

@router.get("/gizmo/{gizmo_id}/", url_name="gizmo-detail")
def canary_gizmo_detail(request, gizmo_id: str):
    """Retrieve a gizmo

    One gizmo by id, from the caller's tenant.

    A gizmo in another tenant answers `not_found`, never `forbidden`.
    """
    return {"id": gizmo_id}
