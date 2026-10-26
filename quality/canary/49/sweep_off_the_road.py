

from datetime import datetime as _canary_datetime

from apps.core.models import Tenant as _CanaryTenant
from apps.core.service import service as _canary_service
from apps.core.types import Swept as _CanarySwept


# Planted: a sweep off the road's signature (a tenant it may filter by), unlisted, no actor.
@_canary_service
def canary_purge_off_the_road(
    *, before: _canary_datetime, tenant: _CanaryTenant | None
) -> _CanarySwept:
    """Drop the frobs older than `before`, recording nobody."""
    return _CanarySwept(label="example.Frob", count=0)
