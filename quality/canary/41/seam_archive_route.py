"""Planted: an archive route whose narrowed block omits `archive_blocked`.

Its service calls `core.verbs.archive_row`, which raises `ArchiveBlocked` over
any declared blocker — two calls below the route.
"""

from ninja import Router

from apps.core.api.docs import refuses
from apps.core.requests import TenantRequest
from apps.zzz_canary import services

router = Router(tags=["zzz-canary"])


@router.post("/cogs/{cog_id}/archive/", response=dict, url_name="cog-archive")
@refuses("forbidden", "not_found")
def shelve_cog_route(request: TenantRequest, cog_id: str) -> dict:
    """Archive a cog

    Take one cog out of the book.
    """
    return services.shelve_cog(tenant=request.tenant, cog_id=cog_id)
