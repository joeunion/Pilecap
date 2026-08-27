"""The walk: one run, several messages, and the four ways a chain ends.

Against a real Temporal server with a skippable clock — the real worker
assembly, the real interceptors, the real activities writing to the real
database, the real Django mail path (locmem, which is `mail.outbox`) and the
real fake-SMS transport. Nothing here is a decision-logic test with stubbed
activities: the property worth proving is that a policy row becomes two
messages, in order, with the waits in between, and that is a property of the
whole assembly.

Five things are proved and each is a different way for the feature to be wrong:

* **one run, two messages** — a run per step would be a chain nothing could
  stop, so the id is asserted to be a single one and both rows are asserted to
  point at it;
* **delivered stops the chain** — the person answered the text, so the email
  must not go. This is the feature inverted if it fails, not merely reduced;
* **the snapshot holds** — a policy revised mid-wait does not reach into the run
  already interpreting it (rule 9, and the reason `PolicyStep` exists);
* **consent is re-checked per step** (ADR comms-7) — somebody who suppresses a
  channel between the text and the email does not get the email;
* **silence escalates** — no delivery status inside the wait means the next rung
  is tried, which is the whole point of an escalation.

`transaction=True` throughout: the activities run on worker threads with their
own connections, and an `on_commit` hook only fires on a real commit.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import timedelta
from typing import Any

import pytest
from django.core import mail
from django.test import Client
from temporalio.client import Client as TemporalClient
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment

from apps.accounts.models import User
from apps.comms import providers, services
from apps.comms.models import Channel, Message, Recipient
from apps.comms.tests.conftest import make_template
from apps.comms.types import MessageOutcome
from apps.connections.api import SIGNATURE_HEADER, SIGNATURE_PREFIX
from apps.connections.services import create_connection
from apps.core.actor import Actor, system_actor
from apps.core.asyncdb import run_db
from apps.core.audit import AuditEntry
from apps.core.models import Organization, Tenant
from apps.core.services import root_organization
from apps.events.models import Event
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db(transaction=True)

#: How long step 1 holds the run open for an SMS delivery status. Ten minutes of
#: simulated time, milliseconds of wall clock.
STEP_ONE_WAIT = 600

#: Strides big enough to walk past `STEP_ONE_WAIT`, and enough of them to still
#: get there if the first few land before the wait's timer exists. Same shape and
#: reason as `test_workflows.RETRY_STEPS`.
WAIT_STRIDE = timedelta(seconds=120)
WAIT_STEPS = 20

SETTLE_TRIES = 200
SETTLE_PAUSE = 0.05

#: The secret the SMS provider's status webhooks are signed with.
SMS_SECRET = "the-sms-provider-shares-this"  # pragma: allowlist secret


def delivery_id(tenant: Tenant, message: Message) -> str:
    """The id `send()` will have used for the whole escalation — derived, never remembered."""
    # The row records it — `send()` wrote it there before the run existed —
    # so a test that rebuilt the id would be a second implementation of the
    # grammar, agreeing on the day it was written.
    return message.delivery_workflow_id


async def _local_client(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> TemporalClient:
    """Point everything at the test server, including the on-commit hooks."""
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> TemporalClient:
        return attach_interceptors(await TemporalClient.connect(target, namespace=namespace))

    monkeypatch.setattr(client_module, "get_client", connect)
    return attach_interceptors(env.client)


async def _messages(tenant: Tenant) -> list[Message]:
    """Every message this tenant has, oldest first — the escalation in order."""
    return await run_db(
        lambda: list(Message.objects.for_tenant(tenant).order_by("created_at").all())
    )


async def _settled(tenant: Tenant, message: Message, status: str) -> Message:
    """The row, once the worker has moved it to `status`. Asserts if it never does."""
    row = message
    for _ in range(SETTLE_TRIES):
        row = await run_db(lambda: Message.objects.for_tenant(tenant).get(pk=message.pk))
        if row.status == status:
            return row
        await asyncio.sleep(SETTLE_PAUSE)
    raise AssertionError(f"message stayed {row.status!r}, never reached {status!r}")


async def _advance(env: WorkflowEnvironment, handle: Any, stride: timedelta = WAIT_STRIDE) -> None:
    """Step the simulated clock until the run stops running.

    Strides rather than one leap, and the same reason `test_workflows` gives:
    each wait's timer is created a moment after the step before it finished, so
    a single jump could land before the timer this test is trying to expire
    exists. The default stride walks a policy step; a no-policy send waits
    `STATUS_WAIT`, which is three days, and passes its own.
    """
    for _ in range(WAIT_STEPS):
        if (await handle.describe()).status is not WorkflowExecutionStatus.RUNNING:
            return
        await env.sleep(stride)


@pytest.fixture
def escalation(tenant: Tenant, owner_actor: Actor, recipient: Recipient) -> Recipient:
    """A recipient with a phone, and the two-step policy that reaches them.

    Text them, wait ten minutes for a delivery status, and email them if none
    arrived. The `escalate_when="delivered"` on step 1 is the whole instruction:
    *go on unless the transport says this one landed*.
    """
    make_template(actor=owner_actor)
    make_template(
        actor=owner_actor,
        name="texted",
        channel=Channel.SMS,
        subject="",
        body="Hello {{ name }}, please look at your account.",
    )
    services.create_policy(
        tenant=tenant,
        actor=owner_actor,
        name="oncall",
        steps=[
            {
                "channel": "sms",
                "template": "texted",
                "wait_seconds": STEP_ONE_WAIT,
                "escalate_when": "delivered",
            },
            {
                "channel": "email",
                "template": "receipt",
                "wait_seconds": 0,
                "escalate_when": "none",
            },
        ],
    )
    services.update_recipient(
        tenant=tenant, actor=owner_actor, recipient=recipient, phone="+15550001111"
    )
    recipient.refresh_from_db()
    return recipient


def _send(tenant: Tenant, actor: Actor, recipient: Recipient) -> Message:
    return services.send(
        recipient=recipient,
        context={"name": "Ada"},
        tenant=tenant,
        actor=actor,
        policy="oncall",
    )


# --- C2b-3: the headline ----------------------------------------------------------


@pytest.mark.asyncio
async def test_no_delivery_status_escalates_from_the_text_to_the_email(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    escalation: Recipient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2b-3. **One run, two messages, in order, with the wait in between.**

    Absent, this is either no second message — an escalation that does not
    escalate — or a run per step, which is a chain nothing can stop. Both are
    asserted against, and the single `WorkflowRun` row is the one that would
    catch the second.
    """
    mail.outbox.clear()
    providers.fake_sms_outbox.clear()

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            first = await run_db(_send, tenant, owner_actor, escalation)
            handle = client.get_workflow_handle(
                delivery_id(tenant, first), result_type=MessageOutcome
            )
            sent = await _settled(tenant, first, Message.Status.SENT)
            assert sent.channel == "sms"
            assert sent.provider == "fake-sms", "the fake carried it; no vendor, no account"
            # The run is waiting on the text, not finished. Without this the
            # assertions below would also pass on a run that never waited.
            assert (await handle.describe()).status is WorkflowExecutionStatus.RUNNING
            assert mail.outbox == [], "the email is step 2 and it is not step 2 yet"

            await _advance(env, handle)
            await handle.result()

    rows = await _messages(tenant)
    assert [(row.channel, row.policy_step) for row in rows] == [("sms", 1), ("email", 2)]
    assert {row.policy_name for row in rows} == {"oncall"}
    assert {row.policy_version for row in rows} == {1}
    assert rows[1].status == Message.Status.SENT

    # One conversation, not two unrelated messages that share a recipient.
    assert len({row.correlation_id for row in rows}) == 1
    assert rows[0].correlation_id == rows[1].correlation_id

    # ONE run, and both messages point at it.
    runs = await run_db(
        lambda: list(WorkflowRun.objects.for_tenant(tenant).filter(type="DeliverMessageWorkflow"))
    )
    assert len(runs) == 1, "a run per step would be a chain nothing could stop"
    assert runs[0].status == WorkflowRun.Status.COMPLETED
    assert {row.delivery_workflow_id for row in rows} == {runs[0].workflow_id}

    # The two transports actually carried them.
    assert len(providers.fake_sms_outbox) == 1
    assert providers.fake_sms_outbox[0].to == "+15550001111"
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Your receipt, Ada"


