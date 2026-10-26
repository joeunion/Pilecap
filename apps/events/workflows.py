"""The spine's three workflows: dispatch one event, the purge, the outbox relay (rule 9).

The retry floor rides `DispatchEvent.retry_floor`; this module reads no settings.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from apps.core.determinism import COMPLETED, FAILED, finish_run, reason_of, retry_policy
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
)

#: One database read.
LOAD_TIMEOUT = timedelta(seconds=30)

#: Bounded: a missing event is non-retryable, and this bounds the rest (a refused connection).
LOAD_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
)

#: One POST, and how long the whole conversation with that subscriber may go on.
DELIVERY_ATTEMPT_TIMEOUT = timedelta(seconds=15)
DELIVERY_DEADLINE = timedelta(hours=1)

#: Declared at the call site: the retry behaviour is this dispatch's, not the activity's.
DELIVERY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=6,
)

#: Bookkeeping after the fan-out: fast, local.
BOOKKEEPING_TIMEOUT = timedelta(seconds=30)

#: One round trip to the index, waiting for it to confirm the write.
INDEX_ATTEMPT_TIMEOUT = timedelta(seconds=60)
#: The retry budget IS the catch-up queue (ADR search-2); past it, `manage.py search_reindex`.
INDEX_DEADLINE = timedelta(hours=1)
#: An index that refused a write is usually mid-settle: the first retry waits twice the floor.
INDEX_FLOOR_MULTIPLE = 2
INDEX_MAXIMUM_INTERVAL = timedelta(minutes=5)


def index_retry(floor: float | None) -> RetryPolicy:
    """The search leg's policy: twice the handed floor, capped never below its own interval."""
    initial = None if floor is None else INDEX_FLOOR_MULTIPLE * floor
    ceiling = INDEX_MAXIMUM_INTERVAL
    if initial is not None:
        ceiling = max(ceiling, timedelta(seconds=initial))
    return retry_policy(initial_seconds=initial, maximum_interval=ceiling)


#: Three tables by date; minutes for a large deployment's first run.
PURGE_TIMEOUT = timedelta(minutes=10)

#: One bounded batch: a transaction and a Temporal start per row.
RECONCILE_TIMEOUT = timedelta(minutes=5)

#: Batches per sweep, so one execution's history does not grow with an outage.
RECONCILE_MAX_BATCHES = 20


@workflow.defn(name="DispatchEventWorkflow")
class DispatchEventWorkflow:
    """Fan one event out to everybody who asked for it, and say what happened."""

    @workflow.run
    async def run(self, event: DispatchEvent) -> DispatchOutcome:
        try:
            outcome = await self._dispatch(event)
        except Exception as error:
            await finish_run(status=FAILED, error=reason_of(error))
            raise
        await finish_run(status=COMPLETED)
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
            # One endpoint that never answers must not stop the others; it is dead-lettered.
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
                        error=reason_of(result),
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
        """The search leg: retried hard, and isolated from the dispatch when the budget is spent.

        why-not raise: the run would fail, the outbox stay pending and the relay re-deliver every
        webhook to fix one document; `indexed=False` and a log line are the honest record.
        """
        try:
            indexed: bool = await workflow.execute_activity(
                "index_search",
                IndexSearch(event_id=event.event_id),
                start_to_close_timeout=INDEX_ATTEMPT_TIMEOUT,
                schedule_to_close_timeout=INDEX_DEADLINE,
                retry_policy=index_retry(event.retry_floor),
                result_type=bool,
            )
        except Exception as error:
            # why-not `core.log`: `workflow.logger` does not re-emit on replay (rule 9).
            workflow.logger.warning(
                "events.search.index_gave_up event_id=%s reason=%s "
                "detail=the retry budget is spent; the document is stale until "
                "manage.py search_reindex rebuilds this kind",
                event.event_id,
                reason_of(error),
            )
            return False
        return indexed


@workflow.defn(name="PurgeExpiredWorkflow")
class PurgeExpiredWorkflow:
    """The deployment's housekeeping, started by the declared schedule (`activities.PURGE`)."""

    #: Schedule-started: no `WorkflowRun` row to close (rule 28, ADR workflows-5).
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
    """The outbox relay (ADR events-3): a loop of bounded batches here, the `LIMIT` in the activity.

    The grace arrives as an argument: subtracting it from the clock is a clock read (rule 9).
    """

    #: Schedule-started: no `WorkflowRun` row to close (rule 28, ADR workflows-5).
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
            # Refusals and faults both stay at the head, so both advance the cursor.
            already_seen += batch.unresolved + batch.faults
            if not batch.more_remaining:
                return swept
        swept.more_remaining = True
        return swept


WORKFLOWS: list[type] = [DispatchEventWorkflow, PurgeExpiredWorkflow, ReconcileOutboxWorkflow]
