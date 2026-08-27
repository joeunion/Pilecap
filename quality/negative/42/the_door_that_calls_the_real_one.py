"""The door half of the negative: it calls the vendor AND the real service.

`services.deactivate_user` resolves to `apps.zzz_canary.services`, which is
where the `@service` lives, so the census credits it. `vendor.deactivate_user`
resolves elsewhere and credits nothing — which is exactly what it should do.
"""

from collections.abc import Callable
from typing import Any

from temporalio import activity

from apps.core.actor import system_actor
from apps.workflows.context import workflow_context
from apps.zzz_canary import services, vendor


@activity.defn(name="probe_deactivate")
def probe_deactivate(email: str) -> None:
    tenant, _user_id, org = workflow_context()
    vendor.deactivate_user(email)
    services.deactivate_user(tenant=tenant, actor=system_actor(tenant, org), email=email)


ACTIVITIES: list[Callable[..., Any]] = [probe_deactivate]
