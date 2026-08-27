

from apps.core.schemas import PingOut


@router.get("/flat/", response=list[PingOut], url_name="canary-flat-list")
def canary_flat_list(request):
    return []
