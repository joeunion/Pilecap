"""The ordinary route, and the reason this clause speaks only about narrowed blocks.

No `@refuses(...)`, so the published enumeration is the door-shape SUPERSET —
generous by construction, and rule 41 says so in its own statement. The service
this route calls raises `NotFound`, and `not_found` is a code that derivation
produces for a route with a path parameter. Firing here would mean the clause
had decided the superset was wrong without being able to compute it, which is a
finding invented out of its own blind spot.

The one thing this clause CAN say about an unnarrowed route is in the canary
beside it: a code the derivation can never produce is a code the document does
not mention anywhere.
"""

from uuid import UUID

from ninja import Router

from apps.core.requests import TenantRequest
from apps.zzz_canary import services

router = Router(tags=["zzz-canary"])


@router.get("/gizmos/{gizmo_id}/", response=dict, url_name="gizmo-detail")
def get_gizmo_route(request: TenantRequest, gizmo_id: UUID) -> dict:
    """Retrieve a gizmo

    One gizmo, by id.

    Refusals you can get here:

    * `404 not_found` — no gizmo with that id is visible to you.
    """
    return services.get_gizmo(tenant=request.tenant, gizmo_id=gizmo_id)
