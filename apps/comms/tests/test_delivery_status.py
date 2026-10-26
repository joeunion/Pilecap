"""The status contract, from the wire in: a bounce that says so on its own log.

Every test in this module drives the **real inbound door** — the one signed
receiver in `apps/connections`, at `/api/v1/connections/{id}/webhook/`, with a
real HMAC over a real body. Nothing calls the handler directly, because the
thing worth proving is the seam: a payload posted by somebody else's server
reaches `record_delivery_status` through a registry, a signature check and two
apps that do not import each other's doors (ADR comms-3, comms-4).

**No Temporal server here, and that is deliberate.** `signal_workflow` defers
its dial to `transaction.on_commit`, which never fires in a non-transactional
test, so what these tests measure is the row, the event and the audit trail —
the part the product promises whether or not a worker is listening. The signal
itself, and the run completing on it, are proved against a real server in
`test_workflows.py`; splitting them keeps each test's failure legible.

What is *not* proved here: **a real ESP's own signature scheme and a real ESP's
own payload shape.** These payloads are Anymail's normalised vocabulary and
these signatures are this door's HMAC — the shape a product's own adapter, or a
deployment that verifies elsewhere, hands on. Since E1′ that gap has its own
module, `test_esp_webhook.py`: Resend's raw bodies, Svix signatures, and
Anymail's translation between them, through this same door. The two modules
converge one line inside `EmailChannel.normalize_status`, which is the property
worth having — everything below that line is proved once, here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any
from uuid import UUID

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.comms import services
from apps.comms.models import Channel, ChannelPreference, Message, MessageTemplate, Recipient
from apps.comms.providers import (
    DROP_NO_MESSAGE_ID,
    DROP_NON_TERMINAL,
    DROP_UNTRANSLATABLE,
    STATUS_PROVIDER,
    EmailChannel,
    ExplainsStatusDrops,
    FakeSmsChannel,
    StatusDrop,
    status_drop,
)
from apps.comms.selectors import get_message_by_provider_id
from apps.connections.api import SIGNATURE_HEADER, SIGNATURE_PREFIX
from apps.connections.models import Connection, InboundWebhook
from apps.connections.providers import inbound_handler
from apps.connections.services import create_connection
from apps.core.actor import Actor, system_actor
from apps.core.audit import AuditEntry
from apps.core.exceptions import Conflict, Invalid, NotFound
from apps.core.models import Organization, Tenant
from apps.core.services import root_organization
from apps.events.models import Event

pytestmark = pytest.mark.django_db

JSON = "application/json"

#: The shared secret the ESP connection signs with. Its own value, not the one
#: `apps/connections/tests` uses, so a test here cannot pass because of a
#: fixture over there. The pragma is detect-secrets' own documented mitigation
#: and is used rather than a `.secrets.baseline` entry deliberately: the
#: baseline is a shared file at the root of the tree and this app owns neither
#: it nor the right to make four other lanes conflict on it.
STATUS_SECRET = "the-esp-shares-this-and-nobody-else-does"  # noqa: S105 — a signing secret the test both signs and verifies with  # pragma: allowlist secret


# --- the door ------------------------------------------------------------------


def status_url(connection: Connection) -> str:
    return f"/api/v1/connections/{connection.pk}/webhook/"


def signature(body: bytes, secret: str = STATUS_SECRET) -> str:
    """What the ESP's server would put on the request. Computed, never copied."""
    return SIGNATURE_PREFIX + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def post_status(
    api: Client,
    connection: Connection,
    payload: dict[str, Any],
    *,
    secret: str = STATUS_SECRET,
) -> Any:
    """One signed status delivery, exactly as a provider would send it."""
    body = json.dumps(payload).encode()
    return api.post(
        status_url(connection),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: signature(body, secret), "X-Event-Type": "delivery"},
    )


def tracking_event(message: Message, event_type: str, **extra: Any) -> dict[str, Any]:
    """An Anymail-normalised tracking event for a message this product sent."""
    return {
        "event_type": event_type,
        "message_id": message.provider_message_id,
        "timestamp": "2026-08-20T09:00:00+00:00",
        **extra,
    }


# --- fixtures ------------------------------------------------------------------


@pytest.fixture
def esp(tenant: Tenant, owner_actor: Actor) -> Connection:
    """The tenant's connection to its email provider, holding the webhook secret."""
    return create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider=STATUS_PROVIDER,
        name="Transactional email",
        credentials={"webhook_secret": STATUS_SECRET, "access_token": "an-esp-key"},
        is_signature_v2_required=False,
    )


def sent_message(*, tenant: Tenant, actor: Actor, recipient: Recipient) -> Message:
    """A message a transport has accepted — the state a status webhook arrives on.

    Built through `send()` and then through the same service the delivery
    activity calls, rather than by writing a row: a fixture that set `status`
    and `provider_message_id` by hand could set a pair the product cannot
    actually produce, and every assertion after it would be about a state that
    does not occur.
    """
    message = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=actor,
    )
    return services.record_message_sent(
        tenant=tenant,
        actor=actor,
        message=message,
        provider="locmem",
        provider_message_id=f"<{message.pk}@localhost>",
    )


