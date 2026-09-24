"""Where this app's housekeeping touches the database, and the machine that runs it.

One activity and one declared schedule. Everything non-deterministic is here
rather than in `workflows.py` (house rule 9), and the activity calls a service
rather than a model (house rule 10).

**Plain `def`, like every other activity in this repository**: the ORM is
synchronous and the worker runs activities in a thread pool, so a sync activity
is a sync query on a thread where one belongs rather than an `async def` that
wraps one to hand it back to a thread anyway. It closes stale connections at
both ends, because out here there is no request cycle to do it.

**Why this module exists at all.** `InboundWebhook` declares itself `purged`
(ADR core-13), and a `purged` declaration is a promise: something deletes these
rows on a schedule. House rule 31 walks the promise outwards —

    purged_by -> an activity that references it
              -> a workflow that executes that activity
              -> a `ScheduleDeclaration` in this module's `SCHEDULES`

— because a table shaped for a sweeper with no sweeper looks exactly like a
table that is finished. This is the class rule 30's `next_attempt_at`
describes, and it is the class this file's existence closes for this app.

**It only DECLARES.** Whether the declaration becomes a durable Temporal
Schedule the server owns, or a run a live worker starts on a timer, is decided
once by the deployment's lifetime class in `apps.workflows.client` (ADR
platform-lifecycle-1) — so this app never has to know which one it is running
under, and `apps.connections` never imports `apps.workflows` (the layer
contract holds the platform apps independent of one another).
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

from apps.connections import services
from apps.connections.types import PURGE_WORKFLOW, PurgeInboundWebhooks, PurgeOutcome
from apps.core.log import get_logger
from apps.core.schedules import ScheduleDeclaration
from apps.core.time import now

log = get_logger(__name__)

# **Ninety days after the hand-off closed.** A stored delivery
# is useful for the hand-off's retries, and then for the support window in which
# a human asks what the provider actually sent — the body plus the signing
# headers are what make "we refused it and here is why" answerable. Past that it
# is somebody else's customer data with no reader, which is a liability rather
# than an asset.
#
# A module constant rather than a setting, and that is the one honest
# gap here: `EVENTS_OUTBOX_RETENTION_DAYS` is a setting precisely because retention
# is a data-policy decision a customer contract can move, and this number is the
# same kind of decision. It is a constant here because `config/settings/` is out
# of this app's territory; the trigger for promoting it is a deployment
# that needs a different window from the template's.
INBOUND_WEBHOOK_RETENTION_DAYS = 90

# Daily, like the spine's purge beside it. The window is ninety days wide, so
# the cadence only has to be small against it; running more often would delete
# the same nothing more often.
PURGE_EVERY = timedelta(hours=24)

# **Both ids are namespaced by task queue**, and that is not cosmetic (ADR
# events-2): a schedule id is global to the Temporal
# namespace, so a constant one makes every worker's startup a silent fight over
# where the sweep runs — on a laptop running five worktrees against one dev
# server, the last worker to start hijacks everybody else's purge onto a queue
# that is about to go away. There is no legacy un-suffixed id to drop here;
# this schedule has never existed under one.
PURGE_SCHEDULE_PREFIX = "connections-purge-inbound-webhooks"
PURGE_WORKFLOW_PREFIX = "system:connections:purge"

# One delete over an indexed status, on one table. Generous rather than tight:
# the first sweep of a table that has never been swept is the big one, and a
# timeout there costs a whole day's window.
PURGE_TIMEOUT = timedelta(minutes=10)


def purge_schedule_id(task_queue: str) -> str:
    """The schedule id for one deployment's inbound-webhook purge."""
    return f"{PURGE_SCHEDULE_PREFIX}:{task_queue}"


def purge_workflow_id(task_queue: str) -> str:
    """The id of the run the schedule starts. Deterministic, and per queue too.

    Two schedules starting runs under one workflow id would be two deployments
    fighting over one execution — the schedule id alone is not enough.

    This is the **prefix** Temporal is given: the server appends the scheduled
    time to it, so an actual run is
    `system:connections:purge:<queue>-2026-08-24T03:00:00Z`. That is the
    server's doing and not a random id — the part this repository chooses is
    deterministic, which is what house rule 18 is about.
    """
    return f"{PURGE_WORKFLOW_PREFIX}:{task_queue}"


@activity.defn(name="purge_inbound_webhooks", no_thread_cancel_exception=True)
def purge_inbound_webhooks(window: PurgeInboundWebhooks) -> PurgeOutcome:
    """Take the processed deliveries past their retention.

    Through the service, never around it (house rule 10): the filter that
    protects an unprocessed row lives in one place, and it is the place a reader
    looking for it will go.

    Idempotent, which Temporal demands: it deletes by age, so a re-run inside
    the same window removes nothing.
    """
    close_old_connections()
    try:
        rows = services.purge_inbound_webhooks(
            before=now() - timedelta(days=window.retention_days), tenant=None
        )
        log.info("connections.purge.done", inbound_webhooks=rows.count)
        return PurgeOutcome(inbound_webhooks=rows.count)
    finally:
        close_old_connections()


# --- The schedule ------------------------------------------------------------


def purge_inbound_webhooks_schedule(task_queue: str) -> Schedule:
    """The daily sweep, as a value so a test can read it.

    A Temporal Schedule and not a cron entry (`architecture.md`): the schedule
    is deployed with the code, its last run is visible in the Temporal UI, and a
    missed one is a fact rather than a silence.

    The retention rides on the ACTION rather than being read inside the
    activity, for the reason `apps.events`' relay carries its batch size there:
    an operator can then read the window off the schedule instead of out of the
    source, and the two lifetime classes read the same number out of the same
    value.

    `SKIP` on overlap: two sweeps at once would both read the same expired rows,
    and while a second delete is a harmless no-op there is no reason to pay for
    the race.
    """
    return Schedule(
        action=ScheduleActionStartWorkflow(
            PURGE_WORKFLOW,
            PurgeInboundWebhooks(retention_days=INBOUND_WEBHOOK_RETENTION_DAYS),
            id=purge_workflow_id(task_queue=task_queue),
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=PURGE_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


#: The one periodic machine this app owns, declared as data (ADR
#: platform-lifecycle-1): an id builder and a `Schedule` value, and nothing
#: about how either becomes real.
#:
#: **This is the far end of `InboundWebhook.lifecycle`.** House rule 31 walks
#: from the model's `purged_by` to the service, to the activity above that calls
#: it, to the workflow that executes that activity, to this declaration — and
#: refuses the declaration if the walk stops short. Delete this entry and the
#: model's promise becomes the poller that was never built, loudly, at the gate.
PURGE_INBOUND_WEBHOOKS = ScheduleDeclaration(
    name="connections.purge-inbound-webhooks",
    schedule_id=purge_schedule_id,
    schedule=purge_inbound_webhooks_schedule,
    log_prefix="connections",
)


ACTIVITIES: list[Callable[..., Any]] = [purge_inbound_webhooks]

#: Discovered by `apps.workflows.client.discovered_schedules`, which the worker
#: consults at startup. One declaration per periodic machine this app owns.
SCHEDULES: list[ScheduleDeclaration] = [PURGE_INBOUND_WEBHOOKS]
