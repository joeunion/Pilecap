"""The two seam-reaching routes, with what they reach DECLARED.

`@also_refuses(...)` adds the family's codes to the narrowed set rather than
re-typing it — the composing form the worked example uses. Firing here would
mean the only honest declaration of a seam refusal is a valve.
"""

from ninja import Router

from apps.core.api.docs import also_refuses, refuses
from apps.core.requests import TenantRequest
from apps.zzz_canary import services

router = Router(tags=["zzz-canary"])


@router.post("/sprockets/{sprocket_id}/polish/", response=dict, url_name="sprocket-polish")
@refuses("forbidden", "not_found")
@also_refuses("archived")
def polish_sprocket_route(request: TenantRequest, sprocket_id: str) -> dict:
    """Polish a sprocket

    Polish one sprocket in place.
    """
    return services.polish_sprocket(tenant=request.tenant, sprocket_id=sprocket_id)


@router.post("/cogs/{cog_id}/archive/", response=dict, url_name="cog-archive")
@also_refuses("archive_blocked")
def shelve_cog_route(request: TenantRequest, cog_id: str) -> dict:
    """Archive a cog

    Take one cog out of the book.
    """
    return services.shelve_cog(tenant=request.tenant, cog_id=cog_id)
