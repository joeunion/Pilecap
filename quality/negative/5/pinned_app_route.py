

@router.get("/canary-negative/", response=list[WidgetOut], url_name="canary-neg-list")
@paginate(CursorPagination)
def canary_negative_list(request: TenantRequest):
    return list_widgets(tenant=request.tenant)
