"""Planted: a narrowed block that publishes a refusal nothing can raise.

`@refuses(...)` REPLACES the door-shape derivation, so what it names is what a
client is told to handle — the whole list, exactly. `page_token_missing` is a
registered code, so rule 41's older clause is satisfied and silent; nothing this
route reaches raises it. A client that branched on it wrote a branch that will
never run, and a reader of the document learned something untrue about when this
operation refuses.

This is the shape a narrowed block takes as it ages: the raise moves, the
service is rewritten, the decorator stays.
"""

from ninja import Router

from apps.core.api.docs import refuses
from apps.core.requests import TenantRequest
from apps.zzz_canary import services

router = Router(tags=["zzz-canary"])


@router.get("/doodads/", response=dict, url_name="doodad-list")
@refuses("forbidden", "page_token_missing")
def list_doodads_route(request: TenantRequest) -> dict:
    """List doodads

    Every doodad your acting organization can see.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no tenant.
    """
    return services.list_doodads(tenant=request.tenant)
