"""The door half of: an activity that calls the OTHER `deactivate_user`.

This module reaches a vendor client, not the service beside it. Before the
qualified-name census (P5 QB-R1) the bare name was enough and the service one
directory away read as reachable.
"""

from collections.abc import Callable
from typing import Any

from temporalio import activity

from apps.zzz_canary import vendor


@activity.defn(name="probe_deactivate")
def probe_deactivate(email: str) -> None:
    vendor.deactivate_user(email)


ACTIVITIES: list[Callable[..., Any]] = [probe_deactivate]
