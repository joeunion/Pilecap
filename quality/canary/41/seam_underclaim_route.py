"""Planted: a narrowed block missing a code the family seam raises, two calls down.

The route promises `forbidden` and `not_found`. The service it calls writes a
row after `core.verbs.require_live`, which raises `Archived` — `archived`, 409 —
on an archived row. Before the reach followed `core.verbs` this was invisible
(a raise two hops away), which is how the worked example answered `archived` on
four routes the document never named it on.
"""

from ninja import Router

from apps.core.api.docs import refuses
from apps.core.requests import TenantRequest
from apps.zzz_canary import services

router = Router(tags=["zzz-canary"])


@router.post("/sprockets/{sprocket_id}/polish/", response=dict, url_name="sprocket-polish")
@refuses("forbidden", "not_found")
def polish_sprocket_route(request: TenantRequest, sprocket_id: str) -> dict:
    """Polish a sprocket

    Polish one sprocket in place.
    """
    return services.polish_sprocket(tenant=request.tenant, sprocket_id=sprocket_id)
