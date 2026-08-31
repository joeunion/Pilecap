"""The door half of the negative: it calls the vendor AND the real service.

`services.deactivate_user` resolves to `apps.zzz_canary.services`, which is
where the `@service` lives, so the census credits it. `vendor.deactivate_user`
resolves elsewhere and credits nothing — which is exactly what it should do.

A ROUTE rather than an activity, since 2026-08-29. The subject here is
NAME RESOLUTION, and the module kind is incidental to it — but it stopped being
incidental to the rule: a service reached only from an activity now lands in the
`:internal-only` class, and this negative would have fired for a reason that has
nothing to do with what it exists to prove. The canary twin keeps the
activity, because THAT one is replaying a live incident that happened in one.
"""

from ninja import Router

from apps.accounts.auth import API_AUTH
from apps.core.actor import actor_from_request
from apps.core.requests import TenantRequest
from apps.zzz_canary import services, vendor

router = Router(tags=["zzz-canary"], auth=API_AUTH)


@router.post("/deactivate/", response={200: str}, url_name="zzz-canary-deactivate")
def deactivate(request: TenantRequest, email: str) -> str:
    vendor.deactivate_user(email)
    return services.deactivate_user(
        tenant=request.tenant, actor=actor_from_request(request), email=email
    )