@pytest.mark.asyncio
async def test_the_escalated_step_is_audited_as_the_system_acting_from_a_workflow(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    escalation: Recipient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2b-9. Nobody clicked step 2, and the audit row says so rather than guessing.

    Attributing an escalation ten minutes later to whoever pressed send would
    make the audit trail read plausibly and be false.
    """
    mail.outbox.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            first = await run_db(_send, tenant, owner_actor, escalation)
            handle = client.get_workflow_handle(
                delivery_id(tenant, first), result_type=MessageOutcome
            )
            await _settled(tenant, first, Message.Status.SENT)
            await _advance(env, handle)
            await handle.result()

    audited = await run_db(
        lambda: list(AuditEntry.objects.filter(action="comms.send_step").order_by("created_at"))
    )
    assert len(audited) == 1, "one later step, one audit row"
    assert audited[0].door == "workflow"
    assert audited[0].actor_kind == "system"
    assert audited[0].actor_user_id is None
    assert audited[0].outcome == "ok"


# --- C2b-4: delivered stops the chain ---------------------------------------------


@pytest.mark.asyncio
async def test_a_delivered_status_on_the_text_means_the_email_never_goes(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    escalation: Recipient,
    root_org: Organization,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2b-4. **The person answered. Do not keep chasing them.**

    Absent, the feature is inverted: somebody who read the text still gets the
    email, which is worse than not having escalation at all. The status arrives
    through the real signed webhook door, against a `comms-sms` connection, so
    what is proved is the whole path — HMAC, receiver, registry, adapter,
    service, signal — and not just the service.

    The clock is stepped afterwards to show the run had really *stopped*: if the
    chain had merely been slow, `_advance` would have produced step 2.
    """
    mail.outbox.clear()
    providers.fake_sms_outbox.clear()

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            connection = await run_db(
                create_connection,
                tenant=tenant,
                actor=owner_actor,
                provider="comms-sms",
                name="Texts",
                credentials={"webhook_secret": SMS_SECRET},
            )
            first = await run_db(_send, tenant, owner_actor, escalation)
            handle = client.get_workflow_handle(
                delivery_id(tenant, first), result_type=MessageOutcome
            )
            sent = await _settled(tenant, first, Message.Status.SENT)

            payload = json.dumps(
                {"event_type": "delivered", "message_id": sent.provider_message_id}
            ).encode()
            signature = (
                SIGNATURE_PREFIX
                + hmac.new(SMS_SECRET.encode(), payload, hashlib.sha256).hexdigest()
            )

            def post() -> int:
                response = Client().post(
                    f"/api/v1/connections/{connection.pk}/webhook/",
                    data=payload,
                    content_type="application/json",
                    headers={SIGNATURE_HEADER: signature},
                )
                return int(response.status_code)

            assert await run_db(post) == 202
            await _advance(env, handle)
            await handle.result()

    rows = await _messages(tenant)
    assert len(rows) == 1, "the person answered the text; the email is not sent"
    assert rows[0].status == Message.Status.DELIVERED
    assert mail.outbox == []
    assert await run_db(
        lambda: Event.objects.for_tenant(tenant).filter(name="comms.message.delivered").exists()
    )
    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(type="DeliverMessageWorkflow")
    )
    assert run.status == WorkflowRun.Status.COMPLETED


