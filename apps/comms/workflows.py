"""Delivery as durable work: one run per send walks its snapshot plan (ADR comms-5, comms-7)."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from apps.comms.types import (
    DeliverMessage,
    DeliveryAttempt,
    DeliveryStatus,
    MessageOutcome,
    PolicyStep,
    SendStep,
    StepStarted,
)
from apps.core.determinism import reason_of, run_to_finish

#: One attempt at handing the message to a transport; a provider silent this long is retried.
ATTEMPT_TIMEOUT = timedelta(seconds=30)

#: The whole conversation: a host that will never accept it stops being asked within the hour.
DELIVERY_DEADLINE = timedelta(hours=1)

#: Refusals true at attempt 1 that waiting cannot change — caller-fault, before any transport.
#: Class names as strings: Temporal matches names, and `core.exceptions` is not importable (rule 9).
NON_RETRYABLE: tuple[str, ...] = ("Invalid", "NotFound")

DELIVERY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=5,
    non_retryable_error_types=list(NON_RETRYABLE),
)

#: Recording the outcome is a local write: retried briefly, never for ever.
BOOKKEEPING_TIMEOUT = timedelta(seconds=30)
BOOKKEEPING_RETRY = RetryPolicy(maximum_attempts=5)

#: How long the run waits for a provider's status — a named guess past every ESP's own retry window.
STATUS_WAIT = timedelta(hours=72)

#: The `Message.Status` values this run reaches, as strings (rule 9).
MESSAGE_QUEUED = "queued"
MESSAGE_SENT = "sent"
MESSAGE_FAILED = "failed"
MESSAGE_DELIVERED = "delivered"
MESSAGE_SUPPRESSED = "suppressed"

#: The one edge refusal this run waits out (ADR comms-10); any other lever ends the message.
LEVER_TEMPORAL = "temporal"

#: One deferral per step (ADR comms-10): a window that moved while asleep ends as `failed`.
MAX_DEFERRALS = 1

#: The row's `error` when the one deferral is spent.
DEFERRAL_SPENT = "quiet hours were still in force after the deferral; not sent"

#: A step's escalation word, restated from `services.ESCALATE_*` (rule 9).
ESCALATE_DELIVERED = "delivered"

#: Starting a later step is one local write: retried briefly, like the bookkeeping.
STEP_TIMEOUT = timedelta(seconds=30)
STEP_RETRY = RetryPolicy(maximum_attempts=5)


@workflow.defn(name="DeliverMessageWorkflow")
class DeliverMessageWorkflow:
    """Walk one send's plan: deliver, listen, and escalate while that is the plan."""

    def __init__(self) -> None:
        #: What a provider said about each message this run has sent, keyed by
        #: message id. A dict rather than one slot, because an escalation has
        #: several messages in play and a status for step 1 arriving during
        #: step 2's wait must not end step 2's wait. The signal handler writes
        #: it and `run` reads it; that is the whole of the state this workflow
        #: keeps.
        self.reported: dict[str, str] = {}

    @workflow.signal(name="delivery_status")
    def delivery_status(self, reported: DeliveryStatus) -> None:
        """A provider's status arrived. **Sets state and does nothing else.**

        House rule 9 at its sharpest: a signal handler runs inside the
        deterministic sandbox, so it may not read a row, call an activity or
        look at a clock. It records what it was told, under the message id it
        was told about, and lets `run` — which is already awaiting exactly this
        — decide what it means. The row has already been written by the service
        that sent the signal; there is nothing here to persist.
        """
        self.reported[str(reported.message_id)] = str(reported.status)

    @workflow.run
    async def run(self, delivery: DeliverMessage) -> MessageOutcome:
        outcome, _ = await run_to_finish(lambda: self._walk(delivery), retry=BOOKKEEPING_RETRY)
        return outcome

    async def _walk(self, delivery: DeliverMessage) -> MessageOutcome:
        """The plan, one rung at a time. **The whole of the escalation feature.**

        Step 1's message already exists — `send()` wrote it inside the request,
        and its status came along in the input because this module may not read
        a row. Every later step is `send_step`, which re-runs the consent wall at
        *that* moment (ADR comms-7) and may answer `suppressed`.

        Four decisions per rung, in this order:

        1. **queued** goes to the transport, through the same two activities a
           plain send has always used;
        2. **sent** waits for a provider status, for as long as this step said —
           and `wait_seconds=0` means a step that fans out without waiting;
        3. **delivered** ends the chain, whatever the plan said next. Somebody
           answered; chasing them further is the feature inverted;
        4. otherwise the plan decides: `escalate_when="delivered"` goes on to
           the next rung, `"none"` stops here.

        A suppressed step falls straight through 1 and 2 — there is nothing in
        flight and nothing to wait for — and escalates immediately, which is
        exactly what a person who has revoked one channel and not another
        should get. **A step the edge wall refuses reaches the same place by the
        same road** (ADR comms-10): `_deliver` answers `suppressed`, decision 2
        does not fire because the status is not `sent`, and the plan decides
        whether to try the next channel — which is the right answer for a
        message the person's own preferences turned away, and it costs no new
        branch here.

        **And before any of it, the run may sleep.** `delay_seconds` is
        `send_at` expressed as a duration, or the remainder of a quiet-hours
        window the wall deferred at queue time, or zero — which is every
        send that is neither, and therefore almost all of them. The sleep is
        Temporal's own timer: recorded in history, replayed identically, and
        survives a worker restart or a deploy, which is precisely why a
        scheduled send is a workflow and not a row a poller reads.

        It sits **outside** the loop and before step one on purpose. A schedule
        is a fact about the whole send, not about one rung of an escalation: a
        policy scheduled for Monday starts on Monday and then walks its plan at
        its own pace, and a per-step delay would be a second, silent kind of
        `wait_seconds` nobody asked for.
        """
        if delivery.delay_seconds > 0:
            await workflow.sleep(timedelta(seconds=delivery.delay_seconds))

        steps = delivery.steps or [PolicyStep(wait_seconds=int(STATUS_WAIT.total_seconds()))]
        message_id = delivery.message_id
        nonce = delivery.nonce
        status = delivery.first_step_status or MESSAGE_QUEUED
        outcome = MessageOutcome(message_id=message_id, status=status)

        for index, step in enumerate(steps):
            if index:
                started: StepStarted = await workflow.execute_activity(
                    "send_step",
                    SendStep(
                        message_id=delivery.message_id,
                        step=index + 1,
                        channel=step.channel,
                        template=step.template,
                    ),
                    start_to_close_timeout=STEP_TIMEOUT,
                    retry_policy=STEP_RETRY,
                    result_type=StepStarted,
                )
                message_id, status = started.message_id, started.status
                # Its own row, therefore its own nonce: two rungs of one
                # escalation are two messages a person received, not one
                # message twice.
                nonce = started.nonce
                outcome = MessageOutcome(message_id=message_id, status=status)

                # **The interpreter's half.** The step's own consent wall
                # said "not yet" rather than "no": quiet hours is a fact about
                # the clock, and previously the step was written
                # `suppressed` and the chain escalated straight past it — so a
                # person's own quiet window cost them the step and moved the
                # product on to a channel they had not asked for. The run sleeps
                # the window out and then delivers the step it was going to
                # deliver.
                #
                # Bounded by nothing here on purpose: the seconds come from the
                # wall's own arithmetic, the post-sleep `_deliver` re-runs the
                # FULL wall, and `MAX_DEFERRALS` inside `_deliver` is what stops
                # a window that moves from re-arming for ever. One budget, in
                # one place.
                if started.deferred_seconds > 0:
                    await workflow.sleep(timedelta(seconds=started.deferred_seconds))

            if status == MESSAGE_QUEUED:
                outcome = await self._deliver(message_id, nonce)
                status = outcome.status

            if status == MESSAGE_SENT and step.wait_seconds > 0:
                await self._await_status(message_id, timedelta(seconds=step.wait_seconds))

            if self.reported.get(message_id) == MESSAGE_DELIVERED:
                break
            if step.escalate_when != ESCALATE_DELIVERED:
                break

        return outcome

    async def _await_status(self, message_id: str, patience: timedelta) -> None:
        """Hold the run open until this message's provider reports, or time is up.

        Keyed by message id: an escalation has more than one message in play, and
        a late status for step 1 must not be mistaken for an answer about step 2.

        The timeout is caught rather than propagated, because running out of
        patience is not a failure of this run — see the module docstring. Both
        exits lead back into the walk.
        """
        try:
            await workflow.wait_condition(lambda: message_id in self.reported, timeout=patience)
        except TimeoutError:
            # `asyncio.TimeoutError` is this, on 3.11 and after. Catching the
            # builtin keeps the module's import list at what house rule 9 allows.
            workflow.logger.info("comms.delivery.status_wait_expired")

    async def _deliver(self, message_id: str, nonce: str = "") -> MessageOutcome:
        """One message, handed to its transport — or held back, and then recorded.

        **Three endings, not one** (ADR comms-10). The activity now says which
        one happened, because the interpreter may not read a row and until this
        rung could not tell "handed over" from "refused at the edge":

        1. **handed over** — the transport took it; `sent`, and the walk waits
           for a provider status exactly as it always did;
        2. **refused by a permanent lever** — suppression, consent withdrawn.
           The row already says `suppressed` and the service already emitted the
           event inside its own transaction, so there is nothing to record here
           and `finish_message` is not called: recording an outcome for a
           refusal would be a second write about a settled row. Returning
           `suppressed` is what ends the wait — the walk does not wait for a status
           on a message no provider ever saw, so the run ends in milliseconds
           instead of sitting on a seventy-two hour timer;
        3. **held back by a temporal lever** — quiet hours. The activity says
           how many seconds are left on the window, the run **sleeps** it out on
           Temporal's own clock (the deterministic wait; `workflow.sleep` is
           recorded in history and replays identically), and then the whole loop
           runs again — which re-enters `deliver_message` and therefore re-runs
           the FULL wall against whatever is true on the other side of the
           night. A suppression that landed during the sleep refuses there, at
           the second wall, and takes ending 2. The sleep is not a way around
           the wall; it is a way *back to* it.

        Bounded by `MAX_DEFERRALS`, so a window that moves while the run is
        asleep cannot re-arm the wait for ever.
        """
        deferrals = 0
        while True:
            try:
                attempt: DeliveryAttempt = await workflow.execute_activity(
                    "deliver_message",
                    # The nonce rides every attempt of this delivery, unchanged
                    # — which is the whole of what it buys: a retry after a
                    # crash, and a re-send after a deferral, hand the transport
                    # the same identifier, so a provider that honours one can
                    # tell them from a second send.
                    DeliverMessage(message_id=message_id, nonce=nonce),
                    start_to_close_timeout=ATTEMPT_TIMEOUT,
                    schedule_to_close_timeout=DELIVERY_DEADLINE,
                    retry_policy=DELIVERY_RETRY,
                    result_type=DeliveryAttempt,
                )
            except Exception as error:
                # Every attempt is spent, or the transport refused in a way no
                # retry will fix. That is an outcome the product records, not a
                # fault it raises — see the module docstring.
                return await self._record(
                    MessageOutcome(
                        message_id=message_id,
                        status=MESSAGE_FAILED,
                        error=reason_of(error),
                    )
                )

            if attempt.edge_refused_at is None:
                return await self._record(
                    MessageOutcome(
                        message_id=message_id,
                        status=MESSAGE_SENT,
                        provider=attempt.provider,
                        provider_message_id=attempt.provider_message_id,
                    )
                )

            if attempt.refusal_lever != LEVER_TEMPORAL:
                # Ending 2. No bookkeeping activity: the wall's own service
                # wrote the row and emitted the event inside the transaction
                # that refused.
                return MessageOutcome(message_id=message_id, status=MESSAGE_SUPPRESSED)

            if deferrals >= MAX_DEFERRALS:
                return await self._record(
                    MessageOutcome(
                        message_id=message_id,
                        status=MESSAGE_FAILED,
                        error=DEFERRAL_SPENT,
                    )
                )

            deferrals += 1
            await workflow.sleep(timedelta(seconds=attempt.defer_seconds))

    async def _record(self, outcome: MessageOutcome) -> MessageOutcome:
        """Hand one ending to the terminal activity, and give it back unchanged.

        Split out of `_deliver` when that grew its three endings, so that "which
        endings are recorded" is one visible list rather than a shape a reader
        has to reconstruct from the control flow.
        """
        await workflow.execute_activity(
            "finish_message",
            outcome,
            start_to_close_timeout=BOOKKEEPING_TIMEOUT,
            retry_policy=BOOKKEEPING_RETRY,
            result_type=str,
        )
        return outcome


WORKFLOWS: list[type] = [DeliverMessageWorkflow]
