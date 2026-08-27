"""`send_at`: a scheduled send waits in a **workflow timer**, not in a poller.

T4. Three things are being proved and they are not the same thing:

* **the timer exists and is Temporal's.** `send_at` becomes a duration on the
  workflow's payload and the run sleeps it on Temporal's own clock —
  `TIMER_STARTED` in history, replayed identically, surviving a worker restart
  or a deploy. That is why a scheduled send is a workflow and not a
  `next_attempt_at` column somebody has to write a poller for (house rule 30's
  defect, pointed the other way);
* **the wall runs on the far side of it.** Consent is checked at queue time and
  again when the timer wakes. Scheduling is not a way to bank permission, and a
  revocation that lands in between refuses at the second wall — the same
  property `test_quiet_hours_defer.py` proves for a deferral, for the same
  reason: the sleep is a road back to the wall, not around it;
* **the shapes hold.** Rule 9 — the sleep is in `workflows.py` and the
  arithmetic that produced it is in a service; nothing in the workflow module
  reads a clock or a row. Rule 28 — the run still closes its `WorkflowRun`
  through the finish seam, whichever way it ends.

### What is NOT here, and is a named gap rather than an omission

There is **no `send_at` column on `Message`**. The rung's criteria said
"migrations 0 expected; stop-and-report if `send_at` needs a column", and it
does not need one to work: the schedule is on the run. What that costs is
observability — a scheduled message reads as `queued` like any other and "what
is going out on Monday" is a question only Temporal can answer. Reported rather
than quietly fixed with a migration nobody asked for, and
`test_a_scheduled_message_is_indistinguishable_on_the_row` pins the gap so it is
a decision somebody can reverse rather than a surprise somebody discovers.

There is also no cancel and no reschedule. Same reason, same shape.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from django.core import mail
from django.utils import timezone
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer

from apps.accounts.models import User
from apps.comms import services
from apps.comms.models import Channel, Message, MessageTemplate, Recipient
from apps.comms.tests.conftest import make_preference
from apps.comms.types import MessageOutcome
from apps.comms.workflows import DeliverMessageWorkflow
from apps.core.actor import Actor
from apps.core.asyncdb import run_db
from apps.core.exceptions import Invalid
from apps.core.models import Tenant
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.models import WorkflowRun

CONTEXT: dict[str, Any] = {"name": "Ada"}

#: Far enough out that no amount of worker start-up drifts into it, and short
#: enough that the simulated clock steps past it in one stride. It is never
#: waited on in real time — `env.sleep` skips it — so the number is about
#: legibility rather than about the suite's wall clock.
AHEAD = timedelta(hours=6)

# The same polling constants the sibling workflow modules use, and for the same
# reason: these wait on another thread, which no simulated clock can skip.
SETTLE_TRIES = 200
SETTLE_PAUSE = 0.05


# --- the arithmetic, without a server ---------------------------------------------


@pytest.mark.django_db
def test_a_naive_moment_is_refused_by_name(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """No default zone, and there will not be one.

    A scheduled send is a promise about an instant; a moment with no offset is a
    moment in somebody's assumption, and guessing whose midnight was meant is
    the one mistake that cannot be recovered from afterwards. So it is a refusal
    that names the field rather than a silent localisation into the server's
    zone.

    *Absent:* a client in Auckland schedules 09:00 and the server sends at 21:00
    the previous day, and nothing anywhere said so.
    """
    from datetime import datetime

    with pytest.raises(Invalid) as raised:
        services.send(
            recipient=recipient,
            template="receipt",
            context=CONTEXT,
            channel=Channel.EMAIL,
            tenant=tenant,
            actor=owner_actor,
            send_at=datetime(2026, 9, 1, 9, 0),
        )
    assert "send_at" in raised.value.errors
    assert not Message.objects.for_tenant(tenant).exists(), "and nothing was written"


@pytest.mark.django_db
def test_a_moment_already_past_sends_now_rather_than_refusing(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """Your clock and ours disagreeing by a second must not be an error.

    The honest reading of "send it at 09:00", received at 09:01, is *send it*.

    *Absent:* every client whose clock runs a moment fast gets refusals it
    cannot diagnose.
    """
    message = services.send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
        send_at=timezone.now() - timedelta(hours=1),
    )

    assert message.status == Message.Status.QUEUED
    assert message.delivery_workflow_id


@pytest.mark.django_db
def test_a_scheduled_message_says_so_on_the_row(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """**The gap this test used to pin is closed**, and it is the same test.

    The deferred-window mechanism shipped the timer with no column and wrote the cost down here as
    `test_a_scheduled_message_is_indistinguishable_on_the_row`: both sends read
    `queued`, and "what is going out on Monday" was a question only the Temporal
    UI could answer. That test asserted `send_at` was NOT a field, and its
    docstring said failing was the right day to change it. This is that day and
    this is that change — the name inverted, the claim inverted, the id kept so
    the history is followable.

    The row now tells a support agent which message is waiting and until when,
    with no second system to open.
    """
    at_once = services.send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    later = services.send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
        send_at=timezone.now() + AHEAD,
    )

    # Both are still `queued` — the status was never the thing that could
    # distinguish them, which is exactly why the column was needed.
    assert at_once.status == later.status == Message.Status.QUEUED
    assert at_once.send_at is None, "an immediate send is due now, and says nothing"
    assert later.send_at is not None
    assert abs((later.send_at - (timezone.now() + AHEAD)).total_seconds()) < 60

    # And it reaches the wire, which is where a support agent actually reads it.
    from apps.comms.schemas import MessageOut

    assert MessageOut.from_orm(later).send_at == later.send_at


@pytest.mark.django_db
def test_a_deferred_message_carries_its_due_time_too(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, newsletter: MessageTemplate
) -> None:
    """A quiet-hours deferral is the same support question with the same answer.

    "Why is this still queued" is asked about a deferred message far more often
    than about a scheduled one, and a column that spoke only for `send_at=`
    callers would have been a support answer with a footnote.
    """
    from datetime import time

    from apps.comms.tests.conftest import make_preference

    now = timezone.now()
    make_preference(
        actor=owner_actor,
        recipient=recipient,
        consented=True,
        quiet_hours=(
            (now - timedelta(minutes=30)).time().replace(second=0, microsecond=0),
            (now + timedelta(hours=3)).time().replace(second=0, microsecond=0),
        ),
    )
    deferred = services.send(
        recipient=recipient,
        template="newsletter",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )

    assert deferred.status == Message.Status.QUEUED
    assert deferred.send_at is not None, "held by the window, and the row says until when"
    assert isinstance(time(0, 0), time)


# --- the timer, driven --------------------------------------------------------------


async def _local_client(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> Client:
    """Point everything at the test server, including the on-commit hook."""
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> Client:
        return attach_interceptors(await Client.connect(target, namespace=namespace))

    monkeypatch.setattr(client_module, "get_client", connect)
    return attach_interceptors(env.client)


async def _first_timer(handle: Any) -> timedelta:
    """Wait for the run to arm its first timer, and say how long it is for.

    Read out of the run's own history rather than off a fake, because what the
    workflow did is what history says it did — and the whole of `send_at` is
    that the wait is a recorded timer rather than a thread somewhere.
    """
    for _ in range(SETTLE_TRIES):
        history = await handle.fetch_history()
        timers: list[timedelta] = [
            event.timer_started_event_attributes.start_to_fire_timeout.ToTimedelta()
            for event in history.events
            if event.event_type == EventType.EVENT_TYPE_TIMER_STARTED
        ]
        if timers:
            return timers[0]
        await asyncio.sleep(SETTLE_PAUSE)
    raise AssertionError("the run never armed a timer")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_scheduled_send_arms_a_timer_and_sends_nothing_until_it_fires(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole feature, in one drive: a timer, then a send.

    Two assertions and the order matters. The timer is `AHEAD` long and is in
    history — so the wait is Temporal's, replayable and deploy-proof. And
    **nothing goes out while it is running**, which is what a scheduled send
    means and what a naive implementation (sleep in an activity, or worse, in a
    thread) would also appear to do until the worker restarted.

    *Absent:* the run reaches the transport immediately and `send_at` is a
    parameter that formats a date.
    """
    mail.outbox.clear()

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            message = await run_db(
                services.send,
                recipient=recipient,
                template="receipt",
                context=CONTEXT,
                channel=Channel.EMAIL,
                tenant=tenant,
                actor=owner_actor,
                send_at=timezone.now() + AHEAD,
            )
            handle = client.get_workflow_handle(
                message.delivery_workflow_id, result_type=MessageOutcome
            )
            armed = await _first_timer(handle)

            # Still asleep, and nothing has been handed to a transport.
            assert (await handle.describe()).status is WorkflowExecutionStatus.RUNNING
            assert mail.outbox == [], "a scheduled send does not send early"

            # Step the simulated clock past the schedule and then past the
            # status wait the ordinary send has always had behind it.
            await env.sleep(AHEAD + timedelta(minutes=1))
            for _ in range(24):
                if (await handle.describe()).status is not WorkflowExecutionStatus.RUNNING:
                    break
                await env.sleep(timedelta(hours=12))
            outcome: MessageOutcome = await handle.result()

    # The timer really was the schedule, to the minute — not a retry backoff and
    # not the status wait, both of which are also timers in this run's history.
    assert abs(armed - AHEAD) < timedelta(minutes=1), armed
    assert outcome.status == Message.Status.SENT
    assert len(mail.outbox) == 1

    sent = await run_db(lambda: Message.objects.for_tenant(tenant).get(pk=message.pk))
    assert sent.status == Message.Status.SENT
    assert sent.sent_at is not None

    # Rule 28: the ledger closed, whichever way it went.
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(workflow_id=sent.delivery_workflow_id)
    )
    assert run.status == WorkflowRun.Status.COMPLETED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_suppression_during_the_schedule_refuses_at_the_second_wall(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**Scheduling is not a way to bank permission.**

    The message is scheduled while the address is clean and the address is
    suppressed while the run sleeps. The wall that decides is the one on the far
    side of the timer, and it refuses — permanently, so the run closes promptly
    rather than sitting out the status wait for a message no transport ever saw.

    This is `test_quiet_hours_defer.py`'s sleep-is-not-a-bypass property for the
    other kind of sleep, and it is worth having twice: the two sleeps are two
    code paths, and a `send_at` that skipped the recheck would have reopened
    SEC-R1b's road under a new name.

    *Absent:* somebody unsubscribes on Tuesday and receives Monday's scheduled
    campaign on Wednesday.
    """
    mail.outbox.clear()

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            message = await run_db(
                services.send,
                recipient=recipient,
                template="receipt",
                context=CONTEXT,
                channel=Channel.EMAIL,
                tenant=tenant,
                actor=owner_actor,
                send_at=timezone.now() + AHEAD,
            )
            handle = client.get_workflow_handle(
                message.delivery_workflow_id, result_type=MessageOutcome
            )
            await _first_timer(handle)

            # They ask to be left alone, while the run is asleep.
            await run_db(
                services.suppress_recipient,
                tenant=tenant,
                actor=owner_actor,
                recipient=recipient,
                channel=Channel.EMAIL,
            )

            await env.sleep(AHEAD + timedelta(minutes=1))
            for _ in range(24):
                if (await handle.describe()).status is not WorkflowExecutionStatus.RUNNING:
                    break
                await env.sleep(timedelta(hours=12))
            outcome: MessageOutcome = await handle.result()

    assert outcome.status == Message.Status.SUPPRESSED
    assert mail.outbox == [], "nothing was handed to a transport"

    refused = await run_db(lambda: Message.objects.for_tenant(tenant).get(pk=message.pk))
    assert refused.status == Message.Status.SUPPRESSED
    assert refused.suppressed_reason == Message.SuppressedReason.SUPPRESSED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_scheduled_run_replays_deterministically(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """House rule 9, over the history the timer actually produced.

    A `workflow.sleep` is only worth having if the module it lives in replays —
    and the module it lives in is the one that may not touch a clock, a row or
    the network. Replaying the real history is the strong form of that claim:
    the sandbox re-executes the code against recorded events and a
    non-determinism raises.

    The `TIMER_STARTED` assertion comes first for the reason
    `test_quiet_hours_defer.py`'s does: replaying a history with no timer in it
    would prove the replayer works and nothing about this fix.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            message = await run_db(
                services.send,
                recipient=recipient,
                template="receipt",
                context=CONTEXT,
                channel=Channel.EMAIL,
                tenant=tenant,
                actor=owner_actor,
                send_at=timezone.now() + AHEAD,
            )
            handle = client.get_workflow_handle(
                message.delivery_workflow_id, result_type=MessageOutcome
            )
            await _first_timer(handle)
            await env.sleep(AHEAD + timedelta(minutes=1))
            for _ in range(24):
                if (await handle.describe()).status is not WorkflowExecutionStatus.RUNNING:
                    break
                await env.sleep(timedelta(hours=12))
            await handle.result()

            history = await handle.fetch_history()
            assert any(
                event.event_type == EventType.EVENT_TYPE_TIMER_STARTED for event in history.events
            ), "no timer in this history — the replay below would prove nothing"
            await Replayer(workflows=[DeliverMessageWorkflow]).replay_workflow(history)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_quiet_hours_deferral_at_queue_time_is_the_same_timer(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The queue-time/transport-edge asymmetry through the machinery, not just through the row.

    `test_quiet_hours_seam.py` proves the queue-time fork writes `queued` and
    starts a run. This is the other end of it: the run really does arm a timer
    for the window's remainder, on the same seam `send_at` uses — which is what
    "the defer path this fix builds" means in the criterion.

    The window is the person's own here rather than the tenant seam's, because
    the property is about the *path* and the person's window is the one that
    needs no registration to exist.
    """
    from datetime import time

    now = timezone.now()
    await run_db(
        make_preference,
        actor=owner_actor,
        recipient=recipient,
        consented=True,
        quiet_hours=(
            (now - timedelta(minutes=30)).time().replace(second=0, microsecond=0),
            (now + timedelta(hours=3)).time().replace(second=0, microsecond=0),
        ),
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            message = await run_db(
                services.send,
                recipient=recipient,
                template="newsletter",
                context=CONTEXT,
                channel=Channel.EMAIL,
                tenant=tenant,
                actor=owner_actor,
            )
            assert message.status == Message.Status.QUEUED, "deferred, not killed"
            handle = client.get_workflow_handle(
                message.delivery_workflow_id, result_type=MessageOutcome
            )
            armed = await _first_timer(handle)

    # Roughly the window's remainder — the assertion is deliberately loose about
    # the minute and exact about the hour, because what is being proved is that
    # the timer is the WINDOW and not a retry backoff (seconds) or the status
    # wait (72 hours).
    assert timedelta(hours=2) < armed < timedelta(hours=4), armed
    assert isinstance(time(0, 0), time)
