"""Delivery, end to end, against a real Temporal server.

`WorkflowEnvironment.start_time_skipping()` gives a real server with a skippable
clock — the real worker assembly, the real interceptors, the real activities
writing to the real database and the real Django mail path (locmem under
pytest, which is what `mail.outbox` is).

What is proved here is the part no diff shows:

* `send()` **starts the run** — on the commit, with the id the row implies, from
  the service and not from a door;
* the activity renders the versioned template, hands it to the transport, and
  the terminal activity records `sent` **through the service**, so the event is
  emitted and `Message.provider` names the transport that actually carried it;
* the `WorkflowRun` row is closed rather than left saying `running` beside an
  execution Temporal has finished (queue V6);
* a transport that refuses is an **outcome**: the run completes, the message
  says `failed`, and `comms.message.failed` is emitted;
* **the run then waits** (C2-comms-a, ADR comms-5) — and it is the wait that
  makes the status webhook land somewhere. Both exits are proved here: a
  `delivery_status` signal ends it immediately, and `STATUS_WAIT` running out
  ends it with the message still saying `sent`, because silence is not a bounce.

`transaction=True` throughout: the activities run on worker threads with their
own connections, and an `on_commit` hook only fires on a real commit.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from django.core import mail
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment

from apps.accounts.models import User
from apps.comms import providers, services
from apps.comms.models import Message, MessageTemplate, Recipient
from apps.comms.providers import Sent
from apps.comms.types import MessageOutcome
from apps.comms.workflows import STATUS_WAIT
from apps.core.actor import Actor, system_actor
from apps.core.asyncdb import run_db
from apps.core.models import Organization, Tenant
from apps.events.models import Event
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db(transaction=True)

# Enough minute-sized steps to walk past `workflows.DELIVERY_RETRY` — five
# attempts, doubling from two seconds — with room to spare. It is a ceiling
# on the loop rather than the answer: the loop stops the moment the run does.
RETRY_STEPS = 10

# Twelve-hour strides, enough of them to walk past `workflows.STATUS_WAIT`
# (seventy-two hours) even if the first few land before the wait's timer has
# been created. Same shape and same reason as `RETRY_STEPS`: a ceiling on the
# loop, not the answer — it stops the moment the run does.
WAIT_STRIDE = timedelta(hours=12)
WAIT_STEPS = 24

# How long a test will keep asking the database whether the worker has got there
# yet, before deciding it never will. Real seconds, not simulated ones: this is
# waiting for another thread, which no clock can skip.
SETTLE_TRIES = 100
SETTLE_PAUSE = 0.05


async def _advance_past_the_wait(env: WorkflowEnvironment, handle: Any) -> None:
    """Step the simulated clock until the run stops running.

    The environment skips time by itself only for a handle it returned from
    `start_workflow`; every run in this module was started by the service's
    on-commit hook, so the waiting has to be stepped through here — see the note
    in the retry test for the reason the strides are strides.
    """
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


def delivery_id(tenant: Tenant, message: Message) -> str:
    """The id `send()` will have used — derived, never remembered."""
    # The row records it — `send()` wrote it there before the run existed —
    # so a test that rebuilt the id would be a second implementation of the
    # grammar, agreeing on the day it was written.
    return message.delivery_workflow_id


async def _local_client(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> Client:
    """Point everything at the test server, including the on-commit hook.

    The hook runs in whichever thread committed, on its own event loop, and
    dials a client of its own — exactly as it does in production. Here that dial
    has to reach the test environment rather than a dev server.
    """
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> Client:
        return attach_interceptors(await Client.connect(target, namespace=namespace))

    monkeypatch.setattr(client_module, "get_client", connect)
    return attach_interceptors(env.client)


@pytest.mark.asyncio
async def test_a_send_is_delivered_and_the_row_records_the_transport(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mail.outbox.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        # The worker polls the queue the service will start the run on — the
        # deployment's own, from settings. Nothing here names a queue by hand.
        async with build_worker(client):
            message = await run_db(
                services.send,
                recipient=recipient,
                template="receipt",
                context={"name": "Ada"},
                channel="email",
                tenant=tenant,
                actor=owner_actor,
            )
            handle = client.get_workflow_handle(
                delivery_id(tenant, message), result_type=MessageOutcome
            )
            # C2-comms-a: the run no longer ends when the transport accepts it —
            # it holds open for a provider status (ADR comms-5). Nothing this
            # test asserts has changed; the clock is stepped past the deadline
            # so the run reaches the end it always reached.
            await _advance_past_the_wait(env, handle)
            outcome: MessageOutcome = await handle.result()

    assert outcome.status == Message.Status.SENT
    assert outcome.provider == "locmem"

    delivered = await run_db(lambda: Message.objects.for_tenant(tenant).get(pk=message.pk))
    assert delivered.status == Message.Status.SENT
    assert delivered.provider == "locmem"
    assert delivered.provider_message_id == f"<{message.pk}@localhost>"
    assert delivered.sent_at is not None

    # One message, actually rendered from the versioned template.
    assert len(mail.outbox) == 1
    sent = mail.outbox[0]
    assert sent.subject == "Your receipt, Ada"
    assert "here is your receipt" in sent.body
    assert sent.to == [recipient.email]
    # **A `Message-ID` is written into the mail again — and it is a
    # different string, which is the whole of the fix.** ADR comms-9 took the
    # old one out because `provider_message_id` is the key a bounce webhook
    # suppresses an address against, so a forwarded receipt carried a valid
    # weapon against its own recipient (vector (b)). That reasoning stands
    # and the second half of this assertion is it: the handle the ROW records
    # still appears nowhere in the composed message. What is on the wire is the
    # opaque delivery nonce, which is accepted by nothing —
    # `tests/test_nonce.py` drives that rather than asserting it.
    nonce = services.issue_delivery_nonce(message.pk)
    assert sent.extra_headers["Message-ID"] == f"<{nonce}@localhost>"
    assert nonce != str(message.pk)
    assert delivered.provider_message_id not in sent.message().as_string()

    assert await run_db(
        lambda: Event.objects.for_tenant(tenant).filter(name="comms.message.sent").exists()
    )
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(type="DeliverMessageWorkflow")
    )
    assert run.status == WorkflowRun.Status.COMPLETED
    assert run.finished_at is not None


# --- the wait (C2-comms-a, ADR comms-5) -----------------------------------------


@pytest.mark.asyncio
async def test_a_delivered_status_ends_the_wait_and_completes_the_run(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    receipt: MessageTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2a-1's other half: the run completes on the **signal**, not the deadline.

    The clock is never touched. If the signal did not reach the waiting run,
    this test would sit at `handle.result()` until pytest's own patience ran
    out rather than passing slowly — which is the point: nothing here can be
    satisfied by the seventy-two hours quietly elapsing.
    """
    mail.outbox.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            message = await run_db(
                services.send,
                recipient=recipient,
                template="receipt",
                context={"name": "Ada"},
                channel="email",
                tenant=tenant,
                actor=owner_actor,
            )
            handle = client.get_workflow_handle(
                delivery_id(tenant, message), result_type=MessageOutcome
            )
            sent = await _settled_at(tenant, message, Message.Status.SENT)
            # The run is genuinely waiting: it accepted the message and has not
            # ended. Asserted rather than assumed, because a run that had
            # already finished would make everything below pass for the wrong
            # reason.
            assert (await handle.describe()).status is WorkflowExecutionStatus.RUNNING

            recorded = await run_db(
                services.record_delivery_status,
                tenant=tenant,
                actor=system_actor(tenant, root_org),
                provider_message_id=sent.provider_message_id,
                status=Message.Status.DELIVERED.value,
            )
            outcome: MessageOutcome = await handle.result()

    assert recorded.status == Message.Status.DELIVERED
    assert recorded.delivered_at is not None
    # The run's own result is still what it was: the workflow reports what it
    # did, and what it did was hand the message over. `delivered` is the
    # transport's word and it lives on the row.
    assert outcome.status == Message.Status.SENT

    row = await run_db(lambda: Message.objects.for_tenant(tenant).get(pk=message.pk))
    assert row.status == Message.Status.DELIVERED
    assert row.delivered_at is not None
    assert row.bounced_at is None
    assert row.delivery_workflow_id == delivery_id(tenant, message)

    assert await run_db(
        lambda: Event.objects.for_tenant(tenant).filter(name="comms.message.delivered").exists()
    )
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(type="DeliverMessageWorkflow")
    )
    assert run.status == WorkflowRun.Status.COMPLETED
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_no_status_before_the_deadline_completes_the_run_and_leaves_it_sent(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2a-5. **Silence is not a bounce**, and it is not a hang either.

    Three days of simulated waiting, milliseconds of wall clock. The message
    ends where the product's own knowledge ends — `sent` — with no `delivered`
    and no `bounced` invented on its behalf, and the run closes rather than
    sitting open for the life of the deployment.
    """
    mail.outbox.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            message = await run_db(
                services.send,
                recipient=recipient,
                template="receipt",
                context={"name": "Ada"},
                channel="email",
                tenant=tenant,
                actor=owner_actor,
            )
            handle = client.get_workflow_handle(
                delivery_id(tenant, message), result_type=MessageOutcome
            )
            await _settled_at(tenant, message, Message.Status.SENT)
            # Still open with the message already sent: this is the wait, and
            # without this line the assertions below would also pass on a
            # workflow that never waited at all.
            assert (await handle.describe()).status is WorkflowExecutionStatus.RUNNING
            assert STATUS_WAIT == timedelta(hours=72)

            await _advance_past_the_wait(env, handle)
            outcome: MessageOutcome = await handle.result()

    assert outcome.status == Message.Status.SENT
    row = await run_db(lambda: Message.objects.for_tenant(tenant).get(pk=message.pk))
    assert row.status == Message.Status.SENT, "a provider that never reports is not a bounce"
    assert row.delivered_at is None
    assert row.bounced_at is None
    assert row.failed_at is None

    names = await run_db(
        lambda: sorted(
            Event.objects.for_tenant(tenant)
            .filter(name__in=["comms.message.delivered", "comms.message.bounced"])
            .values_list("name", flat=True)
        )
    )
    assert names == []
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(type="DeliverMessageWorkflow")
    )
    assert run.status == WorkflowRun.Status.COMPLETED


@pytest.mark.asyncio
async def test_a_status_after_the_wait_closed_lands_on_the_row_without_raising(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    receipt: MessageTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2a-4. A **late** status is recorded; only the wake-up is skipped.

    The run has been closed by its own deadline before the provider reports.
    `signal_workflow` refuses a finished run — correctly — and
    `record_delivery_status` treats that refusal as the ordinary end of the
    story rather than as a failure, because the row and the event are what the
    product actually promised. A 500 here would be a status webhook the ESP
    retries for ever against a run that is never coming back.
    """
    mail.outbox.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            message = await run_db(
                services.send,
                recipient=recipient,
                template="receipt",
                context={"name": "Ada"},
                channel="email",
                tenant=tenant,
                actor=owner_actor,
            )
            handle = client.get_workflow_handle(
                delivery_id(tenant, message), result_type=MessageOutcome
            )
            sent = await _settled_at(tenant, message, Message.Status.SENT)
            await _advance_past_the_wait(env, handle)
            await handle.result()
            closed = await run_db(
                lambda: WorkflowRun.objects.for_tenant(tenant).get(type="DeliverMessageWorkflow")
            )
            assert closed.status == WorkflowRun.Status.COMPLETED

            # Now the provider finally speaks. No exception, and the row moves.
            recorded = await run_db(
                services.record_delivery_status,
                tenant=tenant,
                actor=system_actor(tenant, root_org),
                provider_message_id=sent.provider_message_id,
                status=Message.Status.BOUNCED.value,
                detail="550 mailbox unavailable",
            )

    assert recorded.status == Message.Status.BOUNCED
    assert recorded.bounced_at is not None
    assert "550 mailbox unavailable" in recorded.error
    assert await run_db(
        lambda: Event.objects.for_tenant(tenant).filter(name="comms.message.bounced").exists()
    )


@pytest.mark.asyncio
async def test_a_transport_that_never_accepts_ends_as_a_failed_message_not_a_failed_run(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The attempts are spent. That is an outcome the product records, not a fault.

    The retry policy is bounded (five attempts), which is what makes this test
    finish rather than hang: an unbounded default would retry until the
    schedule-to-close deadline, and a workflow that retried forever would be a
    worker somewhere still trying at midnight.
    """

    class RefusingChannel:
        slug = "email"

        def send(self, *, message: Message, subject: str, body: str, nonce: str = "") -> Sent:
            raise RuntimeError("the mail host said no")

    monkeypatch.setitem(providers._channels, "email", RefusingChannel())
    mail.outbox.clear()

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            message = await run_db(
                services.send,
                recipient=recipient,
                template="receipt",
                context={"name": "Ada"},
                channel="email",
                tenant=tenant,
                actor=owner_actor,
            )
            handle = client.get_workflow_handle(
                delivery_id(tenant, message), result_type=MessageOutcome
            )
            # The environment skips time by itself only for a handle it returned
            # from `start_workflow`; this run was started by the service's
            # on-commit hook, so the retry backoff is stepped through here.
            # Minute-sized steps rather than one leap, because each retry timer
            # is created a moment after the previous attempt failed and a single
            # jump could land before the next one exists.
            for _ in range(RETRY_STEPS):
                if (await handle.describe()).status is not WorkflowExecutionStatus.RUNNING:
                    break
                await env.sleep(timedelta(minutes=1))
            outcome: MessageOutcome = await handle.result()

    assert outcome.status == Message.Status.FAILED
    failed = await run_db(lambda: Message.objects.for_tenant(tenant).get(pk=message.pk))
    assert failed.status == Message.Status.FAILED
    assert "the mail host said no" in failed.error
    assert failed.failed_at is not None
    assert mail.outbox == []

    assert await run_db(
        lambda: Event.objects.for_tenant(tenant).filter(name="comms.message.failed").exists()
    )
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(type="DeliverMessageWorkflow")
    )
    assert run.status == WorkflowRun.Status.COMPLETED


@pytest.mark.asyncio
async def test_a_suppressed_send_starts_no_delivery_run_and_sends_nothing(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
    monkeypatch: pytest.MonkeyPatch,
    recorded_workflow_starts: Any,
) -> None:
    """The consent refusal, proved where a commit is real and a hook would fire."""
    mail.outbox.clear()
    message = await run_db(
        services.send,
        recipient=recipient,
        template="newsletter",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    assert message.status == Message.Status.SUPPRESSED
    assert not await run_db(
        lambda: (
            WorkflowRun.objects.for_tenant(tenant).filter(type="DeliverMessageWorkflow").exists()
        )
    )
    assert mail.outbox == []
