# collides: announce_widget_onboarded — an allow-listed name redefined as a reached sweep; the listed name is the ghost under test


from datetime import datetime as _canary_datetime

from apps.core.service import service as _canary_service
from apps.core.types import Swept as _CanarySwept


# Planted: an allow-listed name redefined as a sweep the factory reaches — its list entry is a ghost.
@_canary_service
def announce_widget_onboarded(*, before: _canary_datetime, tenant: None) -> _CanarySwept:
    """Drop the frobs older than `before`; absence 1 by construction."""
    return _CanarySwept(label="example.Frob", count=0)


canary_reached_sweep = announce_widget_onboarded