# --- C2b-5: the snapshot ----------------------------------------------------------


@pytest.mark.asyncio
async def test_revising_the_policy_mid_wait_does_not_reach_into_the_running_escalation(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    escalation: Recipient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2b-5. **v2 does not leak into a history that was written under v1.**

    The run is holding step 1's wait when the policy is revised to a v2 whose
    second step is a *different template*. The run finishes v1: step 2 is the
    `receipt` email v1 named, and the row records `policy_version=1`. That is
    house rule 9 doing the work it exists for — a workflow that re-read the row
    would be a workflow whose history no longer explains its own decisions.
    """
    mail.outbox.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            await run_db(
                make_template,
                actor=owner_actor,
                name="different",
                subject="A different subject for {{ name }}",
                body="This is v2's template and it must not be used by a v1 run.",
            )
            first = await run_db(_send, tenant, owner_actor, escalation)
            handle = client.get_workflow_handle(
                delivery_id(tenant, first), result_type=MessageOutcome
            )
            await _settled(tenant, first, Message.Status.SENT)
            assert (await handle.describe()).status is WorkflowExecutionStatus.RUNNING

            revised = await run_db(
                services.revise_policy,
                tenant=tenant,
                actor=owner_actor,
                name="oncall",
                steps=[
                    {
                        "channel": "sms",
                        "template": "texted",
                        "wait_seconds": STEP_ONE_WAIT,
                        "escalate_when": "delivered",
                    },
                    {
                        "channel": "email",
                        "template": "different",
                        "wait_seconds": 0,
                        "escalate_when": "none",
                    },
                ],
            )
            assert revised.version == 2

            await _advance(env, handle)
            await handle.result()

    rows = await _messages(tenant)
    assert len(rows) == 2
    second = rows[1]
    assert second.template_name == "receipt", "the run finished the plan it was given"
    assert second.policy_version == 1
    assert mail.outbox[-1].subject == "Your receipt, Ada"


# --- C2b-6: consent, per step -----------------------------------------------------


@pytest.mark.asyncio
async def test_suppressing_the_channel_between_the_steps_stops_the_second_message(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    escalation: Recipient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2b-6, ADR comms-7. **The wall stands at each step's own send time.**

    Somebody asks to be left alone on email while the escalation is mid-wait.
    Step 2 must be a `suppressed` row with a reason and an event — not a
    silence, and certainly not an email. A snapshot taken when the policy was
    entered would have sent it, which is exactly the design that was rejected.

    Suppression rather than a marketing revocation because step 2's template is
    **transactional**: consent is not what stands in front of a receipt, and
    `suppressed_at` is. Picking the lever that actually applies is the point —
    a test that revoked marketing consent here would pass without proving
    anything.
    """
    mail.outbox.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            first = await run_db(_send, tenant, owner_actor, escalation)
            handle = client.get_workflow_handle(
                delivery_id(tenant, first), result_type=MessageOutcome
            )
            await _settled(tenant, first, Message.Status.SENT)

            await run_db(
                services.suppress_recipient,
                tenant=tenant,
                actor=owner_actor,
                recipient=escalation,
                channel=Channel.EMAIL,
            )

            await _advance(env, handle)
            await handle.result()

    rows = await _messages(tenant)
    assert len(rows) == 2, "the refusal is a row, not a silence"
    second = rows[1]
    assert second.channel == "email"
    assert second.policy_step == 2
    assert second.status == Message.Status.SUPPRESSED
    assert second.suppressed_reason == Message.SuppressedReason.SUPPRESSED
    assert mail.outbox == [], "the person asked to be left alone"

    suppressed = await run_db(
        lambda: list(
            Event.objects.for_tenant(tenant)
            .filter(name="comms.message.suppressed")
            .values_list("payload", flat=True)
        )
    )
    assert [str(payload["id"]) for payload in suppressed] == [str(second.pk)]

    run = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).get(type="DeliverMessageWorkflow")
    )
    assert run.status == WorkflowRun.Status.COMPLETED, "refused cleanly, not failed"


