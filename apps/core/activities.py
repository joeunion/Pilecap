"""The platform's own periodic work. One activity, and it only looks.

`apps/core` had no `activities.py` until the integrations census needed a fourth
surface, and it grows one here rather than borrowing a platform app's for the
reason `core` exists: this is `core`'s own instrument, `core` imports nothing
above it, and a schedule declared in a higher app about a lower app's census
would be the ownership inversion rule 31's own `does_not_cover` warns about.
`apps.core.schedules` already sits here for exactly this shape.

**Plain `def`, not `async def`** — the house form. The worker runs a sync
activity on a thread from its own pool, and what a sync activity owes that
thread is `close_old_connections()` at both ends: there is no request cycle out
here to close what it opened.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from django.db import close_old_connections
from temporalio import activity
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from apps.core.integrations import IntegrationStatus, census
from apps.core.log import get_logger
from apps.core.schedules import ScheduleDeclaration

log = get_logger("apps.core.activities")


@activity.defn(name="probe_integrations", no_thread_cancel_exception=True)
def probe_integrations() -> dict[str, str]:
    """Read the census, say the loud parts out loud, hand back `{key: status}`.

    **Idempotent by construction**: it writes nothing anywhere. A Temporal retry
    re-reads the world, which is the only honest thing a probe can do with a
    retry.

    Three log levels, and the split is the instrument's whole argument:

    * an **unreadable** seam is `error` — the census does not know what that app
      talks to, and a probe that could not look must not be mistaken for a probe
      that looked;
    * a **fake or absent** integration is `warning`, carrying its remedy, so the
      alert a person is woken by already says what to type;
    * the summary is `info`, so a healthy deployment leaves a heartbeat rather
      than a silence — a probe that logs nothing when all is well is a probe
      whose own death is invisible.
    """
    close_old_connections()
    try:
        report = census()
        for seam in report.unreadable:
            log.error("core.integrations.seam_unreadable", module=seam.module, reason=seam.reason)
        for row in report.unmet:
            log.warning(
                "core.integrations.not_configured",
                integration=row.key,
                status=row.status.value,
                probe=row.probe,
                remedy=row.remedy,
            )
        log.info(
            "core.integrations.probed",
            declared=len(report.integrations),
            configured=sum(1 for row in report.integrations if row.is_configured),
            unmet=len(report.unmet),
            unreadable=len(report.unreadable),
        )
        return {row.key: IntegrationStatus(row.status).value for row in report.integrations}
    finally:
        close_old_connections()


# --- the schedule ------------------------------------------------------------

#: `<tenant>:<app>:<noun>:<key>` with `platform` in the tenant position — the
#: deployment's own housekeeping belongs to no tenant — and per task queue, so
#: two deployments sharing a Temporal namespace never fight over one execution.
#: The events purge's precedent, and house rule 18's `platform:` shape.
PROBE_WORKFLOW_PREFIX = "platform:core:integrations"
PROBE_SCHEDULE_PREFIX = "system:core:integrations"

#: How often. Six-hourly: a probe is cheap, and the number that matters is how
#: long a deployment can stand on a fake before somebody is told. A day is a
#: working day of password resets printed to a log; an hour buys nothing over
#: six for a class of failure that arrives on the timescale of an expiring key.
PROBE_EVERY = timedelta(hours=6)


def probe_schedule_id(task_queue: str) -> str:
    """The schedule id for one deployment's prober. One per task queue."""
    return f"{PROBE_SCHEDULE_PREFIX}:{task_queue}"


def probe_workflow_id(task_queue: str) -> str:
    """The deterministic id of the run the schedule starts (house rule 18).

    Per queue and derived, so every worker in a deployment computes the same one
    and Temporal's `SKIP` overlap policy means the second to ask is told it is
    already happening. The server appends the scheduled time; the part this
    repository chooses is the part that must be deterministic.
    """
    return f"{PROBE_WORKFLOW_PREFIX}:{task_queue}"


def probe_schedule(task_queue: str) -> Schedule:
    """The prober's schedule, as a value so a test can read it without a server."""
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "ProbeIntegrationsWorkflow",
            id=probe_workflow_id(task_queue=task_queue),
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=PROBE_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


#: The standing prober — the census's fourth surface, and the only one that
#: catches rot. No legacy id: this schedule has never existed under another name.
PROBE_INTEGRATIONS = ScheduleDeclaration(
    name="core.probe-integrations",
    schedule_id=probe_schedule_id,
    schedule=probe_schedule,
    log_prefix="core",
)


ACTIVITIES: list[Callable[..., Any]] = [probe_integrations]

#: Discovered by `apps.workflows.client.discovered_schedules`, which the worker
#: consults at startup. One declaration, and it is the integrations prober.
SCHEDULES: list[ScheduleDeclaration] = [PROBE_INTEGRATIONS]
