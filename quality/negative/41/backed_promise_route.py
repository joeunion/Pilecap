"""The same promise, kept. Firing here would tax every route that tells the truth.

The sentence is word for word the canary's, and this one is honest: the service
one level down calls `core.authz.require`, so a member really does meet the 403
the document describes. Thirty-nine routes in the tree are this shape, and a
clause that could not tell them from the canary would leave a builder two
choices — delete a true sentence, or carry a finding forever.
"""

from ninja import Router

from apps.core.actor import actor_from_request
from apps.core.requests import TenantRequest
from apps.zzz_canary import services

router = Router(tags=["zzz-canary"])


@router.post("/doohickeys/", response={201: dict}, url_name="doohickey-create")
def create_doohickey_route(request: TenantRequest, payload: dict) -> dict:
    """Create a doohickey

    Register a doohickey for this tenant.

    Refusals you can get here:

    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    return services.create_doohickey(
        tenant=request.tenant, actor=actor_from_request(request), name=str(payload)
    )