@pytest.mark.asyncio
async def test_a_suppressed_first_step_escalates_immediately_without_waiting(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    escalation: Recipient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR comms-7's other half: nothing went out, so there is nothing to wait for.

    The clock is **never touched** in this test, and that is the assertion. If a
    suppressed step still waited its ten minutes, `handle.result()` would hang
    rather than the test failing on a value — so this passing at all is the
    proof that the wait was skipped.
    """
    mail.outbox.clear()
    await run_db(
        services.suppress_recipient,
        tenant=tenant,
        actor=owner_actor,
        recipient=escalation,
        channel=Channel.SMS,
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            first = await run_db(_send, tenant, owner_actor, escalation)
            assert first.status == Message.Status.SUPPRESSED
            handle = client.get_workflow_handle(
                delivery_id(tenant, first), result_type=MessageOutcome
            )
            await handle.result()

    rows = await _messages(tenant)
    assert [(row.channel, row.status) for row in rows] == [
        ("sms", Message.Status.SUPPRESSED),
        ("email", Message.Status.SENT),
    ]
    assert len(mail.outbox) == 1, "the text was refused; the email is the whole point"


# --- C2b-7: the no-policy send is what it always was ------------------------------


@pytest.mark.asyncio
async def test_a_send_with_no_policy_is_one_message_and_one_run_exactly_as_before(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    escalation: Recipient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C2b-7. The path that did not change, driven the way it was before.

    One message, one run, delivered by email, the three policy columns empty,
    and the run holding open for `STATUS_WAIT` afterwards — comms-a's behaviour,
    reached now through the general interpreter rather than preserved as a
    special case beside it.
    """
    mail.outbox.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            message = await run_db(
                services.send,
                recipient=escalation,
                template="receipt",
                context={"name": "Ada"},
                channel="email",
                tenant=tenant,
                actor=owner_actor,
            )
            handle = client.get_workflow_handle(
                delivery_id(tenant, message), result_type=MessageOutcome
            )
            await _settled(tenant, message, Message.Status.SENT)
            assert (await handle.describe()).status is WorkflowExecutionStatus.RUNNING
            # Three days, not ten minutes: with no policy the implicit step is
            # comms-a's `STATUS_WAIT`, which is exactly the point of this test.
            await _advance(env, handle, stride=timedelta(hours=12))
            outcome: MessageOutcome = await handle.result()

    assert outcome.status == Message.Status.SENT
    rows = await _messages(tenant)
    assert len(rows) == 1
    assert (rows[0].policy_name, rows[0].policy_version, rows[0].policy_step) == ("", None, None)
    assert len(mail.outbox) == 1
    runs = await run_db(
        lambda: list(WorkflowRun.objects.for_tenant(tenant).filter(type="DeliverMessageWorkflow"))
    )
    assert len(runs) == 1
    assert runs[0].status == WorkflowRun.Status.COMPLETED


# --- the SMS status door, in its own right ----------------------------------------


@pytest.mark.asyncio
async def test_a_status_webhook_on_the_sms_connection_reads_with_the_sms_adapter(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    escalation: Recipient,
    root_org: Organization,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`STATUS_PROVIDERS`, not a hard-coded email adapter.

    comms-a resolved every inbound status with `EmailChannel`, which was right
    while email was the only kind that could report and is a bug the moment SMS
    can. The connection's provider slug is what picks the adapter now, and this
    is the test that would have failed before the change.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            first = await run_db(_send, tenant, owner_actor, escalation)
            handle = client.get_workflow_handle(
                delivery_id(tenant, first), result_type=MessageOutcome
            )
            sent = await _settled(tenant, first, Message.Status.SENT)
            hat = await run_db(root_organization, tenant=tenant)
            recorded = await run_db(
                services.record_delivery_status,
                tenant=tenant,
                actor=system_actor(tenant, hat),
                provider_message_id=sent.provider_message_id,
                status=Message.Status.BOUNCED.value,
                detail="the number is not in service",
            )
            await _advance(env, handle)
            await handle.result()

    assert recorded.status == Message.Status.BOUNCED
    assert recorded.channel == "sms"
    assert "not in service" in recorded.error
    rows = await _messages(tenant)
    # A bounce is not a delivery, so the chain still escalates — which is the
    # right answer: the text did not reach them, so try the email.
    assert [(row.channel, row.policy_step) for row in rows] == [("sms", 1), ("email", 2)]
