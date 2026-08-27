"""The delivery nonce: **a re-send is a NEW run, a retry is the SAME run.**

ADR comms-9 deferred a per-message nonce id and named its own trigger; that is
the trigger firing, because comms-10 widened the window comms-9
had measured:

* comms-9 took the minted `Message-ID` out of the mail, because
  `provider_message_id` is the key `record_delivery_status` accepts a bounce
  against — so printing it into every message handed the recipient, and anybody
  they forwarded to, a valid suppression key for themselves (vector (b)).
  The stated cost was that a crash between handing a message to a transport and
  recording that we did produces two messages a provider cannot tell apart;
* comms-10 then wrote a `sending` row back to `queued` and slept up to a day, so
  "a crash" became "a day". **Each half was declared where it was made; the
  interaction was not.**

The way out is a **second** identifier that is not the first, and every test
here is one property of it:

* it is **derived**, so a retry computes the same value and rule 18's "never a
  random value" holds for the id it rides in;
* it is **per message**, so two sends are two identifiers and the person gets
  the two copies they were meant to get;
* it is **not a suppression key** — and that is not a claim, it is
  `test_the_nonce_suppresses_nobody`, which takes the string off the wire and
  tries to use it as one.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core import mail

from apps.comms import providers, services
from apps.comms.models import Channel, Message, MessageTemplate, Recipient
from apps.comms.services import NONCE_SEPARATOR, issue_delivery_nonce
from apps.core.actor import Actor, system_actor
from apps.core.exceptions import NotFound
from apps.core.models import Tenant
from apps.core.services import root_organization
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db

CONTEXT: dict[str, Any] = {"name": "Ada"}


def _send(*, tenant: Tenant, actor: Actor, recipient: Recipient) -> Message:
    return services.send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=actor,
    )


# --- the value itself ------------------------------------------------------------


def test_the_nonce_is_derived_and_therefore_repeatable() -> None:
    """Rule 18's "never a random value", at the one place it could have been one.

    The nonce rides in a workflow id, and a workflow id that is not repeatable
    cannot dedupe a retry — which is the whole job. Computed twice from one row,
    it is one string.

    *Absent:* `uuid4()`, every retry starts a second run, and the id grammar's
    determinism clause is decoration.
    """
    assert issue_delivery_nonce("01a03000-0000-7000-8000-000000000001") == issue_delivery_nonce(
        "01a03000-0000-7000-8000-000000000001"
    )
    assert issue_delivery_nonce("a") != issue_delivery_nonce("b")
    assert len(issue_delivery_nonce("a")) == 32
    assert issue_delivery_nonce("a").isalnum()


def test_the_nonce_is_not_the_primary_key(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """One-way, so that publishing it is not publishing the row's identifier.

    A digest with the pk recoverable from it would be the pk with extra steps,
    and comms-9's whole argument was about what publishing the pk-derived handle
    costs.
    """
    message = _send(tenant=tenant, actor=owner_actor, recipient=recipient)
    nonce = issue_delivery_nonce(message.pk)

    assert nonce != str(message.pk)
    assert str(message.pk) not in nonce
    assert str(message.pk).replace("-", "") not in nonce


# --- the two directions ----------------------------------------------------------


def test_a_retry_is_the_same_run(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """The same message, asked for twice, is one run — because the id is repeatable.

    This is the half that makes at-least-once safe: `start_workflow_on_commit`
    is registered on a transaction that may be retried, and Temporal's own
    de-duplication is keyed on the id. Built twice from one row, it is the same
    string, so the second start joins the first run instead of opening a second.

    *Absent:* a retried service call sends the person two copies and the ledger
    shows two runs for one message.
    """
    message = _send(tenant=tenant, actor=owner_actor, recipient=recipient)

    # The nonce is what makes the id repeatable, so it is the thing computed
    # twice here — the id itself is built once, at `send()`'s call site, where
    # house rule 18 can see `workflow_id(...)` for what it is. A test that
    # rebuilt the id would be a second implementation of the grammar, agreeing
    # with the first on the day it was written.
    assert issue_delivery_nonce(message.pk) == issue_delivery_nonce(message.pk)
    assert message.delivery_workflow_id.endswith(
        f"{NONCE_SEPARATOR}{issue_delivery_nonce(message.pk)}"
    )
    assert (
        WorkflowRun.objects.for_tenant(tenant)
        .filter(workflow_id=message.delivery_workflow_id)
        .count()
        == 1
    )


def test_a_re_send_is_a_new_run(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """Two deliberate sends are two runs, two nonces and two copies.

    The other half, and the one that must NOT be deduped: a person who is sent
    the same receipt twice on purpose received two messages, and a provider that
    collapsed them would be swallowing one the product meant to deliver.

    *Absent:* a nonce keyed on something the two sends share — the recipient,
    the template, the day — and the second copy silently never arrives.
    """
    first = _send(tenant=tenant, actor=owner_actor, recipient=recipient)
    second = _send(tenant=tenant, actor=owner_actor, recipient=recipient)

    assert first.pk != second.pk
    assert issue_delivery_nonce(first.pk) != issue_delivery_nonce(second.pk)
    assert first.delivery_workflow_id != second.delivery_workflow_id
    # Filtered by type, because the spine starts its own runs: an `emit()` on
    # each send opens a `DispatchEventWorkflow`, and counting every run in the
    # tenant would be counting those too.
    delivery_runs = WorkflowRun.objects.for_tenant(tenant).filter(type="DeliverMessageWorkflow")
    assert delivery_runs.count() == 2
    assert set(delivery_runs.values_list("workflow_id", flat=True)) == {
        first.delivery_workflow_id,
        second.delivery_workflow_id,
    }


def test_the_run_id_carries_both_facts_in_the_house_grammar(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """`<tenant>:<app>:<noun>:<pk>.<nonce>` — four segments, and a key with two halves.

    The separator is a full stop and **not** a colon, and that is not taste:
    `workflows.workflow_id` refuses a key containing the id separator, because
    the four-segment grammar is what a human reads in the Temporal UI and what a
    prefix search for a tenant's runs depends on. A fifth segment smuggled into
    `key` would break both.

    *Absent:* the id says which message and not which delivery of it, and the
    distinction this whole module is about has nowhere to live.
    """
    message = _send(tenant=tenant, actor=owner_actor, recipient=recipient)
    run_id = message.delivery_workflow_id

    assert run_id.count(":") == 3, run_id
    tenant_slug, app, noun, key = run_id.split(":")
    assert (tenant_slug, app, noun) == (tenant.slug, "comms", "message")
    assert key == f"{message.pk}{NONCE_SEPARATOR}{issue_delivery_nonce(message.pk)}"


# --- what the transport is told --------------------------------------------------


def test_the_transport_is_told_the_nonce_and_stamps_it(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """The header is back on the wire, and it is the nonce.

    Two attempts of one delivery — which is what a crashed worker produces —
    carry ONE identifier, so a provider that honours `Message-ID` can collapse
    them. That is the dedup comms-9 wrote down as the cost of taking the old
    header out.

    *Absent:* Django stamps its own random `Message-ID` per send and the two
    mails are, to the provider, two different messages.
    """
    message = _send(tenant=tenant, actor=owner_actor, recipient=recipient)
    nonce = issue_delivery_nonce(message.pk)
    mail.outbox.clear()

    for _ in range(2):
        providers.get_channel(Channel.EMAIL.value).send(
            message=message, subject="Receipt", body="Thanks.", nonce=nonce
        )

    assert len(mail.outbox) == 2
    stamped = {one.extra_headers.get("Message-ID") for one in mail.outbox}
    assert stamped == {f"<{nonce}@localhost>"}, "one identifier for two attempts"


def test_two_sends_are_stamped_differently(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """And the other direction, on the wire this time."""
    first = _send(tenant=tenant, actor=owner_actor, recipient=recipient)
    second = _send(tenant=tenant, actor=owner_actor, recipient=recipient)
    mail.outbox.clear()

    for message in (first, second):
        providers.get_channel(Channel.EMAIL.value).send(
            message=message,
            subject="Receipt",
            body="Thanks.",
            nonce=issue_delivery_nonce(message.pk),
        )

    stamped = {one.extra_headers.get("Message-ID") for one in mail.outbox}
    assert len(stamped) == 2, "two sends, two identifiers"


def test_no_nonce_stamps_no_header(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """The default is the behaviour every caller had before this parameter existed.

    A `DeliverMessage` payload written before this fix deserialises with an
    empty nonce, and an empty nonce stamps nothing — so a run already in flight
    when this shipped replays into exactly what it was doing.
    """
    message = _send(tenant=tenant, actor=owner_actor, recipient=recipient)
    mail.outbox.clear()

    providers.get_channel(Channel.EMAIL.value).send(
        message=message, subject="Receipt", body="Thanks."
    )

    assert "Message-ID" not in mail.outbox[0].extra_headers


# --- and the thing that makes putting it on the wire safe ------------------------


def test_the_nonce_suppresses_nobody(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """**The suppression risk stays closed.** The string on the wire is a weapon against nobody.

    This is the test that earns the header. comms-9's argument for removing it
    was that `provider_message_id` is the key `record_delivery_status` joins a
    bounce on, so a forwarded message carried a valid suppression key for its
    own recipient. The nonce is a different string and is accepted by nothing —
    and a claim that a published value is harmless is worth exactly as much as
    the test that takes it off the wire and tries to use it.

    *Absent:* the header is back and so is the vector, under a new name.
    """
    message = _send(tenant=tenant, actor=owner_actor, recipient=recipient)
    sent = services.record_message_sent(
        tenant=tenant,
        actor=owner_actor,
        message=message,
        provider="locmem",
        provider_message_id=f"<{message.pk}@localhost>",
    )
    nonce = issue_delivery_nonce(message.pk)
    system = system_actor(tenant, root_organization(tenant=tenant))

    # The recipient forwards the mail, reads the header, and posts it as a bounce.
    with pytest.raises(NotFound):
        services.record_delivery_status(
            tenant=tenant,
            actor=system,
            provider_message_id=nonce,
            status=Message.Status.BOUNCED.value,
            detail="550 no such mailbox",
        )
    with pytest.raises(NotFound):
        services.record_delivery_status(
            tenant=tenant,
            actor=system,
            provider_message_id=f"<{nonce}@localhost>",
            status=Message.Status.BOUNCED.value,
            detail="550 no such mailbox",
        )

    # Nothing moved, and nobody was silenced.
    settled = Message.objects.for_tenant(tenant).get(pk=sent.pk)
    assert settled.status == Message.Status.SENT
    assert settled.bounced_at is None
    from apps.comms.models import ChannelPreference

    assert (
        not ChannelPreference.objects.for_tenant(tenant)
        .filter(recipient=recipient, suppressed_at__isnull=False)
        .exists()
    )


def test_the_real_handle_still_is_a_suppression_key(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """The control, without which the test above passes on a door that refuses everybody.

    The row's own `provider_message_id` still bounces the message and still
    suppresses the address — which is exactly why comms-9 keeps it out of the
    mail, and exactly why the nonce had to be a second string rather than the
    first one re-published.
    """
    from apps.comms.models import ChannelPreference

    message = _send(tenant=tenant, actor=owner_actor, recipient=recipient)
    handle = f"<{message.pk}@localhost>"
    services.record_message_sent(
        tenant=tenant,
        actor=owner_actor,
        message=message,
        provider="locmem",
        provider_message_id=handle,
    )

    services.record_delivery_status(
        tenant=tenant,
        actor=system_actor(tenant, root_organization(tenant=tenant)),
        provider_message_id=handle,
        status=Message.Status.BOUNCED.value,
        detail="550 no such mailbox",
    )

    bounced = Message.objects.for_tenant(tenant).get(pk=message.pk)
    assert bounced.status == Message.Status.BOUNCED
    assert (
        ChannelPreference.objects.for_tenant(tenant)
        .filter(recipient=recipient, suppressed_at__isnull=False)
        .exists()
    )
