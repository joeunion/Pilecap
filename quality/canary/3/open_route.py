"""Planted: a route that declares no auth."""

from ninja import Router

router = Router(tags=["zzz-canary"])


@router.get("/open/", auth=None, url_name="canary-open")
def canary_open(request):
    return {"ok": True}
