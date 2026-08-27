"""Planted: the promise of a permission wall, with nothing behind it.

its finding, replanted. The sentence is the one that was pasted onto five
reads in `apps/events` and sat in three more api modules: a caller is told that
`403` here means they are not an owner or an administrator of the tenant. This
route checks no role. It takes no actor, calls no service, and answers 200 for
any member of the tenant.

EVERY OTHER MECHANISM IS SATISFIED AND SILENT. `forbidden` is registered, so
rule 41's older clause passes. It is genuinely reachable — the door refuses a
request that resolves no tenant with exactly that code — so its overclaim
direction is correct to say nothing. The document renders, the tests pass, and
the only thing that is wrong is the sentence, which is the half nothing was
reading.
"""

from ninja import Router

from apps.core.requests import TenantRequest
from apps.zzz_canary import services

router = Router(tags=["zzz-canary"])


@router.get("/doohickeys/", response=dict, url_name="doohickey-list")
def list_doohickeys_route(request: TenantRequest) -> dict:
    """List doohickeys

    Every doohickey this tenant owns.

    Refusals you can get here:

    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    return services.list_doohickeys(tenant=request.tenant)
