

from dataclasses import dataclass as _canary_dataclass
from datetime import datetime as _canary_datetime

from apps.core.service import service as _canary_service


@_canary_dataclass(frozen=True)
class CanaryUnSwept:
    """A result whose name ends like the sweep's and is not `core.types.Swept`."""

    label: str
    count: int


# Planted: reached by a `daily_purge` declaration, the parameters exact, the return a lookalike.
@_canary_service
def canary_reached_sweep(*, before: _canary_datetime, tenant: None) -> CanaryUnSwept:
    """Drop the frobs older than `before`, recording nobody."""
    return CanaryUnSwept(label="example.Frob", count=0)
