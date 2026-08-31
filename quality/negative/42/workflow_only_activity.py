"""The reaching half: an activity, and nothing else, calling the service.

An activity is a workflow's step. It is a door in the sense that the mounts
discover it and a service reached from it is not dead code — and it is not a
door in the sense that decides this rule's question, because no credential a
person holds opens it.
"""

from collections.abc import Callable
from typing import Any

from temporalio import activity

from apps.zzz_canary import services


@activity.defn(name="probe_sweep")
def probe_sweep() -> int:
    return services.sweep_probe_rows(tenant=None, actor=None)


ACTIVITIES: list[Callable[..., Any]] = [probe_sweep]
