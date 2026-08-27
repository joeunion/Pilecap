"""This app's one workflow. Deterministic code only (house rule 9).

No ORM, no `httpx`, no clock and no randomness is imported or called here — all
of it is in `activities.py`, invoked **by name**, because importing the
activities module would drag the ORM into code that has to replay identically
years from now. The only module of ours this file imports is its own
`types.py`, which is standard library all the way down.

**`PurgeInboundWebhooksWorkflow`** is the deployment's housekeeping for this
app: the processed deliveries past their retention, deleted on a schedule
rather than by a cron entry (`architecture.md`: there is no beat and no cron).
It is the machine that makes `InboundWebhook`'s `purged` declaration true — and
writing the two in one commit is the whole point of house rule 31, because a
table shaped for a sweeper with no sweeper looks exactly like a table that is
finished.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

from apps.connections.types import PURGE_WORKFLOW, PurgeInboundWebhooks, PurgeOutcome

# One delete over an indexed status, on one table. The same number the activity
# is sized for, declared here at the call site rather than inside the activity:
# the timeout is a property of *this* run, and an activity that decided its own
# could not be reused by a workflow that wanted a different answer.
PURGE_TIMEOUT = timedelta(minutes=10)


@workflow.defn(name=PURGE_WORKFLOW)
class PurgeInboundWebhooksWorkflow:
    """Delete the inbound webhooks whose hand-off closed longer ago than the window.

    Started by the declared machinery (`activities.PURGE_INBOUND_WEBHOOKS`),
    which the deployment's lifetime class turns into either a durable Temporal
    Schedule or a timer on a live worker (ADR platform-lifecycle-1). A schedule
    rather than cron, because cron entries live in a place nobody deploys and
    nobody can see the last run of.
    """

    #: House rule 28 (ADR workflows-5), and the same half its siblings
    #: `PurgeExpiredWorkflow` and `ReconcileOutboxWorkflow` carry: a
    #: schedule-started run has no `WorkflowRun` row to close, because no
    #: service asked for it and nobody is waiting on a visibility row for the
    #: deployment's own housekeeping. The marker means "I own no row" — never
    #: "I am exempt" — and the ledger not lying by omission is the property
    #: rule 28 is defending.
    owns_no_run = True

    @workflow.run
    async def run(self, window: PurgeInboundWebhooks) -> PurgeOutcome:
        purged: PurgeOutcome = await workflow.execute_activity(
            "purge_inbound_webhooks",
            window,
            start_to_close_timeout=PURGE_TIMEOUT,
            result_type=PurgeOutcome,
        )
        return purged


WORKFLOWS: list[type] = [PurgeInboundWebhooksWorkflow]
