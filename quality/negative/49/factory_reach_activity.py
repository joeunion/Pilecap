

from datetime import datetime as _canary_datetime

from temporalio import activity as _canary_activity

from apps.core.schedules import daily_purge as _canary_daily_purge
from apps.example import services as _canary_services
from apps.example.activities import ACTIVITIES as _CANARY_ACTIVITIES


# Planted: the activity a `daily_purge` declaration's workflow executes, calling the planted sweep.
@_canary_activity.defn(name="canary_reached_sweep_activity")
def canary_reached_sweep_activity() -> None:
    """Run the planted sweep as the system."""
    _canary_services.canary_reached_sweep(before=_canary_datetime.now(), tenant=None)


_CANARY_ACTIVITIES.append(canary_reached_sweep_activity)

SCHEDULES = [
    _canary_daily_purge(
        app="example",
        noun="canary-sweep",
        workflow="canary_reached_sweep_workflow",
        arg=None,
    )
]
