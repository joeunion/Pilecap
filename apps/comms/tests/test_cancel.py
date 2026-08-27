"""Cancelling a message, and the two refusals that make it safe.

The second half of that visibility. `send_at` made a scheduled send visible; this is what
somebody does about it once they can see it — and without it the only way to
stop a send scheduled for Monday was the Temporal UI, which is not a product
surface and is not open to whoever is on support.

Three claims:

* **only a message no transport has seen** can be cancelled (`CANCELLABLE` is
  `{queued}`). `sending` means an activity is inside a gateway at this moment,
  and a row marked cancelled while the gateway accepted it would be a message
  the person receives beside a log that says it was stopped — a worse lie than
  the invisibility this closes;
* **`cancelled` is its own status**, not a `SuppressedReason`. `suppressed` is
  the product refusing on the RECIPIENT's behalf; this is the SENDER changing
  their mind, and a campaign report counting these among the opt-outs would be
  inventing consent news;
* **the row decides, not the run.** The cancel goes to Temporal on
  `on_commit(..., robust=True)`, so a cancel that never reaches the server
  leaves a run that wakes, re-reads the row, finds a status outside `SENDABLE`
  and hands nothing to any transport. That belt is what makes the ordering safe
  and it is driven here rather than argued.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.comms import services
from apps.comms.models import Channel, Message, MessageTemplate, Recipient
from apps.comms.services import CANCELLABLE
from apps.core.actor import Actor
from apps.core.exceptions import Conflict, NotFound
from apps.core.models import Tenant
from apps.events.models import Event

pytestmark = pytest.mark.django_db

CONTEXT: dict[str, Any] = {"name": "Ada"}
JSON = "application/json"


def _scheduled(*, tenant: Tenant, actor: Actor, recipient: Recipient) -> Message:
    return services.send(
        recipient=recipient,
        template="receipt",
        context=CONTEXT,
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=actor,
        send_at=timezone.now() + timedelta(hours=6),
    )


def test_the_cancellable_population_is_only_queued() -> None:
    """Named once, asserted here, so widening it is a diff a reviewer reads."""
    assert CANCELLABLE == frozenset({Message.Status.QUEUED.value})


def test_a_scheduled_message_can_be_taken_back(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> None:
    """The verb, and the status it writes.

    *Absent:* a person schedules a campaign for Monday, changes their mind on
    Sunday, and the only way to stop it is a Temporal console they do not have.
    """
    message = _scheduled(tenant=tenant, actor=owner_actor, recipient=recipient)

    cancelled = services.cancel_message(tenant=tenant, actor=owner_actor, message=message)

    assert cancelled.status == Message.Status.CANCELLED
    assert cancelled.suppressed_reason == "", "not a suppression, and does not borrow its column"
    assert Message.objects.for_tenant(tenant).get(pk=message.pk).status == (
        Message.Status.CANCELLED
    )


def test_cancelling_announces_itself_under_its_own_name(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> None:
    """`comms.message.cancelled`, and NOT `comms.message.suppressed`.

    A subscriber keeping a consent mirror off the suppression stream would
    otherwise record an opt-out that nobody made — which is the same class of
    mistake as the nonce/message-id confusion, one table over: two facts sharing one name.
    """
    message = _scheduled(tenant=tenant, actor=owner_actor, recipient=recipient)
    services.cancel_message(tenant=tenant, actor=owner_actor, message=message)

    named = [
        event.name for event in Event.objects.for_tenant(tenant).filter(payload__id=str(message.pk))
    ]
    assert "comms.message.cancelled" in named
    assert "comms.message.suppressed" not in named


@pytest.mark.parametrize(
    "reach",
    [
        Message.Status.SENDING,
        Message.Status.SENT,
        Message.Status.DELIVERED,
        Message.Status.BOUNCED,
        Message.Status.FAILED,
        Message.Status.SUPPRESSED,
    ],
)
def test_a_message_past_the_queue_is_refused_by_name(
    reach: str,
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> None:
    """Every status that is not `queued`, and the refusal names the one it is in.

    `sending` is the member that matters most: a transport has the message in
    hand at that moment, so a `cancelled` row would be a lie the product could
    never detect. The others are already somebody's news.

    Written straight to the column rather than through the services that would
    normally move it, because the property under test is the GUARD and building
    six legitimate journeys would test the journeys.
    """
    message = _scheduled(tenant=tenant, actor=owner_actor, recipient=recipient)
    # `suppressed` carries its reason: the database refuses the pair otherwise
    # (`comms_message_suppressed_carries_a_reason`), which is that invariant
    # catching this test's own shortcut — worth honouring rather than working
    # around, so the row written here is one the product could really produce.
    moved: dict[str, Any] = {"status": reach}
    if reach == Message.Status.SUPPRESSED:
        moved |= {
            "suppressed_reason": Message.SuppressedReason.NO_CONSENT,
            "suppressed_at": timezone.now(),
        }
    Message.objects.filter(pk=message.pk).update(**moved)
    message.refresh_from_db()

    with pytest.raises(Conflict) as raised:
        services.cancel_message(tenant=tenant, actor=owner_actor, message=message)

    assert str(reach) in str(raised.value)
    assert Message.objects.for_tenant(tenant).get(pk=message.pk).status == reach


def test_cancelling_twice_is_a_conflict_and_not_a_shrug(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> None:
    """Deliberately unlike `archive_recipient`, which is idempotent.

    Archiving twice is one intent expressed twice. Cancelling a message that has
    already gone is a caller who believes something false, and telling them is
    the whole value of the second call.
    """
    message = _scheduled(tenant=tenant, actor=owner_actor, recipient=recipient)
    services.cancel_message(tenant=tenant, actor=owner_actor, message=message)

    with pytest.raises(Conflict):
        services.cancel_message(
            tenant=tenant,
            actor=owner_actor,
            message=Message.objects.for_tenant(tenant).get(pk=message.pk),
        )


def test_another_tenants_message_is_not_found(
    tenant: Tenant,
    owner_actor: Actor,
    stranger_actor: Actor,
    other_tenant: Tenant,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> None:
    """House rule 26 at the reference: the row came off the wire as an id."""
    from apps.comms.tests.conftest import make_recipient, make_template

    make_template(actor=stranger_actor)
    theirs = make_recipient(actor=stranger_actor, email="theirs@example.com")
    their_message = _scheduled(tenant=other_tenant, actor=stranger_actor, recipient=theirs)

    with pytest.raises(NotFound):
        services.cancel_message(tenant=tenant, actor=owner_actor, message=their_message)


# --- the belt that makes the ordering safe ------------------------------------------


def test_the_delivery_edge_refuses_a_cancelled_row(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> None:
    """**The row decides, not the run** — driven, because the service argues it.

    `cancel_message` settles the row inside its transaction and only *asks*
    Temporal to stop. If that request never lands — an unreachable server, a
    dropped hook — the run wakes and re-enters `deliver_message`, whose first
    act is to read the status back. `cancelled` is outside `SENDABLE`, so
    nothing is handed to any transport.

    This is what makes it safe to write the row first, and it is exactly the
    seam SEC-R1b hardened for the retry case.

    *Absent:* a cancel that Temporal missed delivers the message anyway, and the
    log says it was cancelled.
    """
    message = _scheduled(tenant=tenant, actor=owner_actor, recipient=recipient)
    services.cancel_message(tenant=tenant, actor=owner_actor, message=message)
    reread = Message.objects.for_tenant(tenant).get(pk=message.pk)

    assert reread.status not in services.SENDABLE

    # And the edge wall itself returns it untouched rather than sending.
    unchanged = services.mark_message_sending(tenant=tenant, actor=owner_actor, message=reread)
    assert unchanged.status == Message.Status.CANCELLED


# --- the doors ------------------------------------------------------------------------


def test_the_cancel_door_answers_the_row(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> None:
    message = _scheduled(tenant=tenant, actor=owner_actor, recipient=recipient)
    api.force_login(owner)

    response = api.post(f"/api/v1/messages/{message.pk}/cancel/", content_type=JSON)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["send_at"] is not None, "and the schedule it was cancelled out of"


def test_the_cancel_door_refuses_a_sent_message_with_conflict(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> None:
    """The refusal reaches the wire as `409 conflict`, with the status named."""
    message = _scheduled(tenant=tenant, actor=owner_actor, recipient=recipient)
    Message.objects.filter(pk=message.pk).update(status=Message.Status.SENT)
    api.force_login(owner)

    response = api.post(f"/api/v1/messages/{message.pk}/cancel/", content_type=JSON)

    assert response.status_code == 409, response.content
    body = response.json()
    assert body["code"] == "conflict"
    assert "sent" in body["detail"]


def test_the_machine_door_cancels_the_same_way(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> None:
    """Rule 17 for the new capability, over the same service."""
    from apps.comms.tests.test_mcp import context_for, tool

    message = _scheduled(tenant=tenant, actor=owner_actor, recipient=recipient)

    out = tool("cancel_message")(context_for(owner, tenant), message_id=message.pk)

    assert out.status == "cancelled"
    assert out.id == message.pk
