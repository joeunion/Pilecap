"""Delivery, as durable work — because a mail host is a thing that blinks.

Nothing sends inside a request. `send()` writes the row, says
`comms.message.queued`, and starts this: one run per message, started on the
sending transaction's commit, with an id derived from the message's primary key
so a retried send starts one run and not two.

House rule 9, visible: this module imports `timedelta`, `temporalio`, and its
own `types.py` — and nothing else. **No ORM, no network, no clock, no
randomness, and no import of `activities.py`** — the activities are invoked by
name, because importing them would drag the ORM into a module that has to
replay identically years from now.

**A message that could not be delivered does not fail the run.** The attempts
are spent, the terminal activity records `failed` and emits
`comms.message.failed`, and the run completes having done its whole job. A run
left `failed` for an outcome the product handled correctly is an alert somebody
has to triage every time an address is wrong. What *does* fail the run is the
bookkeeping failing — that is a real fault, and it should look like one.

**And it walks a plan** (C2-comms-b). One run per `send()`, whether that send
was one message or an escalation of four: the run is the only orchestrator, so
"they answered, stop chasing them" has exactly one place to be true. The plan is
a **snapshot** taken when the send started (`DeliverMessage.steps`) and this
module never reads a row — revising a policy mid-flight changes the next send
and not this one, which is house rule 9 doing the work it exists for rather than
a promise in a docstring.

A plain send is the same walk with no plan: `steps` empty becomes one implicit
step that delivers, waits `STATUS_WAIT` for a provider status, and ends. That is
byte-for-byte what the earlier single-step workflow did, expressed as the general case rather than
preserved as a special one.

**And it knows when it was refused** (ADR comms-10). The edge wall
speaks back through `DeliveryAttempt` now, so the two things the interpreter
used to be blind to are things it can act on. A **permanent** refusal —
suppression, consent withdrawn — ends the step immediately: no `STATUS_WAIT`,
because no provider ever saw the message and no status is coming, and a run
sitting open for three days about a refusal decided in milliseconds is the run
ledger lying by laziness. A **temporal** refusal — quiet hours — is not a
refusal at all but a *later*: the run sleeps out the window on Temporal's clock
and then re-enters the same activity, which re-runs the whole wall against
whatever is true in the morning. Killing an evening's marketing because it was
judged two minutes after ten was throwing away sends nobody objected to.

**And it waits** (ADR comms-5). Handing a message to a transport is not
the end of the story: hours later the provider says whether it arrived, and
that report has to land somewhere. It lands here, as a signal, on a run that is
still alive to receive it — which is the entire reason the wait is in *this*
rung and not deferred. A run that completed the moment the SMTP conversation
ended would `Conflict` on every status webhook that followed, and the seam
would be untestable in principle rather than merely untested.

Each wait is bounded and ends the same way either way: a status arrives, or the
step's `wait_seconds` runs out. **Silence is not a bounce.** A provider that
never reports leaves a `sent` message saying `sent`, which is the honest record;
marking it failed would invent a fact, and waiting for ever would leave a run
open per message for the life of the deployment. What silence *does* mean, when
a step says `escalate_when="delivered"`, is that the next rung is tried — which
is the entire product feature.
"""

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
    RunFinished,
    SendStep,
    StepStarted,
)

# How long one attempt at handing the message to a transport may take. Thirty
# seconds is already generous for an SMTP conversation; a provider that has not
# answered in that time is a provider having a day, and the retry is the answer.
ATTEMPT_TIMEOUT = timedelta(seconds=30)

# And how long the whole conversation may go on for. This is the number that
# matters: a mail host down for ten minutes costs retries, and one that will
# never accept this message stops being asked within the hour rather than at
# midnight.
DELIVERY_DEADLINE = timedelta(hours=1)

# Declared here, at the call site, rather than inside the activity: the retry
# behaviour is a property of *this* delivery, and an activity that decided its
# own could not be reused by a caller that wanted a different answer.
#: The refusals that are **already true at attempt 1** and cannot become false
#: by waiting. Retrying one of these is not caution, it is the run
#: telling the message log a lie for a minute: a push to a contact with no
#: registered device showed `sending` for about sixty seconds — five attempts
#: and their backoff — before failing with the reason it had on the first.
#:
#: Both members are **caller-fault, decided before any transport was reached**.
#: `Invalid` is bad input (no device, no address, an unknown platform);
#: `NotFound` is a reference this hat cannot reach, which a retry cannot change
#: either — and the reachability answer must not be re-asked five times, because
#: an actor's hat moving mid-run is a different bug and this would hide it.
#:
#: **What is deliberately NOT here** is everything that can succeed later: a
#: transport raising, a timeout, a gateway's 500, `Conflict`. Those are the
#: retry policy's whole reason to exist. The names are the class names Temporal
#: matches on, which is why they are strings rather than the types — the
#: workflow module may not import `core.exceptions` (house rule 9).
NON_RETRYABLE: tuple[str, ...] = ("Invalid", "NotFound")

DELIVERY_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=5,
    non_retryable_error_types=list(NON_RETRYABLE),
)

