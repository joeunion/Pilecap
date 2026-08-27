"""Planted: a narrowed block missing a code its direct callee raises.

The route says it can refuse with `forbidden` and nothing else. The service it
calls — one level down, by name, resolvable — raises `Conflict`. A client that
read the document has no branch for a 409 and will meet one, and the failure is
not in the code: it is in the sentence somebody wrote about the code, which no
test asserts and no reviewer re-reads when the service changes.

Two files, because an underclaim is a RELATION between a decorator and a raise
site and a one-file fixture could not express it.
"""

from ninja import Router

from apps.core.api.docs import refuses
from apps.core.requests import TenantRequest
from apps.zzz_canary import services

router = Router(tags=["zzz-canary"])


@router.post("/doodads/", response={201: dict}, url_name="doodad-create")
@refuses("forbidden")
def create_doodad_route(request: TenantRequest, payload: dict) -> dict:
    """Create a doodad

    Register a doodad for your acting organization.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no tenant.
    """
    return services.create_doodad(tenant=request.tenant, name=str(payload))
