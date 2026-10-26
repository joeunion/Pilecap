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

from apps.core.integrations import IntegrationStatus, census
from apps.core.log import get_logger
from apps.core.schedules import ScheduleDeclaration, platform_schedule

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

#: How often. Six-hourly: a probe is cheap, and the number that matters is how
#: long a deployment can stand on a fake before somebody is told. A day is a
#: working day of password resets printed to a log; an hour buys nothing over
#: six for a class of failure that arrives on the timescale of an expiring key.
PROBE_EVERY = timedelta(hours=6)


#: The standing prober — the census's fourth surface, and the only one that
#: catches rot. Declared through the platform factory, so its schedule and its
#: run are both `platform:core:integrations:<queue>` (house rule 18) — the
#: schedule used to be `system:core:integrations:<queue>`, the one id of core's
#: that `check_workflow_id` would have refused. The old schedule id was keyed by
#: the queue, which `legacy_ids` (constants) cannot name; a long-lived deployment
#: still holding it removes it by hand once (CHANGELOG.md, "A long-lived
#: deployment's old integrations-prober schedule").
PROBE_INTEGRATIONS = platform_schedule(
    app="core",
    noun="integrations",
    workflow="ProbeIntegrationsWorkflow",
    every=PROBE_EVERY,
    name="core.probe-integrations",
    log_prefix="core",
)


ACTIVITIES: list[Callable[..., Any]] = [probe_integrations]

#: Discovered by `apps.workflows.client.discovered_schedules`, which the worker
#: consults at startup. One declaration, and it is the integrations prober.
SCHEDULES: list[ScheduleDeclaration] = [PROBE_INTEGRATIONS]
