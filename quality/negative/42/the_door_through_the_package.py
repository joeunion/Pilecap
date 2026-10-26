"""The door half: it calls the service through the package that re-exports it."""

from ninja import Router

from apps.accounts.auth import API_AUTH
from apps.core.actor import actor_from_request
from apps.core.requests import TenantRequest
from apps.zzz_canary import services

router = Router(tags=["zzz-canary"], auth=API_AUTH)


@router.post("/enrol/", response={200: str}, url_name="zzz-canary-enrol")
def enrol(request: TenantRequest, email: str) -> str:
    return services.enrol_probe_person(
        tenant=request.tenant, actor=actor_from_request(request), email=email
    )
