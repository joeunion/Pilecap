"""Quiet hours delay; edge refusals end. ADR comms-10.

Two failures with one cause: the delivery run could not see what the edge wall
decided. `DeliveryAttempt` carried a provider and an id and nothing else, so the
interpreter treated a refusal exactly as it treated a hand-over.

* the wall's answer for quiet hours was `suppressed`, the same word it
  uses for a hard bounce. A marketing message queued at 21:59 and delivery-
  checked at 22:01 was **killed** for a fact about the clock that would stop
  being true before breakfast. Every evening campaign lost the tail of its own
  send window.
* a refused message still went through the `sent` branch of the walk,
  so the run sat on a seventy-two hour timer waiting for a provider status about
  a message no provider had ever seen. Three days of a `WorkflowRun` reading
  `running`, per refusal.

What replaces them is one fork with two arms. A **permanent** lever — the
address suppressed, marketing consent withdrawn — kills as it always did, and
the run closes inside its own execution. A **temporal** lever — quiet hours —
defers: the activity says how many seconds the window has left, the run sleeps
them out on Temporal's clock, and then re-enters the same activity, which runs
the **whole wall** again against whatever is true in the morning.

**The sleep is a road back to the wall, not around it.** That is the property
`test_a_suppression_during_the_deferral_refuses_at_the_second_wall` exists for:
an earlier fix closed the retry road, and a defer path that skipped the
recheck would have reopened it under a new name.

### How these tests move time without a clock library

There is no `time_machine` in this tree and this test suite adds no dependency, so
nothing here freezes `timezone.now()`. Two devices do the job honestly:

* **the window moves, not the reader.** `test_services.py` already establishes
  the idiom — quiet hours is "is *now* inside this window", so a test makes the
  window contain now (or stop containing it) instead of moving now. A message is
  queued while the person has no window at all and delivery-checked a moment
  after they set one, which is exactly the 21:59/22:01 story with the two
  clocks swapped.
* **the window is seconds wide.** For the half that needs real time to pass — a
  deferral that ends and *delivers* — the window closes a couple of seconds out
  and the test waits those seconds for real. The simulated clock is stepped
  separately, by `env.sleep`, because a run started by the service's on-commit
  hook is not a handle the environment skips time for on its own.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

import pytest
from django.utils import timezone
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer

from apps.comms import providers, services
from apps.comms.activities import deliver_message
from apps.comms.models import Channel, Message, MessageTemplate, Recipient
from apps.comms.providers import Sent
from apps.comms.selectors import get_preference
from apps.comms.tests.conftest import make_preference
from apps.comms.types import DeliverMessage, DeliveryAttempt, MessageOutcome
from apps.comms.workflows import DeliverMessageWorkflow
from apps.core.actor import Actor
from apps.core.asyncdb import run_db
from apps.core.models import Organization, Tenant
from apps.core.time import UTC
from apps.events.models import Event
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.context import reset_principal, set_principal
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db(transaction=True)

# How far out the closing edge of a live-window test sits.
#
# The number is a **race margin**, and it is worth saying what the race is: the
# worker is deliberately built *after* the message is queued (that gap is the
# only way to queue a message outside the window and judge it inside without a
# clock library), so the window has to still be shut when the worker finishes
# starting and picks the activity up. Eight seconds is comfortably past that on
# a loaded machine and is also the whole real-time cost of a test that waits for
# a window to pass. Too short and the test goes green by delivering for the
# wrong reason — which is why the delivering test asserts the transport was
# entered *after* the window, and not merely that it was entered.
WINDOW_TAIL = timedelta(seconds=8)

# The same polling constants `test_workflows.py` uses, and for the same reason:
# these wait on another thread, which no simulated clock can skip.
SETTLE_TRIES = 200
SETTLE_PAUSE = 0.05

# Twelve-hour strides, enough of them to walk past `STATUS_WAIT`. Copied rather
# than imported from `test_workflows.py`: a test module that imports another
# test module makes two suites one, and this one is about a different property.
WAIT_STRIDE = timedelta(hours=12)
WAIT_STEPS = 24

CONTEXT: dict[str, Any] = {"name": "Ada"}


# --- a transport that says WHEN it was entered ------------------------------------


@dataclass
class ClockedChannel:
    """A transport that records **when** it was reached, not just that it was.

    `mail.outbox` and a call counter both answer "did anything go out". Neither
    answers the question this fix turns on — *did it go out after the window
    closed* — and a deferral that delivered a second early would pass both.
    """

    slug: str = Channel.EMAIL.value
    sends: list[datetime] = field(default_factory=list)

    def send(self, *, message: Message, subject: str, body: str, nonce: str = "") -> Sent:
        self.sends.append(timezone.now())
        return Sent(provider="clocked", provider_message_id=f"<{message.pk}@clocked>")

    def normalize_status(self, *, payload: dict[str, Any]) -> Any:
        return None


@pytest.fixture
def clocked() -> Iterator[ClockedChannel]:
    """The clocked transport in the `email` slot, and the real one back after."""
    spy = ClockedChannel()
    providers.register_channel(spy)
    try:
        yield spy
    finally:
        providers.register_channel(providers.EmailChannel())


# --- driving the pieces the way the worker would ----------------------------------


@contextmanager
def acting_as(tenant: Tenant, org: Organization) -> Iterator[None]:
    """The principal an inbound interceptor would have unpacked from the headers.

    Set by hand because there is no worker in the activity-level tests. Same
    three values `workflow_context()` reads and nothing else.
    """
    tokens = set_principal(tenant_id=str(tenant.pk), user_id=None, org_id=str(org.pk))
    try:
        yield
    finally:
        reset_principal(tokens)


def delivery_id(tenant: Tenant, message: Message) -> str:
    """The id `send()` will have used — derived, never remembered."""
    # The row records it — `send()` wrote it there before the run existed —
    # so a test that rebuilt the id would be a second implementation of the
    # grammar, agreeing on the day it was written.
    return message.delivery_workflow_id


async def _local_client(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> Client:
    """Point everything at the test server, including the on-commit hook."""
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> Client:
        return attach_interceptors(await Client.connect(target, namespace=namespace))

    monkeypatch.setattr(client_module, "get_client", connect)
    return attach_interceptors(env.client)


async def _timers(handle: WorkflowHandle[Any, Any]) -> list[timedelta]:
    """Every timer this run has started, in history order, as durations."""
    history = await handle.fetch_history()
    return [
        event.timer_started_event_attributes.start_to_fire_timeout.ToTimedelta()
        for event in history.events
        if event.event_type == EventType.EVENT_TYPE_TIMER_STARTED
    ]


async def _first_timer(handle: WorkflowHandle[Any, Any]) -> timedelta:
    """Wait for the run to arm its first timer, and say how long it is for."""
    for _ in range(SETTLE_TRIES):
        started = await _timers(handle)
        if started:
            return started[0]
        await asyncio.sleep(SETTLE_PAUSE)
    raise AssertionError("the run never armed a timer")


async def _edge_refusal(client: Client, handle: WorkflowHandle[Any, Any]) -> DeliveryAttempt:
    """The refusal the deliver activity put into history. **Read from history.**

    Out of the run's own event log rather than off a fake, because what the
    workflow acted on is what history says it acted on — and the whole of this
    rung is that a refusal travels that way at all.
    """
    history = await handle.fetch_history()
    for event in history.events:
        if event.event_type != EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
            continue
        payloads = event.activity_task_completed_event_attributes.result
        decoded = await client.data_converter.decode(list(payloads.payloads), [DeliveryAttempt])
        attempt = decoded[0]
        if isinstance(attempt, DeliveryAttempt) and attempt.edge_refused_at is not None:
            return attempt
    raise AssertionError("no edge refusal was recorded in the run's history")


async def _advance_past_the_wait(env: WorkflowEnvironment, handle: Any) -> None:
    """Step the simulated clock until the run stops running."""
    for _ in range(WAIT_STEPS):
        if (await handle.describe()).status is not WorkflowExecutionStatus.RUNNING:
            return
        await env.sleep(WAIT_STRIDE)


async def _settled_at(tenant: Tenant, message: Message, status: str) -> Message:
    """The row, once the worker has moved it to `status`. Asserts if it never does."""
    row = message
    for _ in range(SETTLE_TRIES):
        row = await run_db(lambda: Message.objects.for_tenant(tenant).get(pk=message.pk))
        if row.status == status:
            return row
        await asyncio.sleep(SETTLE_PAUSE)
    raise AssertionError(f"message stayed {row.status!r}, never reached {status!r}")


def _window_closing_at(moment: datetime) -> tuple[time, time]:
    """An hour-long window that ends at `moment`, named in UTC to the second."""
    return ((moment - timedelta(hours=1)).time(), moment.time())


def _shut_the_window(
    *, tenant: Tenant, actor: Actor, recipient: Recipient, closes_at: datetime
) -> None:
    """Give this person a quiet window that contains now and ends at `closes_at`.

    The window moves and the clock does not — see the module docstring. Through
    the service, like every other write in these tests: `set_quiet_hours` is the
    only verb that touches those three columns.
    """
    start, end = _window_closing_at(closes_at)
    services.set_quiet_hours(tenant=tenant, actor=actor, recipient=recipient, start=start, end=end)


# --- the arithmetic, on its own ---------------------------------------------------


def test_the_window_that_is_not_shut_defers_nothing(
    owner_actor: Actor, recipient: Recipient
) -> None:
    """The negative every other assertion here needs. Outside is zero, not "soon".

    Absent: a deferral computed for a person whose evening has not started,
    which would turn every send into a wait.
    """
    at = timezone.now()
    preference = make_preference(
        actor=owner_actor,
        recipient=recipient,
        consented=True,
        quiet_hours=_window_closing_at(at - timedelta(minutes=5)),
    )

    assert preference.quiet_opens_in(at) == timedelta(0)
    assert not preference.is_quiet_at(at), "the predicate and the arithmetic agree"


def test_a_shut_window_defers_to_its_own_closing_minute(
    owner_actor: Actor, recipient: Recipient
) -> None:
    """Inside the window, the answer is the distance to the far edge — rounded up.

    Rounded **up**, and asserted as such: the caller turns this into an integer
    number of seconds for a timer, and a truncated duration wakes the run a
    fraction of a second before the window closes, where the wall refuses again
    and the deferral is spent on nothing.

    Absent: the run wakes early, re-refuses, and quiet hours is a kill switch
    again with extra steps.
    """
    closes_at = (timezone.now() + timedelta(minutes=42)).replace(microsecond=0)
    preference = make_preference(
        actor=owner_actor,
        recipient=recipient,
        consented=True,
        quiet_hours=_window_closing_at(closes_at),
    )

    ragged = closes_at - timedelta(seconds=90, microseconds=400_000)
    assert preference.quiet_opens_in(ragged) == timedelta(seconds=91)

    exact = closes_at - timedelta(seconds=90)
    assert preference.quiet_opens_in(exact) == timedelta(seconds=90)


def test_the_window_is_read_in_the_persons_own_timezone(
    owner_actor: Actor, recipient: Recipient
) -> None:
    """A window written in somebody else's clock closes at their morning, not ours.

    The same three columns the predicate reads, read the same way — which is why
    both live on the row rather than in two modules: a deferral computed against
    a different zone than the refusal would sleep to the wrong minute, and
    nothing downstream could tell.

    Absent: the arithmetic quietly resolves every window in UTC, and every
    deferral is wrong by the person's own offset.
    """
    # A fixed instant, and the only one in this module: the arithmetic is pure,
    # so `at` is an argument rather than the clock, and pinning it keeps the
    # assertion from depending on what time the suite happens to run.
    at = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)
    preference = make_preference(
        actor=owner_actor,
        recipient=recipient,
        consented=True,
        quiet_hours=(time(6, 0), time(12, 30)),
        quiet_hours_timezone="UTC",
    )
    assert preference.quiet_opens_in(at) == timedelta(minutes=30)

    # The same clock-face window, declared two hours west. The window did not
    # move; the reader did — 12:00 UTC is 10:00 to them, so their 12:30 is still
    # two and a half hours away.
    preference.quiet_hours_timezone = "Etc/GMT+2"
    preference.save(update_fields=["quiet_hours_timezone", "updated_at"])
    assert preference.quiet_opens_in(at) == timedelta(hours=2, minutes=30)


# --- the wall's fork, at the activity ---------------------------------------------


def test_a_temporal_lever_leaves_the_row_queued_and_says_how_long(
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    newsletter: MessageTemplate,
    recorded_workflow_starts: None,
    clocked: ClockedChannel,
) -> None:
    """The fix at the seam it lives at. **Queued, not killed, and for how long.**

    Queued while the person had no quiet window; delivery-checked a moment after
    they set one — the 21:59/22:01 story told by moving the window instead of
    the clock, because this tree has no clock library and this test suite adds no
    dependency.

    Absent: the edge wall answers a fact about the clock with the same
    word it uses for a hard bounce, and the message is thrown away.
    """
    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    message = services.send(
        recipient=recipient,
        template="newsletter",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert message.status == Message.Status.QUEUED, "the wall said yes when the send was made"

    closes_at = (timezone.now() + timedelta(minutes=30)).replace(microsecond=0)
    _shut_the_window(tenant=tenant, actor=owner_actor, recipient=recipient, closes_at=closes_at)

    with acting_as(tenant, root_org):
        attempt = deliver_message(DeliverMessage(message_id=str(message.pk)))

    assert attempt.refusal_lever == services.LEVER_TEMPORAL
    assert attempt.edge_refused_at is not None
    refused_at = datetime.fromisoformat(attempt.edge_refused_at)
    # The exact identity: the deferral is the distance from the refusal to the
    # window's far edge, to the whole second, and never short of it.
    judged = get_preference(tenant=tenant, recipient=recipient, channel=Channel.EMAIL, org=root_org)
    assert judged is not None
    assert timedelta(seconds=attempt.defer_seconds) == judged.quiet_opens_in(refused_at)
    assert refused_at + timedelta(seconds=attempt.defer_seconds) >= closes_at

    row = Message.objects.for_tenant(tenant).get(pk=message.pk)
    assert row.status == Message.Status.QUEUED, "a delay is not a death"
    assert row.suppressed_reason == ""
    assert row.suppressed_at is None
    assert clocked.sends == [], "the window is shut; nothing may be handed over"
    assert not Event.objects.for_tenant(tenant).filter(name="comms.message.suppressed").exists(), (
        "a suppression event for a message about to be delivered is the ledger lying"
    )


def test_a_permanent_lever_still_kills_and_now_says_so(
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
    clocked: ClockedChannel,
) -> None:
    """The other arm: unchanged in behaviour, newly **legible** to the run.

    The row still goes `suppressed` and the event still goes out — R2's contract
    is untouched. What is new is `edge_refused_at` on the result, which is the
    only reason the interpreter can now tell a refusal from a hand-over and
    close the run instead of waiting three days.

    Absent: the fork loses its permanent arm and a suppression becomes a nap.
    """
    message = services.send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    services.suppress_recipient(
        tenant=tenant, actor=owner_actor, recipient=recipient, channel=Channel.EMAIL
    )

    with acting_as(tenant, root_org):
        attempt = deliver_message(DeliverMessage(message_id=str(message.pk)))

    assert attempt.refusal_lever == services.LEVER_PERMANENT
    assert attempt.edge_refused_at is not None
    assert attempt.defer_seconds == 0, "nothing about a suppression expires"
    assert clocked.sends == []
    row = Message.objects.for_tenant(tenant).get(pk=message.pk)
    assert row.status == Message.Status.SUPPRESSED
    assert row.suppressed_reason == Message.SuppressedReason.SUPPRESSED


def test_a_row_already_refused_reports_the_same_refusal_on_a_replay(
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
    clocked: ClockedChannel,
) -> None:
    """One refusal vocabulary, whether this attempt drew it or merely found it.

    Temporal runs an activity at least once. The second pass short-circuits
    above the wall — the row is already `suppressed` — and it has to answer in
    the same words, or the interpreter would sit out `STATUS_WAIT` on the replay
    of a refusal it closed promptly the first time.

    Absent: the same defect survives on the retry path, the same way an
    earlier bug survived on the retry path.
    """
    message = services.send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    services.suppress_recipient(
        tenant=tenant, actor=owner_actor, recipient=recipient, channel=Channel.EMAIL
    )

    with acting_as(tenant, root_org):
        first = deliver_message(DeliverMessage(message_id=str(message.pk)))
        second = deliver_message(DeliverMessage(message_id=str(message.pk)))

    assert (first.refusal_lever, second.refusal_lever) == (
        services.LEVER_PERMANENT,
        services.LEVER_PERMANENT,
    )
    assert second.edge_refused_at is not None
    assert clocked.sends == []
    assert Event.objects.for_tenant(tenant).filter(name="comms.message.suppressed").count() == 1, (
        "one refusal, one announcement"
    )


# --- the run: it waits, it re-judges, and it stops waiting for nothing -------------


@pytest.mark.asyncio
async def test_a_deferred_run_sleeps_the_window_out_and_then_delivers(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
    clocked: ClockedChannel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**The whole of the fix, end to end, against a real server.**

    Queued outside the window, judged inside it, and then delivered on the other
    side of it — with the timer's duration equal to the refusal's own arithmetic
    and the transport entered strictly after the window closed.

    The window is two seconds wide at its closing edge, and those two seconds
    are waited for real: the simulated clock is what fires the timer, and the
    real clock is what the wall reads, so both have to cross the same line.

    It also carries the replay-determinism check: the history this produces is
    the only one in the
    suite with the deferred path in it, so that check runs
    here rather than paying for a second nine-second run of the same story.

    Absent: quiet hours remain a kill switch and every evening campaign
    silently halves; and (for the replay half) the defer path is the app's first
    non-replayable workflow, failing years from now on a worker upgrade.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)

        await run_db(make_preference, actor=owner_actor, recipient=recipient, consented=True)
        message = await run_db(
            services.send,
            recipient=recipient,
            template="newsletter",
            context=CONTEXT,
            channel=Channel.EMAIL,
            tenant=tenant,
            actor=owner_actor,
        )
        assert message.status == Message.Status.QUEUED

        # The person's evening starts now and ends in a couple of seconds. The
        # run has already been started; no worker has picked it up yet, so the
        # wall it meets is this one.
        closes_at = (timezone.now() + WINDOW_TAIL).replace(microsecond=0)
        await run_db(
            _shut_the_window,
            tenant=tenant,
            actor=owner_actor,
            recipient=recipient,
            closes_at=closes_at,
        )

        handle = client.get_workflow_handle(
            delivery_id(tenant, message), result_type=MessageOutcome
        )
        async with build_worker(client):
            armed = await _first_timer(handle)

            # It is waiting, not working: nothing handed over, nothing killed.
            assert clocked.sends == []
            waiting = await run_db(lambda: Message.objects.for_tenant(tenant).get(pk=message.pk))
            assert waiting.status == Message.Status.QUEUED

            # The timer IS the window: the refusal's own arithmetic, recorded in
            # history, and the timer Temporal armed from it are the same number.
            refusal = await _edge_refusal(client, handle)
            assert refusal.refusal_lever == services.LEVER_TEMPORAL
            assert armed == timedelta(seconds=refusal.defer_seconds)
            refused_at = datetime.fromisoformat(str(refusal.edge_refused_at))
            assert refused_at + armed >= closes_at
            assert refused_at + armed < closes_at + timedelta(seconds=1)

            # Real time crosses the window's far edge…
            await asyncio.sleep(max(0.0, (closes_at - timezone.now()).total_seconds()) + 0.25)
            # …and the simulated clock fires the timer the run is sitting on.
            await env.sleep(WINDOW_TAIL + timedelta(seconds=5))

            sent = await _settled_at(tenant, message, Message.Status.SENT)
            await _advance_past_the_wait(env, handle)
            outcome: MessageOutcome = await handle.result()

        # C2-5, on the only history that has the deferred path in it. Rule 9's
        # gate check reads this module's imports and calls; it cannot tell
        # whether the *decisions* replay. Running the current workflow code back
        # over the run that just happened is the instrument that would catch a
        # branch taken on something history does not hold, and `raise_on_replay
        # _failure` is left explicit because a replay test that swallowed the
        # failure could not fail.
        history = await handle.fetch_history()
        assert any(
            event.event_type == EventType.EVENT_TYPE_TIMER_STARTED for event in history.events
        ), "no timer in history — this replayed a plain send, not a deferral"
        await Replayer(workflows=[DeliverMessageWorkflow]).replay_workflow(
            history, raise_on_replay_failure=True
        )

    assert outcome.status == Message.Status.SENT
    assert sent.provider == "clocked"
    assert len(clocked.sends) == 1, "one message, handed over once"
    assert clocked.sends[0] >= closes_at, (
        "the transport was entered before the person's quiet window had closed"
    )
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(type="DeliverMessageWorkflow")
    )
    assert run.status == WorkflowRun.Status.COMPLETED
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_a_suppression_during_the_deferral_refuses_at_the_second_wall(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
    clocked: ClockedChannel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2-3. **The sleep is a road back to the wall, not around it.**

    The address is suppressed while the run is asleep. Waking up is re-entering
    `deliver_message`, which re-runs the FULL wall — so the second judgement
    sees the suppression, takes the permanent arm, and no transport is entered.

    Absent: the defer path becomes the one road around the wall SEC-R1b just
    closed on the retry road — and it would be a road with a timer on it, which
    is the hardest kind to notice.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)

        await run_db(make_preference, actor=owner_actor, recipient=recipient, consented=True)
        message = await run_db(
            services.send,
            recipient=recipient,
            template="newsletter",
            context=CONTEXT,
            channel=Channel.EMAIL,
            tenant=tenant,
            actor=owner_actor,
        )
        closes_at = (timezone.now() + WINDOW_TAIL).replace(microsecond=0)
        await run_db(
            _shut_the_window,
            tenant=tenant,
            actor=owner_actor,
            recipient=recipient,
            closes_at=closes_at,
        )

        handle = client.get_workflow_handle(
            delivery_id(tenant, message), result_type=MessageOutcome
        )
        async with build_worker(client):
            await _first_timer(handle)

            # They ask to be left alone while the run is asleep.
            await run_db(
                services.suppress_recipient,
                tenant=tenant,
                actor=owner_actor,
                recipient=recipient,
                channel=Channel.EMAIL,
            )

            await asyncio.sleep(max(0.0, (closes_at - timezone.now()).total_seconds()) + 0.25)
            await env.sleep(WINDOW_TAIL + timedelta(seconds=5))

            refused = await _settled_at(tenant, message, Message.Status.SUPPRESSED)
            outcome: MessageOutcome = await handle.result()
            # Read while the test server is still up: the deferral's own timer,
            # and nothing else. In particular not `STATUS_WAIT`.
            armed = await _timers(handle)

    assert outcome.status == Message.Status.SUPPRESSED
    assert refused.suppressed_reason == Message.SuppressedReason.SUPPRESSED
    assert refused.sent_at is None
    assert clocked.sends == [], "the wall refused on waking and the transport was still reached"
    # And having refused, the run stops: no seventy-two hour wait behind it.
    assert len(armed) == 1, f"one deferral and nothing else, but the run armed {armed}"
    assert timedelta(hours=72) not in armed
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(type="DeliverMessageWorkflow")
    )
    assert run.status == WorkflowRun.Status.COMPLETED
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_a_permanent_refusal_closes_the_run_without_arming_a_single_timer(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    clocked: ClockedChannel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**Stated as the absence of a timer.**

    The simulated clock is never stepped in this test and the run still ends.
    That is the whole claim: before this fix the run reached `handle.result()`
    only after seventy-two simulated hours were walked past it, and a
    `WorkflowRun` row read `running` for three days about a message refused in
    milliseconds.

    `_timers(handle) == []` is the assertion that cannot pass vacuously — a run
    that had merely got *faster* would still show the timer.

    Absent: a 72h zombie per refused message, and the run ledger lies by
    lateness.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)

        message = await run_db(
            services.send,
            recipient=recipient,
            template="receipt",
            context=CONTEXT,
            channel=Channel.EMAIL,
            tenant=tenant,
            actor=owner_actor,
        )
        await run_db(
            services.suppress_recipient,
            tenant=tenant,
            actor=owner_actor,
            recipient=recipient,
            channel=Channel.EMAIL,
        )

        handle = client.get_workflow_handle(
            delivery_id(tenant, message), result_type=MessageOutcome
        )
        async with build_worker(client):
            # No `env.sleep`, no clock stepping, no patience: the run either
            # ends on its own or this test does not finish.
            outcome: MessageOutcome = await asyncio.wait_for(handle.result(), timeout=30)
            armed = await _timers(handle)
            assert (await handle.describe()).status is WorkflowExecutionStatus.COMPLETED

    assert armed == [], f"the run waited on {armed} for a status no provider will send"
    assert outcome.status == Message.Status.SUPPRESSED
    assert clocked.sends == []
    row = await run_db(lambda: Message.objects.for_tenant(tenant).get(pk=message.pk))
    assert row.status == Message.Status.SUPPRESSED
    assert row.sent_at is None
    assert not await run_db(
        lambda: Event.objects.for_tenant(tenant).filter(name="comms.message.sent").exists()
    ), "nothing was sent, so nothing may say it was"
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(type="DeliverMessageWorkflow")
    )
    assert run.status == WorkflowRun.Status.COMPLETED
    assert run.finished_at is not None