@pytest.fixture
def message(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> Message:
    return sent_message(tenant=tenant, actor=owner_actor, recipient=recipient)


def reread(tenant: Tenant, message: Message) -> Message:
    return Message.objects.for_tenant(tenant).get(pk=message.pk)


def events(tenant: Tenant, name: str) -> list[Event]:
    return list(Event.objects.for_tenant(tenant).filter(name=name).order_by("created_at"))


# --- C2a-1: delivered, over the wire --------------------------------------------


def test_a_delivered_webhook_moves_the_row_and_says_so_on_the_spine(
    api: Client, tenant: Tenant, owner: User, esp: Connection, message: Message
) -> None:
    """C2a-1. The headline, minus the run: a delivered payload becomes a delivered row.

    The event's payload is asserted **against the REST body for the same
    message**, field by field, because that equality is the contract
    `MessageOut` exists to keep: a webhook subscriber and a client reading the
    message log must not be looking at two shapes.

    It **is** a raw `==`, and that is new. This assertion used to run each
    timestamp through a `_to_millis` shim, because the two serialisers disagreed
    about datetime *precision*: ninja renders a response through Django's
    `DjangoJSONEncoder`, which truncates to milliseconds, while `emit()` carried
    `model_dump(mode="json")`, which keeps microseconds — same instant, two
    strings, and template-wide rather than this module's. ADR core-8
    (`docs/product/architecture.md`, the ADR home)
    closed it at the one chokepoint: `emit()` now renders its payload through
    the exact encoder class the REST door renders with. The shim is gone and the
    equality is literal, which is what E3's sentence — a webhook client sees what
    a REST client sees — was always claiming.
    """
    assert reread(tenant, message).status == Message.Status.SENT

    response = post_status(api, esp, tracking_event(message, "delivered"))
    assert response.status_code == 202, "accepted, never processed"

    row = reread(tenant, message)
    assert row.status == Message.Status.DELIVERED
    assert row.delivered_at is not None
    assert row.bounced_at is None

    api.force_login(owner)
    detail = api.get(f"/api/v1/messages/{message.pk}/")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "delivered"
    assert body["delivered_at"] is not None

    published = events(tenant, "comms.message.delivered")
    assert len(published) == 1
    assert published[0].v == 1

    payload = dict(published[0].payload)
    assert payload.pop("v") == 1
    # `recipient_email` is the doors' alone: `MessageOut` marks it personal.
    assert body.pop("recipient_email")
    assert "recipient_email" not in payload
    assert sorted(payload) == sorted(body), "one row, one key set, both doors"
    assert payload == body, "one row, one rendering, both doors"
    # The timestamps are the half that used to differ, so they are named rather
    # than left to be inferred from a passing `==` over a dict.
    for key in ("created_at", "sent_at", "delivered_at"):
        assert payload[key] == body[key], key


def test_without_the_webhook_the_message_stays_sent_and_the_spine_is_silent(
    tenant: Tenant, message: Message
) -> None:
    """The absent half of C2a-1 — the test the one above would pass without.

    Nothing is posted. If a `delivered` row or a `comms.message.delivered` event
    can appear without a provider saying so, the whole status contract is
    decoration.
    """
    row = reread(tenant, message)
    assert row.status == Message.Status.SENT
    assert row.delivered_at is None
    assert events(tenant, "comms.message.delivered") == []


# --- C2a-2: bounced -------------------------------------------------------------


def test_a_bounced_webhook_records_the_bounce_and_the_provider_reason(
    api: Client, tenant: Tenant, esp: Connection, message: Message
) -> None:
    """C2a-2. Without this the headline is false: a bounce nobody can see."""
    response = post_status(
        api,
        esp,
        tracking_event(
            message,
            "bounced",
            description="550 5.1.1 The email account that you tried to reach does not exist",
            reject_reason="bounced",
        ),
    )
    assert response.status_code == 202

    row = reread(tenant, message)
    assert row.status == Message.Status.BOUNCED
    assert row.bounced_at is not None
    assert row.delivered_at is None
    assert "550 5.1.1" in row.error

    published = events(tenant, "comms.message.bounced")
    assert len(published) == 1
    assert published[0].v == 1
    assert published[0].payload["status"] == "bounced"


@pytest.mark.parametrize("event_type", ["bounced", "rejected"])
def test_the_two_words_that_mean_this_address_is_dead_both_bounce(
    api: Client, tenant: Tenant, esp: Connection, message: Message, event_type: str
) -> None:
    """A rejection is a bounce. One column, one rule.

    Collapsing them is a decision (`providers.EMAIL_STATUS`), not an accident,
    and it is the decision that lets a suppression rule read one status instead
    of two.

    **Re-pointed by F1m (ADR comms-9, amended), and the re-pointing is the
    contract change**: `complained` was the third member of this parametrize and
    is not one any more. A rejection is an ESP saying *this address is dead*,
    which is a fact about the address; a complaint is a person saying *stop
    writing to me*, which is a fact about consent and about a message that
    arrived. The sibling below is where the complaint's own contract is now
    asserted.
    """
    assert post_status(api, esp, tracking_event(message, event_type)).status_code == 202
    assert reread(tenant, message).status == Message.Status.BOUNCED


def test_a_complaint_suppresses_without_claiming_the_message_bounced(
    api: Client, tenant: Tenant, esp: Connection, recipient: Recipient, message: Message
) -> None:
    """F1m-2, and the other half of the re-pointing above.

    The complaint's payload is identical to the bounce's at this door — the same
    Anymail-normalised shape, the same `message_id` — and the outcome is
    deliberately different: the address is silenced, the row is untouched, and
    the announcement carries the complaint's own name.

    Absent: the split is a docstring, and a `sent` message the ESP accepted is
    logged as one it refused.
    """
    assert post_status(api, esp, tracking_event(message, "complained")).status_code == 202

    row = reread(tenant, message)
    assert row.status == Message.Status.SENT, "a complaint is not delivery news"
    assert row.bounced_at is None
    assert row.bounce_kind is None

    silenced = preference_for(tenant, recipient)
    assert silenced is not None and silenced.suppressed_at is not None

    published = events(tenant, "comms.message.complained")
    assert len(published) == 1
    assert published[0].v == 1
    assert published[0].payload["status"] == "sent", "the payload is the row's own truth"
    assert events(tenant, "comms.message.bounced") == []


# --- C2a-3: the same delivery, twice --------------------------------------------


def test_an_identical_webhook_twice_transitions_once_and_emits_once(
    api: Client, tenant: Tenant, esp: Connection, message: Message
) -> None:
    """C2a-3. Every ESP worth integrating with redelivers; nothing may double.

    The second delivery is a `202` with nothing behind it — not a `409`, because
    the provider is not wrong, and not a second event, because the message did
    not arrive twice.
    """
    payload = tracking_event(message, "delivered")
    first = post_status(api, esp, payload)
    second = post_status(api, esp, payload)

    assert (first.status_code, second.status_code) == (202, 202)
    assert len(events(tenant, "comms.message.delivered")) == 1

    row = reread(tenant, message)
    assert row.status == Message.Status.DELIVERED
    # Both deliveries were stored: the receipt log is not deduplicated, and
    # should not be — "they told us twice" is itself a fact.
    assert InboundWebhook.objects.for_tenant(tenant).count() == 2


def test_an_open_is_stored_and_ignored(
    api: Client, tenant: Tenant, esp: Connection, message: Message
) -> None:
    """Opens and clicks are real events and none of them is a delivery status.

    A named deferral: tracking ships with its own rung. Until then the honest
    answer is that the message is still `sent` and the run is still waiting.
    """
    for kind in ("opened", "clicked", "queued", "deferred"):
        assert post_status(api, esp, tracking_event(message, kind)).status_code == 202

    row = reread(tenant, message)
    assert row.status == Message.Status.SENT
    assert row.delivered_at is None
    assert InboundWebhook.objects.for_tenant(tenant).count() == 4, "stored, just not acted on"


# --- C2a-6: the closed vocabulary and the settled row ---------------------------


def test_a_status_outside_the_set_is_invalid_and_names_the_field(
    tenant: Tenant, root_org: Organization, message: Message
) -> None:
    """C2a-6, first half. A provider inventing a word does not invent a status.

    Asserted at the service rather than at the door because the status door
    answers `202` to everything by design — the refusal envelope
    `{detail, code, errors}` that `config/api.py` builds from this exception is
    proved in `apps/core/tests/test_refusals.py`, once, for every refusal.
    """
    with pytest.raises(Invalid) as refusal:
        services.record_delivery_status(
            tenant=tenant,
            actor=system_actor(tenant, root_org),
            provider_message_id=message.provider_message_id,
            status="exploded",
        )
    assert refusal.value.code == "invalid"
    assert list(refusal.value.errors) == ["status"]
    assert reread(tenant, message).status == Message.Status.SENT


def test_a_delivered_message_cannot_then_bounce(
    api: Client, tenant: Tenant, root_org: Organization, esp: Connection, message: Message
) -> None:
    """C2a-6, second half. A log that contradicts itself is worse than a gap."""
    assert post_status(api, esp, tracking_event(message, "delivered")).status_code == 202

    with pytest.raises(Conflict) as refusal:
        services.record_delivery_status(
            tenant=tenant,
            actor=system_actor(tenant, root_org),
            provider_message_id=message.provider_message_id,
            status=Message.Status.BOUNCED.value,
        )
    assert refusal.value.code == "conflict"
    assert reread(tenant, message).status == Message.Status.DELIVERED
    assert events(tenant, "comms.message.bounced") == []


def test_a_suppressed_message_takes_no_status_at_all(
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    """A message the consent wall refused was never handed to anybody.

    It has no `provider_message_id`, so the selector cannot find it — which is
    the same wall, one layer earlier, and is why an empty provider id is
    `NotFound` rather than a filter that matches the whole queue.
    """
    refused = services.send(
        recipient=recipient,
        template="newsletter",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    assert refused.status == Message.Status.SUPPRESSED
    assert refused.provider_message_id == ""

    with pytest.raises(NotFound):
        services.record_delivery_status(
            tenant=tenant,
            actor=system_actor(tenant, root_org),
            provider_message_id="",
            status=Message.Status.DELIVERED.value,
        )


def test_only_the_system_may_record_a_status(
    tenant: Tenant, owner_actor: Actor, message: Message
) -> None:
    """A delivery is observed, never asserted — `policies.can_record_status`.

    The tenant's **owner** is refused, which is the strongest form of the claim:
    there is no role in the product that can make the message log say a customer
    received something they did not.
    """
    from apps.core.exceptions import Forbidden

    with pytest.raises(Forbidden):
        services.record_delivery_status(
            tenant=tenant,
            actor=owner_actor,
            provider_message_id=message.provider_message_id,
            status=Message.Status.DELIVERED.value,
        )
    assert reread(tenant, message).status == Message.Status.SENT


# --- C2a-7: the walls -----------------------------------------------------------


def test_a_webhook_naming_another_tenants_message_touches_nothing(
    api: Client,
    tenant: Tenant,
    other_tenant: Tenant,
    stranger_actor: Actor,
    owner_actor: Actor,
    esp: Connection,
    receipt: MessageTemplate,
    recipient: Recipient,
) -> None:
    """C2a-7. **The worst possible answer is a cross-tenant write.**

    The delivery is posted at *this* tenant's connection, correctly signed, and
    names a provider message id belonging to *another* tenant's message. The
    receipt is stored — under the connection's tenant, where it belongs, because
    somebody really did send it — and the foreign row does not move, because the
    read that would have found it is scoped to the connection's tenant and not
    to anything the payload said.
    """
    from apps.comms.tests.conftest import make_recipient, make_template

    make_template(actor=stranger_actor)
    theirs = sent_message(
        tenant=other_tenant,
        actor=stranger_actor,
        recipient=make_recipient(actor=stranger_actor, email="theirs@example.com"),
    )
    mine = sent_message(tenant=tenant, actor=owner_actor, recipient=recipient)

    response = post_status(api, esp, tracking_event(theirs, "bounced"))
    assert response.status_code == 202

    assert reread(other_tenant, theirs).status == Message.Status.SENT, "not ours to touch"
    assert reread(other_tenant, theirs).bounced_at is None
    assert reread(tenant, mine).status == Message.Status.SENT, "and not a neighbour either"
    assert events(other_tenant, "comms.message.bounced") == []

    stored = InboundWebhook.objects.for_tenant(tenant).get()
    assert stored.connection_id == esp.pk
    assert not InboundWebhook.objects.for_tenant(other_tenant).exists()


def test_a_wrongly_signed_status_is_refused_and_stores_nothing(
    api: Client, tenant: Tenant, esp: Connection, message: Message
) -> None:
    """C2a-7's other half. The credential on this door is the HMAC, and only that."""
    response = post_status(api, esp, tracking_event(message, "bounced"), secret="not-the-secret")  # noqa: S106 — a signing secret the test both signs and verifies with
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()
    assert reread(tenant, message).status == Message.Status.SENT
    assert events(tenant, "comms.message.bounced") == []


def test_the_selector_refuses_an_unresolved_hat(tenant: Tenant, message: Message) -> None:
    """House rule 24, fail-closed, on the read the status webhook depends on.

    `visible_to(None)` reads an empty table rather than the table — so a handler
    that forgot to resolve an acting organization would find nothing rather than
    finding everything.
    """
    with pytest.raises(NotFound):
        get_message_by_provider_id(
            tenant=tenant, provider_message_id=message.provider_message_id, org=None
        )
    found = get_message_by_provider_id(
        tenant=tenant,
        provider_message_id=message.provider_message_id,
        org=root_organization(tenant=tenant),
    )
    assert found.pk == message.pk


# --- C2a-8: the audit trail and the correlation chain ---------------------------


def test_the_audit_row_names_the_webhook_door_and_joins_the_request_chain(
    api: Client, tenant: Tenant, esp: Connection, message: Message
) -> None:
    """C2a-8. One id joins the delivery, the service, the signal and the event.

    And the message's **original** correlation id is untouched: it belongs to
    the request that asked for the send, months of log retention ago, and a
    status arriving later is a new chain rather than a rewrite of that one.
    """
    minted_by_the_send = message.correlation_id

    assert post_status(api, esp, tracking_event(message, "delivered")).status_code == 202

    recorded = AuditEntry.objects.filter(action="comms.record_delivery_status").get()
    assert recorded.door == "webhook"
    assert recorded.outcome == "ok"
    assert recorded.actor_kind == "system"
    assert recorded.actor_user_id is None
    assert recorded.object_id == UUID(str(message.pk))
    assert recorded.correlation_id

    signalled = AuditEntry.objects.filter(action="workflows.signal_workflow").get()
    assert signalled.correlation_id == recorded.correlation_id

    stored = InboundWebhook.objects.for_tenant(tenant).get()
    received = AuditEntry.objects.filter(
        action="connections.record_inbound_webhook", object_id=stored.pk
    ).get()
    assert received.correlation_id == recorded.correlation_id, "one webhook, one chain"

    assert reread(tenant, message).correlation_id == minted_by_the_send
    assert events(tenant, "comms.message.delivered")[0].correlation_id == recorded.correlation_id


# --- the seam itself ------------------------------------------------------------


def test_comms_claimed_the_esp_provider_slug_at_startup() -> None:
    """`ready()` ran, and the registry is what connects the two apps.

    Not a mechanism test: without this registration the receiver stores the
    delivery, hands it to the event spine and stops, and every wire proof above
    would fail for a reason no reader would guess from the failure.
    """
    assert inbound_handler(STATUS_PROVIDER) is not None
    assert inbound_handler("nobody-registered-this") is None


def test_an_unparseable_body_is_stored_and_dropped(
    api: Client, tenant: Tenant, esp: Connection, message: Message
) -> None:
    """Somebody else's malformed payload is not a fault on our door."""
    body = b"this is not json"
    response = api.post(
        status_url(esp),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: signature(body)},
    )
    assert response.status_code == 202
    assert InboundWebhook.objects.for_tenant(tenant).count() == 1
    assert reread(tenant, message).status == Message.Status.SENT


def test_normalize_status_translates_and_refuses_to_guess() -> None:
    """The adapter, on its own: what maps, what does not, and what has no id."""
    channel = EmailChannel()
    delivered = channel.normalize_status(payload={"event_type": "delivered", "message_id": "<a@b>"})
    assert delivered is not None
    assert (delivered.status, delivered.provider_message_id) == ("delivered", "<a@b>")

    assert channel.normalize_status(payload={"event_type": "opened", "message_id": "<a@b>"}) is None
    assert channel.normalize_status(payload={"event_type": "unknowable"}) is None
    # A terminal event with nothing to join on is not a status: acting on it
    # would mean picking a row, and there is no row it names.
    assert channel.normalize_status(payload={"event_type": "delivered"}) is None


# --- ADR comms-8: what the bounce is FOR -----------------------------------------
#
# Everything above proves the record is **kept**. These prove it is
# **consulted**: the three provider words that mean "this address must stop
# being mailed" reach `suppress_recipient` inside the status write's own
# transaction, and the next send to that address is refused. The record
# was faithful and inert — three docstrings promised this
# chain and no writer existed anywhere in the tree — so each test below is the
# reviewer's own probe shape, and each one was red on the tree before this fix.


def preference_for(
    tenant: Tenant, recipient: Recipient, channel: str = Channel.EMAIL
) -> ChannelPreference | None:
    """This person's preference row for this channel, or the absence of one.

    Read through the tenant manager rather than through an acting hat on
    purpose: the question these tests ask is "does a row exist anywhere in this
    tenant", and reading with a hat would let a suppression written into the
    wrong branch look like no suppression at all.
    """
    return (
        ChannelPreference.objects.for_tenant(tenant)
        .filter(recipient=recipient, channel=channel)
        .first()
    )


@pytest.mark.parametrize("event_type", ["bounced", "complained", "rejected"])
def test_the_bounce_set_suppresses_the_address_it_came_from(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
    recipient: Recipient,
    receipt: MessageTemplate,
    message: Message,
    event_type: str,
) -> None:
    """R2-2, ADR comms-8 (1). **The feedback loop closes.**

    Over the real signed receiver, for each of the three provider words that
    mean *stop mailing this address*: the recipient's channel comes out
    suppressed, the suppression is audited as `comms.suppress_recipient` by the
    system, and the next `send()` to that address answers `suppressed`.

    **The three words no longer settle on one status** (F1m, ADR comms-9 as
    amended) and the fork below says so: a bounce and a rejection transition the
    row, a complaint does not. The suppression — the property this test exists
    for — is identical for all three, which is why all three stayed in the
    parametrize rather than the complaint being moved out of it.

    Absent: the dead-address finding — the product keeps mailing addresses that told it
    to stop, which is the consent wall leaking at the feedback seam and
    eventually an ESP reputation fact.
    """
    assert preference_for(tenant, recipient) is None, (
        "nothing has been said about this address yet, so the row below is the bounce's own work"
    )

    assert post_status(api, esp, tracking_event(message, event_type)).status_code == 202

    settled = reread(tenant, message)
    if event_type == "complained":
        assert settled.status == Message.Status.SENT, "a complaint transitioned the row"
    else:
        assert settled.status == Message.Status.BOUNCED

    suppressed = preference_for(tenant, recipient)
    assert suppressed is not None, "the bounce wrote no preference row at all"
    assert suppressed.suppressed_at is not None, "the record was kept and never consulted"
    # In the recipient's own branch, exactly where a hand-written suppression
    # lands — otherwise `send()`, which reads with the sender's hat, would never
    # see it again.
    assert suppressed.organization_id == recipient.organization_id

    audited = AuditEntry.objects.filter(action="comms.suppress_recipient").get()
    assert audited.actor_kind == "system", "nobody clicked this; the transport said it"
    assert audited.actor_user_id is None
    assert audited.outcome == "ok"

    later = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    assert later.status == Message.Status.SUPPRESSED
    assert later.suppressed_reason == Message.SuppressedReason.SUPPRESSED


def test_the_suppression_and_the_status_are_one_transaction(
    tenant: Tenant,
    recipient: Recipient,
    message: Message,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R2-2's instrument. A planted failure after the status write rolls **both** back.

    The service is called directly here rather than over the wire, and that is
    the point: the inbound receiver deliberately swallows a handler's exception
    inside a savepoint so one app's bad afternoon is not a 500 on the shared
    door, which would hide exactly the rollback this test is measuring. The
    atomic block under test is `record_delivery_status`'s own.

    The failure goes in `_signal_delivery`, the last thing that service does
    inside that block. If the suppression were written in a transaction of its
    own — a second connection, an `on_commit` hook, a call made outside the
    block — the rollback would leave a suppressed address beside a message that
    never bounced, which is the half-landed state this refuses.

    Absent: "in the same transaction" is a claim in a docstring.
    """

    def explode(**_: Any) -> None:
        raise RuntimeError("the signal went wrong after the status write")

    monkeypatch.setattr(services, "_signal_delivery", explode)

    with pytest.raises(RuntimeError):
        services.record_delivery_status(
            tenant=tenant,
            actor=system_actor(tenant, root_organization(tenant=tenant)),
            provider_message_id=message.provider_message_id,
            status=Message.Status.BOUNCED,
        )

    assert reread(tenant, message).status == Message.Status.SENT, "the status rolled back"
    assert preference_for(tenant, recipient) is None, "and so did the suppression"

    # The positive control, in the same test, because a rollback assertion on a
    # write that never happens passes for the wrong reason — which is exactly
    # how this test read on the tree before this fix.
    monkeypatch.undo()
    services.record_delivery_status(
        tenant=tenant,
        actor=system_actor(tenant, root_organization(tenant=tenant)),
        provider_message_id=message.provider_message_id,
        status=Message.Status.BOUNCED,
    )
    assert reread(tenant, message).status == Message.Status.BOUNCED
    landed = preference_for(tenant, recipient)
    assert landed is not None and landed.suppressed_at is not None


def test_a_failed_status_does_not_suppress_anybody(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
    recipient: Recipient,
    receipt: MessageTemplate,
    message: Message,
) -> None:
    """R2-3, ADR comms-8's rejected half. **Weather is not a fact about an address.**

    `failed` is the ESP's own machinery — a spent retry, an outage, a queue that
    gave up. Suppressing on it would silence a healthy recipient for ever on the
    strength of a bad afternoon.

    Absent: the collapsed set quietly grows a fourth member and every transient
    provider fault becomes a permanent refusal.
    """
    assert post_status(api, esp, tracking_event(message, "failed")).status_code == 202

    assert reread(tenant, message).status == Message.Status.FAILED
    assert preference_for(tenant, recipient) is None, "a failure said nothing about the address"
    assert not AuditEntry.objects.filter(action="comms.suppress_recipient").exists()

    later = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    assert later.status == Message.Status.QUEUED


def test_an_auto_suppression_lifts_through_the_door_that_already_exists(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
    recipient: Recipient,
    receipt: MessageTemplate,
    message: Message,
) -> None:
    """R2-6, ADR comms-8 (2). **A data-quality fact, not a punishment.**

    A bounce-driven suppression lifts through `unsuppress_recipient`, exactly as
    a hand-written one does, and the lift is audited like any other write. No
    second vocabulary — no auto-suppression flag, no separate lift service —
    because one fact deserves one door.

    Absent: auto-suppression becomes a one-way ratchet no human can correct
    through a door, and support tickets end in shell sessions.
    """
    assert post_status(api, esp, tracking_event(message, "bounced")).status_code == 202
    auto = preference_for(tenant, recipient)
    assert auto is not None and auto.suppressed_at is not None

    lifted = services.unsuppress_recipient(
        tenant=tenant, actor=owner_actor, recipient=recipient, channel=Channel.EMAIL
    )
    assert lifted.suppressed_at is None
    assert AuditEntry.objects.filter(action="comms.unsuppress_recipient").exists()

    later = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    assert later.status == Message.Status.QUEUED, "a re-verified address is mailable again"


# --- ADR comms-13: three drops, three names -------------------------------
#
# What these exist for. On the template-HMAC path a driver posted a **raw ESP
# body**, `normalize_status` found no `event_type` and no translation to supply
# one, and the drop was logged `comms.status.ignored` with `event_type=""` — a
# name meaning "read and judged non-terminal" over an event nobody managed to
# read. The message stayed `sent` forever and the field test's first hypothesis
# was a missing worker, because the log offered nothing else to look at.
#
# So the property here is a **naming** one, and it is asserted the only way it
# can be: on the structured line as it actually left the process. Each test
# names the line it wants AND the line it must not see, because "a new name
# appeared" and "the wrong old name stopped appearing" are two facts and both
# are needed.


def status_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """Every `comms.status.*` line written in this block, parsed back from JSON.

    Read out of stdlib logging rather than through `structlog.testing`, for the
    reason `core/tests/test_observability.py` gives at its own helper: capturing
    at the structlog end swaps the processor chain, and what a dashboard will
    group by is the rendering, not the event dict on its way there.

    Non-JSON records are skipped rather than failing the parse: Django's own
    loggers share this handler and none of them owes this module a shape.
    """
    lines: list[dict[str, Any]] = []
    for record in caplog.records:
        try:
            parsed = json.loads(record.getMessage())
        except ValueError:
            continue
        if isinstance(parsed, dict) and str(parsed.get("event", "")).startswith("comms.status."):
            lines.append(parsed)
    return lines


def raw_resend_event(kind: str, *, email_id: str) -> dict[str, Any]:
    """A body in **Resend's own** shape — no `event_type` anywhere in it.

    This is what `mail_demo` posted at the HMAC door, and what any operator who
    points an ESP's webhook straight at this receiver will post. Under test
    settings `EMAIL_BACKEND` is locmem, so `_anymail_esp()` is empty and there is
    no translation available: the body arrives in a vocabulary this deployment
    cannot read, which is the whole finding.
    """
    return {
        "type": kind,
        "created_at": "2026-08-20T09:00:00+00:00",
        "data": {"email_id": email_id, "to": ["ada@example.com"]},
    }


def test_a_raw_body_with_no_esp_configured_is_logged_untranslatable_not_ignored(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    message: Message,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The original repro, as a test. The drop says what would make the body readable.

    *Absent:* the raw-body case still prints `comms.status.ignored` with
    `event_type=""` — a judgement claimed over an event that was never read, and
    the reason the finding cost a field test.
    """
    body = json.dumps(raw_resend_event("email.delivered", email_id="re_1")).encode()
    with caplog.at_level(logging.INFO):
        response = api.post(
            status_url(esp),
            data=body,
            content_type=JSON,
            headers={SIGNATURE_HEADER: signature(body)},
        )
    assert response.status_code == 202, "verify, store, hand off — the 202 is unchanged"

    named = [line["event"] for line in status_lines(caplog)]
    assert named == ["comms.status.untranslatable_body"]
    assert "comms.status.ignored" not in named

    line = status_lines(caplog)[0]
    assert line["connection_id"] == str(esp.pk)
    assert line["provider"] == STATUS_PROVIDER
    assert line["esp"] == "", "no Anymail backend here — which is exactly the diagnosis"
    # The remedy is the point of the new name: both ways out, in the line.
    assert "event_type" in line["remedy"]
    assert "EMAIL_BACKEND" in line["remedy"]

    # And nothing was recorded off a body nobody could read.
    assert reread(tenant, message).status == Message.Status.SENT
    assert not AuditEntry.objects.filter(action="comms.record_delivery_status").exists()


def test_a_non_terminal_event_logs_ignored_with_the_event_type_it_read(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    message: Message,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`ignored` keeps its meaning: read, understood, and not a status.

    Every word below is a real event the door handled correctly, and the line
    now carries which one — so "the run is still waiting because nothing
    terminal has arrived" is readable off the log instead of inferred from it.

    **The set SHRANK, and that is deliberate, not a regression.**
    `opened` and `clicked` used to be in this list: read, understood, and thrown
    away with a log line. ADR comms-9's engagement half stops discarding them —
    they are now `MessageEngagement` rows and the door says
    `comms.engagement.recorded` instead. What is left here is the genuinely
    contentless remainder: a queue acknowledgement and a deferral, which are the
    transport talking about its own machinery. The sibling test below pins the
    two that left, so the boundary is asserted from both sides rather than
    silently moved.

    *Absent:* `ignored` prints an empty `event_type` and stops being
    distinguishable from a body the door could not read at all.
    """
    for kind in ("queued", "deferred"):
        caplog.clear()
        with caplog.at_level(logging.INFO):
            assert post_status(api, esp, tracking_event(message, kind)).status_code == 202

        lines = status_lines(caplog)
        assert [line["event"] for line in lines] == ["comms.status.ignored"], kind
        assert lines[0]["event_type"] == kind
        assert lines[0]["event_type"] != "", "the promise the old line broke"
        assert lines[0]["connection_id"] == str(esp.pk)

    assert reread(tenant, message).status == Message.Status.SENT


def test_an_open_or_a_click_is_no_longer_a_drop(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    message: Message,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The other side of the boundary the test above moved (ADR comms-9).

    Two claims and they are the whole of why this fix touched this module:
    an open or a click writes **no** `comms.status.*` line at all — it is not a
    status and it is no longer a status-shaped drop — and it leaves the message
    row exactly where it was. The engagement row itself, its idempotence and its
    branch are `tests/test_engagement.py`'s; this is only the door's vocabulary,
    asserted where the vocabulary is asserted.

    *Absent:* the two words quietly go on being logged as `ignored` while a row
    is written behind them, which is a log line contradicting the database.
    """
    for kind in ("opened", "clicked"):
        caplog.clear()
        with caplog.at_level(logging.INFO):
            assert post_status(api, esp, tracking_event(message, kind)).status_code == 202
        assert status_lines(caplog) == [], kind

    assert reread(tenant, message).status == Message.Status.SENT


def test_a_terminal_event_naming_no_message_is_its_own_name_too(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    message: Message,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The third drop, which `ignored` also used to swallow.

    A `delivered` with no `message_id` was read and understood and *is* terminal
    — so filing it under a word that means "not terminal" was the same lie in a
    second place. It is the provider's fault rather than the deployment's, and
    it gets a name and a remedy of its own.

    *Absent:* criterion 1's word "only" is untrue — `ignored` still fires for
    something that was never judged non-terminal at all.
    """
    with caplog.at_level(logging.INFO):
        assert post_status(api, esp, {"event_type": "delivered"}).status_code == 202

    lines = status_lines(caplog)
    assert [line["event"] for line in lines] == ["comms.status.no_message_id"]
    assert lines[0]["event_type"] == "delivered"
    assert "message_id" in lines[0]["remedy"]
    assert reread(tenant, message).status == Message.Status.SENT


def test_the_hmac_round_trip_closes_and_only_the_accepted_report_is_audited(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    message: Message,
) -> None:
    """W-C1 criterion 2. The door's contract, driven both ways in one test.

    A body in the vocabulary this door asks for moves `sent -> delivered` and
    leaves one audit row; a body in the vocabulary it does not moves nothing and
    leaves none. Both in one test because the pair is the property: an audit
    trail that recorded the drop would be claiming a write that did not happen,
    and one that missed the acceptance would be the status contract not closing.

    *Absent:* the status is unmoved (`sent` forever), or a drop leaves a
    row behind that says a status was recorded.
    """
    assert reread(tenant, message).status == Message.Status.SENT

    assert post_status(api, esp, tracking_event(message, "delivered")).status_code == 202
    row = reread(tenant, message)
    assert row.status == Message.Status.DELIVERED
    assert row.delivered_at is not None

    accepted = AuditEntry.objects.filter(action="comms.record_delivery_status")
    assert accepted.count() == 1
    assert accepted.get().object_id == UUID(str(message.pk))

    # The dropped one, at the same door, against the same connection.
    body = json.dumps(raw_resend_event("email.bounced", email_id="re_2")).encode()
    dropped = api.post(
        status_url(esp),
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: signature(body)},
    )
    assert dropped.status_code == 202
    assert reread(tenant, message).status == Message.Status.DELIVERED, "unmoved by an unread body"
    assert accepted.count() == 1, "no audit row for a report nobody could read"


def test_the_adapter_says_which_of_the_three_drops_it_was() -> None:
    """The unit under the log lines: one traversal, three named outcomes.

    Driven on the adapter rather than through the door so that a change to
    either can fail on its own — the door tests above prove the names reach a
    log line; this proves the adapter can tell them apart at all.
    """
    channel = EmailChannel()

    carries_a_status = channel.explain_status_drop(
        payload={"event_type": "delivered", "message_id": "<a@b>"}
    )
    assert carries_a_status is None, "a body that carries a status is not a drop"

    non_terminal = channel.explain_status_drop(payload={"event_type": "opened"})
    assert non_terminal == StatusDrop(reason=DROP_NON_TERMINAL, event_type="opened")

    unknown_word = channel.explain_status_drop(payload={"event_type": "unknowable"})
    assert unknown_word == StatusDrop(reason=DROP_NON_TERMINAL, event_type="unknowable")

    no_join = channel.explain_status_drop(payload={"event_type": "delivered"})
    assert no_join == StatusDrop(reason=DROP_NO_MESSAGE_ID, event_type="delivered")

    raw = channel.explain_status_drop(payload={"type": "email.delivered", "data": {}})
    assert raw == StatusDrop(reason=DROP_UNTRANSLATABLE, event_type="")

    # An `event_type` that is present and empty is still no word at all.
    empty = channel.explain_status_drop(payload={"event_type": "  "})
    assert empty == StatusDrop(reason=DROP_UNTRANSLATABLE, event_type="")


class SilentTransport:
    """A product's transport that satisfies `ChannelProvider` and nothing more.

    Written here rather than borrowed from `providers`, for two reasons. It is
    the shape a *product* ships — two members, because two is all this app ever
    asked any transport for — and that is exactly the case the fallback exists
    for.
    """

    slug = "a-product-channel"

    def send(self, *, message: Message, subject: str, body: str, nonce: str = "") -> Any:
        raise AssertionError("this transport is here to be asked about drops, not to send")

    def normalize_status(self, *, payload: dict[str, Any]) -> Any:
        return None


def test_a_transport_that_explains_nothing_still_gets_a_named_drop() -> None:
    """The fallback, exercised — because a fallback nobody drives is a hope.

    A transport is never *required* to account for its own silence: a vendor's
    receipt vocabulary is the product's to write and this app will not invent
    one. It must still never produce a nameless drop, so `status_drop` reads
    what this door can see for itself — whether the body arrived carrying the
    vocabulary the contract asks for.

    *Absent:* the new names exist only for the transports that opted in, and a
    product's own adapter keeps the old `ignored`-over-nothing behaviour.
    """
    silent = SilentTransport()
    assert not isinstance(silent, ExplainsStatusDrops)

    assert status_drop(silent, payload={"event_type": "opened"}) == StatusDrop(
        reason=DROP_NON_TERMINAL, event_type="opened"
    )
    assert status_drop(silent, payload={"vendor_says": "delivered"}) == StatusDrop(
        reason=DROP_UNTRANSLATABLE, event_type=""
    )

    # And the fake SMS transport, which delegates, answers in the shipped SMS vocabulary.
    assert isinstance(FakeSmsChannel(), ExplainsStatusDrops)
    assert status_drop(FakeSmsChannel(), payload={"MessageStatus": "delivered"}) == StatusDrop(
        reason=DROP_NO_MESSAGE_ID, event_type="delivered"
    )


def test_a_status_provider_registered_after_ready_reaches_every_registry() -> None:
    """One call writes the slug's channel, its handler and its verifier — at any moment."""
    from apps.comms.providers import (
        STATUS_PROVIDERS,
        handle_status_webhook,
        register_status_provider,
        verify_sms_webhook,
    )
    from apps.connections.providers import (
        inbound_handler,
        unregister_inbound_handler,
        unregister_webhook_verifier,
        webhook_verifier,
    )

    try:
        register_status_provider("a-product-sms", "sms", verify_sms_webhook)

        assert STATUS_PROVIDERS["a-product-sms"] == "sms"
        assert inbound_handler("a-product-sms") is handle_status_webhook
        assert webhook_verifier("a-product-sms") is verify_sms_webhook
    finally:
        STATUS_PROVIDERS.pop("a-product-sms", None)
        unregister_inbound_handler("a-product-sms")
        unregister_webhook_verifier("a-product-sms")
