

from datetime import datetime as _canary_datetime

from apps.core.service import service as _canary_service
from apps.core.types import Swept as _CanarySwept


# Legal: a sweep on the factory's signature that a `daily_purge` declaration reaches takes no actor.
@_canary_service
def canary_reached_sweep(*, before: _canary_datetime, tenant: None) -> _CanarySwept:
    """Drop the frobs older than `before`; absence 1 by construction."""
    return _CanarySwept(label="example.Frob", count=0)
