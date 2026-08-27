"""A narrowed route whose work is dispatched, and it must stay silent.

`@refuses(...)` names `page_token_missing`, and no raise site this walk can read
produces it — because the route hands the work to a handler pulled out of a
registry at runtime. That is not an overclaim; it is the clause meeting the
edge of what an AST can know. Firing here would convert "I could not read the
callee" into "the callee cannot raise that", which is a finding manufactured out
of a declared blind spot, and the fastest way to teach somebody to delete a
`@refuses` that was telling the truth.

The route is COUNTED — `routes_with_an_unresolved_callee` on rule 41's status
line — so the size of the silence is printed rather than assumed.
"""

from ninja import Router

from apps.core.api.docs import refuses
from apps.core.requests import TenantRequest
from apps.zzz_canary import services

router = Router(tags=["zzz-canary"])


@router.post("/gizmos/dispatch/", response=dict, url_name="gizmo-dispatch")
@refuses("forbidden", "page_token_missing")
def dispatch_gizmo_route(request: TenantRequest, kind: str) -> dict:
    """Run a gizmo handler

    Hand the work to the handler registered for `kind`.

    Refusals you can get here:

    * `403 forbidden` — the request resolved no tenant.
    """
    handler = getattr(services, f"handle_{kind}", services.run_handler)
    return handler(tenant=request.tenant, kind=kind)
