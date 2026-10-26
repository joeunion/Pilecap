

from datetime import datetime as _canary_datetime

from apps.core.service import service as _canary_service
from apps.core.types import Swept as _CanarySwept


# Planted: the sweep signature exactly, unlisted, no actor, and no `daily_purge` declaration reaches it.
@_canary_service
def canary_purge_unreached_by_the_factory(
    *, before: _canary_datetime, tenant: None
) -> _CanarySwept:
    """Drop the frobs older than `before`, recording nobody."""
    return _CanarySwept(label="example.Frob", count=0)
