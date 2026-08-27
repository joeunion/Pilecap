"""The spine's three workflows. Deterministic code only (house rule 9).

No ORM, no `httpx`, no clock, no randomness is imported or called here — all of
it is in `activities.py`, invoked **by name**, because importing the activities
module would drag the ORM into code that has to replay identically years from
now.

**`DispatchEventWorkflow`** is what an `emit()` starts, one run per event:

1. one activity loads the endpoints that asked for this event's name, under a
   **bounded** retry policy — an event whose row has gone fails the run
   terminally rather than being read for forever;
2. one delivery activity per endpoint, **in parallel**, each with its retry
   policy declared here at the call site — exponential backoff, a bounded number
   of attempts, and a deadline that is the real answer to "when do we stop";
3. whatever is still failing when the retries are spent is **dead-lettered**:
   the delivery row gets its `dead_lettered_at` and the outbox row goes to
   `failed`, where `manage.py replay_events` can find it;
4. the realtime bridge is pushed to, and no-ops when `apps.realtime` is not
   installed;
5. the search bridge is handed the same envelope, on the same posture — a
   third fan-out leg, no-opping when `apps.search` is not installed, retried
   hard when the index is down (the retry budget IS the catch-up queue, ADR
   search-2) and isolated from the dispatch when that budget is spent;
6. the outbox row is closed either way, because "we tried and it did not work"
   is a state and not a silence;
7. and the run's own `WorkflowRun` row is closed — `completed` or `failed` with
   the reason — because a visibility row that says `running` next to an
   execution Temporal finished is a row that lies.

**`PurgeExpiredWorkflow`** is the deployment's housekeeping, started by a
Temporal Schedule rather than by cron (`architecture.md`: there is no beat and
no cron entry). It closes the gap where the `IdempotencyRecord` table had a
`purge_expired` and nothing that called it — and takes the dispatched outbox
rows past their retention with it.

**`ReconcileOutboxWorkflow`** is the outbox relay, on a schedule beside the
purge. It closes the same class one table along: `Outbox.next_attempt_at` was
written and indexed and read by nothing, so an event whose dispatch died between
the commit and the on-commit hook was stranded silently and forever (ADR events-3).
Its drain is a **loop over bounded batches** — the loop
here, the `LIMIT` in the activity — because an unbounded one timed out and
re-read its own head for ever.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from apps.events.types import (
    CloseOutbox,
    DeadLetter,
    DeliverWebhook,
    DeliveryOutcome,
    DispatchEvent,
    DispatchOutcome,
    IndexSearch,
    LoadedTargets,
    PurgeExpired,
    PurgeOutcome,
    PushRealtime,
    ReconcileOutbox,
    ReconcileOutcome,
    RunFinished,
)

# One database read; a second is not worth waiting for.
LOAD_TIMEOUT = timedelta(seconds=30)

# And a bounded number of them. Without a policy Temporal retries an activity
# **forever** by default, so an event whose row is gone — a rolled-back
# transaction, a purge — left a worker reading a missing row until somebody
# noticed months later (queue V5). A database that is down for a minute is
# still ridden out; one that will never have this row stops being asked within
# a couple of minutes.
#
# The row being gone does not even reach the last attempt: the activity raises
# it as a **non-retryable** `ApplicationError`, so the run fails on the first
# answer. This bounds the other failures — a connection refused, a deadlock —
# which are the ones worth a second look and not a hundredth.
LOAD_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
)

# One POST to somebody else's server, and how long the whole conversation with
# that server may go on for. The deadline is the number that matters: a
# subscriber that is down for ten minutes costs retries, and one that will never
# answer stops being retried within the hour instead of at midnight.
DELIVERY_ATTEMPT_TIMEOUT = timedelta(seconds=15)
DELIVERY_DEADLINE = timedelta(hours=1)

# Declared here, at the call site, rather than inside the activity: the retry
# behaviour is a property of *this* dispatch, and an activity that decided its
# own could not be reused by a workflow that wanted a different answer.
DELIVERY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=6,
)

# Bookkeeping after the fan-out: fast, local, and worth retrying briefly.
BOOKKEEPING_TIMEOUT = timedelta(seconds=30)

# One round trip to the search index, plus the row re-read behind it. Longer
# than the bookkeeping timeout because the handler waits for the engine to
# CONFIRM the write — an indexer that returned before the index had settled
# would report success for work the server might still reject, and the retry
# below, which is the only thing standing between a transient failure and a
# permanently stale document, would never fire.
INDEX_ATTEMPT_TIMEOUT = timedelta(seconds=60)

# **The retry policy IS the catch-up queue** (ADR search-2, § "The indexer"):
# an index that is down, restarting or mid-deploy is ridden out here rather than
# by a human remembering to reindex, and the deadline is what says how long
# "ridden out" means. An hour matches the delivery deadline above, and for the
# same reason: a container that is down for ten minutes costs retries, and one
# that will never answer stops being asked within the hour instead of at
# midnight.
#
# **Past the deadline the document is stale and the backstop is
# `manage.py search_reindex`** (R-c), which is stated here, at the call site,
# because that is where the budget is chosen. The dispatch does NOT fail when
# the budget is spent — see `_index`, below, for why.
INDEX_DEADLINE = timedelta(hours=1)
INDEX_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
)

# Closing out the `WorkflowRun` row the starting service wrote. Until rung A11
# nothing did, so every dispatch left a row saying `running` beside an execution
# Temporal had marked COMPLETED (queue V6). Bounded, because a bookkeeping
# activity that retried forever would outlive the thing it is bookkeeping for.
FINISH_RETRY = RetryPolicy(maximum_attempts=5)
FINISH_ACTIVITY = "mark_run_finished"

# The two terminal values of `apps.workflows.models.WorkflowRun.Status`, as
# strings: this module may import its own `types.py` and nothing else (house
# rule 9), and `apps.events` may not import `apps.workflows` at all.
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"

# How far `_reason` (below) walks a `__cause__` chain before it stops. Three
# links is wrapper, activity error, the activity's own complaint — all of it.
_REASON_DEPTH = 3

# Housekeeping walks two tables with a date filter; minutes, not seconds, and
# only because a very large deployment's first run has a lot to remove.
PURGE_TIMEOUT = timedelta(minutes=10)

# The relay walks one indexed query and re-enqueues **one batch** of what it
# finds. Minutes rather than seconds because a batch is 500 rows and each one
# is a transaction plus a start against Temporal; minutes rather than ten of
# them because the work behind this deadline is now bounded, and a timeout that
# cannot bite is a ceiling nobody can see.
RECONCILE_TIMEOUT = timedelta(minutes=5)

# How many batches one sweep may spend before it leaves the rest to the next
# scheduled sweep. The loop below is what makes the drain finish; this is what
# stops one execution's history growing with the size of an outage. At the
# declared 20,000 pending, a sweep clears 10,000 and the sweep five minutes
# later clears the rest — and because the order is oldest-clock-first, the half
# that waits is always the newest half.
RECONCILE_MAX_BATCHES = 20


def _reason(failure: BaseException) -> str:
    """The failure and what caused it, as one line for a row's `error`.

    Temporal wraps an activity's own exception in an `ActivityError` whose
    `str()` is `"Activity task failed"` — true, and useless to the subscriber
    reading `GET /dead-letters/` to find out what their server answered.
    Walking `__cause__` puts the delivery activity's actual complaint (`HTTP
    500`, `ConnectError: …`) where the door promises it. Bounded, because a
    cause chain is somebody else's data structure; deterministic, because it
    reads nothing but the exception it was handed, which is what makes it legal
    in a module house rule 9 governs.

    A second copy of `apps/workflows/workflows.py::_reason` and deliberately so:
    `apps.events` may not import `apps.workflows` (the layer contract), which is
    the same reason `RUN_COMPLETED` and `RUN_FAILED` are restated above rather
    than imported. django-conventions §7 is the shape both copies keep.
    """
    said: list[str] = []
    seen: BaseException | None = failure
    while seen is not None and len(said) < _REASON_DEPTH:
        said.append(f"{type(seen).__name__}: {seen}")
        seen = seen.__cause__
    return " <- ".join(said)


@workflow.defn(name="DispatchEventWorkflow")
class DispatchEventWorkflow:
    """Fan one event out to everybody who asked for it, and say what happened."""

    @workflow.run
    async def run(self, event: DispatchEvent) -> DispatchOutcome:
        try:
            outcome = await self._dispatch(event)
        except Exception as error:
            # An orphaned event now fails terminally rather than retrying for
            # ever (V5), which makes this the path that actually gets walked:
            # the row says `failed` and why, instead of `running` for ever.
            # `_reason`, not `str(error)`: the wrapper's own message is
            # "Activity task failed" and the run row would carry that (§7).
            await self._finish(status=RUN_FAILED, error=_reason(error))
            raise
        await self._finish(status=RUN_COMPLETED)
        return outcome

    async def _dispatch(self, event: DispatchEvent) -> DispatchOutcome:
        """The fan-out itself. Separated so the bookkeeping wraps all of it."""
        loaded: LoadedTargets = await workflow.execute_activity(
            "load_delivery_targets",
            event,
            start_to_close_timeout=LOAD_TIMEOUT,
            retry_policy=LOAD_RETRY,
            result_type=LoadedTargets,
        )

        results = await asyncio.gather(
            *(
                workflow.execute_activity(
                    "deliver_webhook",
                    DeliverWebhook(event_id=event.event_id, endpoint_id=target.endpoint_id),
                    start_to_close_timeout=DELIVERY_ATTEMPT_TIMEOUT,
                    schedule_to_close_timeout=DELIVERY_DEADLINE,
                    retry_policy=DELIVERY_RETRY,
                    result_type=DeliveryOutcome,
                )
                for target in loaded.targets
            ),
            # The failures are the interesting half: one endpoint that will
            # never answer must not stop the others being delivered to, and it
            # must be dead-lettered rather than lost.
            return_exceptions=True,
        )

        outcome = DispatchOutcome()
        for target, result in zip(loaded.targets, results, strict=True):
            if isinstance(result, BaseException):
                outcome.dead_lettered += 1
                await workflow.execute_activity(
                    "dead_letter_delivery",
                    DeadLetter(
                        event_id=event.event_id,
                        endpoint_id=target.endpoint_id,
                        # The walked cause, not the wrapper: `str(result)` here
                        # is Temporal's "Activity task failed", and the
                        # dead-letter row is read by the subscriber whose server
                        # answered (§7, N193b).
                        error=_reason(result),
                    ),
                    start_to_close_timeout=BOOKKEEPING_TIMEOUT,
                )
            else:
                outcome.delivered += 1

        outcome.pushed = await workflow.execute_activity(
            "push_realtime",
            PushRealtime(event_id=event.event_id),
            start_to_close_timeout=BOOKKEEPING_TIMEOUT,
            result_type=bool,
        )

        outcome.indexed = await self._index(event)

        await workflow.execute_activity(
            "close_outbox",
            CloseOutbox(
                event_id=event.event_id,
                status="failed" if outcome.dead_lettered else "dispatched",
                error=f"{outcome.dead_lettered} endpoint(s) dead-lettered"
                if outcome.dead_lettered
                else "",
            ),
            start_to_close_timeout=BOOKKEEPING_TIMEOUT,
        )
        return outcome

    async def _index(self, event: DispatchEvent) -> bool:
        """The search leg: retried hard, and **isolated from the dispatch**.

        `INDEX_RETRY` inside `INDEX_DEADLINE` is the catch-up queue — a
        Meilisearch that is down, restarting or mid-deploy converges here with
        nobody running anything (ADR search-2's recovery sentence). What this
        method adds is what happens when that budget is *spent*, which the ADR
        answers one layer along: `manage.py search_reindex` is the backstop
        beyond the retries.

        So the failure is caught rather than raised, and the reason is a cost
        comparison rather than a preference. Letting it raise fails the run, so
        `close_outbox` never runs, so the outbox row stays `pending`, so
        `ReconcileOutboxWorkflow` re-dispatches it — and **re-delivers every
        webhook** for this event, to fix a document. That is paying the
        subscribers' bill for the index's problem. Every other leg of this
        dispatch has already succeeded by the time we are here; the honest
        record is `indexed=False` plus a line somebody can search for.

        **The residual, said out loud:** a document stale past the budget stays
        stale until the backstop runs. Nothing detects that drift today — the
        startup reconcile compares DECLARATIONS, not documents — and R-c owns
        both the command and whether the reconcile grows a count comparison.
        """
        try:
            indexed: bool = await workflow.execute_activity(
                "index_search",
                IndexSearch(event_id=event.event_id),
                start_to_close_timeout=INDEX_ATTEMPT_TIMEOUT,
                schedule_to_close_timeout=INDEX_DEADLINE,
                retry_policy=INDEX_RETRY,
                result_type=bool,
            )
        except Exception as error:
            # `workflow.logger` and not `core.log`: house rule 9 governs this
            # module, and Temporal's own logger is the one that does not
            # re-emit on every replay.
            workflow.logger.warning(
                "events.search.index_gave_up event_id=%s reason=%s "
                "detail=the retry budget is spent; the document is stale until "
                "manage.py search_reindex rebuilds this kind",
                event.event_id,
                _reason(error),
            )
            return False
        return indexed

    async def _finish(self, *, status: str, error: str = "") -> None:
        """Close the run's visibility row, whichever way the dispatch ended.

        The same activity `EchoWorkflow` calls, reached **by name** from an app
        that may not import the one that defines it. Idempotent, so a retry
        rewrites the same terminal state.
        """
        await workflow.execute_activity(
            FINISH_ACTIVITY,
            RunFinished(
                workflow_id=workflow.info().workflow_id,
                status=status,
                error=error,
            ),
            start_to_close_timeout=BOOKKEEPING_TIMEOUT,
            retry_policy=FINISH_RETRY,
            result_type=str,
        )


@workflow.defn(name="PurgeExpiredWorkflow")
class PurgeExpiredWorkflow:
    """The deployment's housekeeping: expired idempotency keys, old outbox rows.

    Started by the declared machinery (`activities.PURGE`), which
    the worker ensures at startup. A schedule rather than cron, because cron
    entries live in a place nobody deploys and nobody can see the last run of.
    """

    #: House rule 28's other half (ADR workflows-5), exactly as its sibling
    #: `ReconcileOutboxWorkflow` below carries it: a schedule-started run has no
    #: `WorkflowRun` row to close, because no service asked for it and nobody is
    #: waiting on a visibility row for the deployment's own housekeeping. This
    #: workflow predates the marker — W3's measure-first pass over rule 28's
    #: population found it as the one class satisfying neither half, and booked
    #: it rather than reaching into this app to fix its own rule green.
    owns_no_run = True

    @workflow.run
    async def run(self, window: PurgeExpired) -> PurgeOutcome:
        purged: PurgeOutcome = await workflow.execute_activity(
            "purge_expired_records",
            window,
            start_to_close_timeout=PURGE_TIMEOUT,
            result_type=PurgeOutcome,
        )
        return purged


@workflow.defn(name="ReconcileOutboxWorkflow")
class ReconcileOutboxWorkflow:
    """The outbox relay: the reader `next_attempt_at` did not have.

    `emit()` writes the event, its outbox row and a retry clock in the caller's
    transaction, and the dispatch starts on commit. A process that dies in the
    gap between that commit and the client call leaves a `pending` row holding a
    promise and **nothing that would ever notice** — the clock was written and
    indexed and read by no production code at all, with `manage.py replay_events`
    as the only recovery and a human who already knew as its only trigger
    (ADR events-3).

    Started by the declared machinery (`activities.RECONCILE_OUTBOX`)
    beside the purge, for the same reason: a recovery mechanism somebody has to
    remember to run is the finding one layer up.

    The grace arrives as an argument rather than being read here, because
    subtracting it from the clock is a clock read and a workflow may not make
    one (house rule 9). The activity does it, once, where every other
    non-deterministic thing in this app lives.

    **The drain is a loop here and a `LIMIT` there.** One
    execution of the activity resumes at most a batch and says whether anything
    is left; this workflow asks again until it is told no, or until it has spent
    `RECONCILE_MAX_BATCHES`. The split is house rule 9 again: the ORM cannot
    come up here, and an unbounded walk cannot stay down there, because an
    activity that times out mid-drain is retried from the head and the oldest
    promises are the ones it never reaches.

    The loop is deterministic — integer arithmetic over activity results, which
    Temporal replays from history — and it carries `already_seen` forward so a
    batch that could resume nothing still advances. `types.ReconcileOutbox`
    holds why a count is a sound cursor over this particular set.
    """

    #: House rule 28's other half (ADR workflows-5): a schedule-started run has
    #: no `WorkflowRun` row to close, because no service asked for it — nobody
    #: is waiting on a visibility row for the deployment's own housekeeping.
    owns_no_run = True

    @workflow.run
    async def run(self, window: ReconcileOutbox) -> ReconcileOutcome:
        swept = ReconcileOutcome()
        already_seen = window.already_seen
        for _ in range(RECONCILE_MAX_BATCHES):
            batch: ReconcileOutcome = await workflow.execute_activity(
                "reconcile_outbox",
                ReconcileOutbox(
                    grace_seconds=window.grace_seconds,
                    batch_size=window.batch_size,
                    already_seen=already_seen,
                ),
                start_to_close_timeout=RECONCILE_TIMEOUT,
                result_type=ReconcileOutcome,
            )
            swept.reconciled += batch.reconciled
            swept.unresolved += batch.unresolved
            swept.faults += batch.faults
            # Only the rows this sweep could NOT move stay at the head of the
            # next batch's read; the resumed ones have left the window. Both
            # immovable populations count: a refusal the service made and a
            # fault the activity isolated are both still sitting at the head,
            # and a cursor that stepped past only the first would let one poison
            # row starve every row behind it.
            already_seen += batch.unresolved + batch.faults
            if not batch.more_remaining:
                return swept
        # Every batch spent and the last one still saw more: the sweep hit its
        # ceiling rather than the end of the queue, and says so.
        swept.more_remaining = True
        return swept


WORKFLOWS: list[type] = [DispatchEventWorkflow, PurgeExpiredWorkflow, ReconcileOutboxWorkflow]