# Recording the outcome is a local database write: fast, and worth retrying
# briefly rather than for ever.
BOOKKEEPING_TIMEOUT = timedelta(seconds=30)
BOOKKEEPING_RETRY = RetryPolicy(maximum_attempts=5)

# How long to hold the run open waiting for the provider to say what became of
# a message it accepted. **A named guess**, and worth naming as one: three days
# is comfortably past every ESP's own retry window for a tracking webhook, and
# well short of a run that is really a leak. The cost of getting it wrong is
# bounded in one direction only — too short and a very late status lands on the
# row and the event but not on a run; too long and a run per message sits open.
# It is a number to revisit with real provider telemetry, not a constant to
# defend.
STATUS_WAIT = timedelta(hours=72)

# Closing out the `WorkflowRun` row the starting service wrote. A visibility row
# saying `running` beside an execution Temporal has finished is a row that lies
# (queue V6), so every path through `run` closes it.
FINISH_ACTIVITY = "mark_run_finished"

# The two terminal values of `apps.workflows.models.WorkflowRun.Status`, and the
# two of `apps.comms.models.Message.Status` this workflow can reach. Strings,
# because this module may import its own `types.py` and nothing else.
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
MESSAGE_QUEUED = "queued"
MESSAGE_SENT = "sent"
MESSAGE_FAILED = "failed"
MESSAGE_DELIVERED = "delivered"
MESSAGE_SUPPRESSED = "suppressed"

# The one kind of edge refusal this module waits for (ADR comms-10). A string,
# for the same reason every other value in this module is one: `services` owns
# the definitions — `services.LEVER_TEMPORAL` is the original — and this module
# may import its own `types.py` and nothing else.
#
# **Only `temporal` sleeps, and everything else ends the message.** Written as
# "not temporal" rather than "is permanent" on purpose: a lever kind this module
# has never heard of — a newer service, an older worker replaying — must fall to
# the ending that stops, not to the one that waits. Fail closed is the direction
# a comms product wants when it is unsure whether it is allowed to mail somebody.
LEVER_TEMPORAL = "temporal"

# How many times one step may wait out a temporal lever before it stops trying.
#
# **One**, and the ADR says one: the wall is re-run once after the sleep, and by
# then the window it slept out is over. A second temporal refusal means the
# window MOVED while the run was asleep — the person widened it — and the honest
# answers are "sleep again, possibly for ever" or "stop and say so". This picks
# the second: a deferral that cannot converge is recorded as a failure with its
# reason on the row, where support can see it, rather than a run that quietly
# re-arms itself every morning.
MAX_DEFERRALS = 1

# What the row's `error` says when that happens. Not a refusal code and not a
# new word for the wall: the message genuinely did not go out, and `failed` is
# this app's existing vocabulary for that.
DEFERRAL_SPENT = "quiet hours were still in force after the deferral; not sent"

# What a step says to do when it did not land. Restated as strings for the same
# reason every other value here is: this module may import its own `types.py`
# and nothing else, and `services.ESCALATE_*` is where the set is enforced.
ESCALATE_DELIVERED = "delivered"

# Starting a later step is a local database write behind one service call: fast,
# and worth retrying briefly rather than for ever, exactly like the bookkeeping.
STEP_TIMEOUT = timedelta(seconds=30)
STEP_RETRY = RetryPolicy(maximum_attempts=5)


def failure_reason(error: BaseException) -> str:
    """The transport's own words, not the wrapper's.

    Temporal wraps an activity failure in an `ActivityError` whose `str()` is
    "Activity task failed" — true, and useless on a `Message.error` somebody is
    reading to find out why a customer never got their receipt. The chain is
    walked to the innermost cause, which is what the provider actually said.

    Pure string handling, so it is safe in a module that has to replay
    identically (house rule 9).
    """
    cause: BaseException = error
    while cause.__cause__ is not None:
        cause = cause.__cause__
    return str(cause) if cause is not error else str(error)


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
        try:
            outcome = await self._walk(delivery)
        except Exception as error:
            # The bookkeeping itself failed. The row says so, and then the run
            # still fails — a `WorkflowRun` left at `running` beside an
            # execution that ended is worse than no row at all.
            await self._finish(status=RUN_FAILED, error=str(error))
            raise
        await self._finish(status=RUN_COMPLETED)
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
                        error=failure_reason(error),
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

    async def _finish(self, *, status: str, error: str = "") -> None:
        """Close the run's visibility row, whichever way the delivery ended.

        The same activity every other app's workflows call, reached **by name**
        from an app that does not import the one that defines it. Idempotent, so
        a retry rewrites the same terminal state.
        """
        await workflow.execute_activity(
            FINISH_ACTIVITY,
            RunFinished(
                workflow_id=workflow.info().workflow_id,
                status=status,
                error=error,
            ),
            start_to_close_timeout=BOOKKEEPING_TIMEOUT,
            retry_policy=BOOKKEEPING_RETRY,
            result_type=str,
        )


WORKFLOWS: list[type] = [DeliverMessageWorkflow]
