"""The suppression wall is not a weapon — ADR comms-9.

An earlier investigation proved the signed status webhook had become a **denial-of-comms
primitive**, in two halves that compound:

* **(a) the collapsed bounce set.** ADR comms-8 made every `bounced` — and the
  `complained` and `rejected` that collapse onto it — suppress the address,
  tenant-wide, under the root-hat system actor. A *soft* bounce is a mailbox
  that was full for an hour, and it silenced a healthy recipient for ever;
* **(b) the forwardable key.** `EmailChannel` printed the `provider_message_id`
  into every delivered mail as its `Message-ID` header, so a forwarded receipt
  handed the recipient's suppression key to whoever read it.

ADR comms-9 closes the cheap half of both and announces the rest:

1. `bounced` carries a `BounceKind`, and only **hard** suppresses;
2. the composed mail no longer echoes the key — it lives in our storage;
3. a **mass-suppression tripwire** — `SURGE_THRESHOLD` suppressions on one
   connection in a trailing hour — emits `comms.suppression.surged` **once** on
   crossing and `comms.suppression.recovered` **once** on the first hour back
   under it. Transitions only (the announce-on-transition ruling);
   the open `SuppressionSurge` row is the announcement's memory, so a
   re-probing attacker cannot make it spam.

The first two tests in this module were each run on the pre-fix tree and each
failed there, which is what makes them evidence rather than decoration.

Everything that can go over the wire does: the bounce tests drive the real
signed receiver in `apps/connections`, exactly as `test_delivery_status.py`
does, because the seam worth proving is a payload from somebody else's server
reaching a service through a signature check and a registry.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from typing import Any

import pytest
from django.core import mail
from django.test import Client
from django.utils import timezone

from apps.comms import services
from apps.comms.models import (
    BounceKind,
    Channel,
    ChannelPreference,
    Message,
    MessageTemplate,
    Recipient,
    SuppressionSurge,
)
from apps.comms.providers import STATUS_PROVIDER, EmailChannel
from apps.connections.api import SIGNATURE_HEADER, SIGNATURE_PREFIX
from apps.connections.models import Connection
from apps.connections.services import create_connection
from apps.core.actor import Actor, system_actor
from apps.core.audit import AuditEntry
from apps.core.models import Tenant
from apps.core.services import root_organization
from apps.events.models import Event

pytestmark = pytest.mark.django_db

JSON = "application/json"

#: This module's own shared secret for the ESP connection — a different string
#: from the one `test_delivery_status.py` uses, so a test here cannot pass
#: because of a fixture over there. detect-secrets' documented pragma rather
#: than a `.secrets.baseline` entry: the baseline is a shared file at the root
#: of the tree and this app owns neither it nor the right to conflict four
#: other lanes on it.
STATUS_SECRET = "this-rung-signs-with-its-own-string"  # pragma: allowlist secret


# --- the door, the same one every status test drives -----------------------------


def signature(body: bytes) -> str:
    return SIGNATURE_PREFIX + hmac.new(STATUS_SECRET.encode(), body, hashlib.sha256).hexdigest()


def post_status(api: Client, connection: Connection, payload: dict[str, Any]) -> Any:
    """One signed status delivery, exactly as a provider would send it."""
    body = json.dumps(payload).encode()
    return api.post(
        f"/api/v1/connections/{connection.pk}/webhook/",
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: signature(body), "X-Event-Type": "delivery"},
    )


def tracking_event(message: Message, event_type: str, **extra: Any) -> dict[str, Any]:
    """An Anymail-normalised tracking event for a message this product sent."""
    return {
        "event_type": event_type,
        "message_id": message.provider_message_id,
        "timestamp": "2026-08-22T09:00:00+00:00",
        **extra,
    }


# --- fixtures --------------------------------------------------------------------


@pytest.fixture
def esp(tenant: Tenant, owner_actor: Actor) -> Connection:
    """The tenant's connection to its email provider, holding the webhook secret."""
    return create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider=STATUS_PROVIDER,
        name="Transactional email",
        credentials={"webhook_secret": STATUS_SECRET, "access_token": "an-esp-key"},
    )


def sent_message(*, tenant: Tenant, actor: Actor, recipient: Recipient) -> Message:
    """A message a transport has accepted — the state a status webhook arrives on.

    Built through the services rather than by writing a row, for the reason
    `test_delivery_status.py` states: a hand-written pair can be a state the
    product cannot actually produce, and every assertion after it would be
    about a world that does not occur.
    """
    message = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel=Channel.EMAIL,
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


def preference_for(tenant: Tenant, recipient: Recipient) -> ChannelPreference | None:
    """This person's email preference row for this tenant, or the absence of one.

    Read through the tenant manager rather than through a hat, the same call
    `test_delivery_status.py` makes and for the same reason: the question is
    "does a row exist anywhere in this tenant", and reading with a hat would
    let a suppression written into the wrong branch look like no suppression.
    """
    return (
        ChannelPreference.objects.for_tenant(tenant)
        .filter(recipient=recipient, channel=Channel.EMAIL)
        .first()
    )


def events(tenant: Tenant, name: str) -> list[Event]:
    return list(Event.objects.for_tenant(tenant).filter(name=name).order_by("created_at"))


# --- C1-1(a) / C1-2: the split bites ----------------------------------------------


def test_a_soft_bounce_records_the_kind_and_suppresses_nobody(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
    recipient: Recipient,
    receipt: MessageTemplate,
    message: Message,
) -> None:
    """**A full mailbox is not a dead address.**

    Anymail normalises the ESP's own reason into `reject_reason`, and
    `timed_out` is its word for "we retried and gave up" — transient by
    definition. Before ADR comms-9 this webhook suppressed the recipient
    tenant-wide, which is the cheap half of the risk: any forwarded receipt plus one
    soft-bounce-shaped payload silenced a healthy person for ever.

    The bounce is still **recorded** — the status, the reason and now the kind —
    because "this address is having trouble" is a fact a support agent reads.
    What it no longer does is act.

    Absent: the cheap half of the risk — the wall is a weapon anybody holding a message id
    can fire, and a real ESP's ordinary soft bounces silence real customers.
    """
    assert preference_for(tenant, recipient) is None, (
        "nothing has been said about this address yet, so any row below is this bounce's work"
    )

    response = post_status(api, esp, tracking_event(message, "bounced", reject_reason="timed_out"))
    assert response.status_code == 202

    row = reread(tenant, message)
    assert row.status == Message.Status.BOUNCED, "the report is still recorded faithfully"
    assert row.bounce_kind == BounceKind.SOFT, "and it is recorded as the kind it was"

    assert preference_for(tenant, recipient) is None, "a soft bounce suppressed an address"
    assert not AuditEntry.objects.filter(action="comms.suppress_recipient").exists()

    later = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert later.status == Message.Status.QUEUED, "the next send to a healthy address proceeds"


def test_a_delivered_mail_does_not_carry_the_suppression_key(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """C1-1(b) red first, C1-3. **The key stops being forwardable.**

    `EmailChannel` used to set `Message-ID` to the very string it records as
    `provider_message_id`, so the value the status webhook joins on was printed
    into every mail this product sends. A recipient forwarding a receipt handed
    their own suppression key to whoever read it — SEC-1's vector (b).

    The grep is over the **whole composed MIME**, headers and body together,
    because "we removed it from the body" would be a fix on one of the two
    places it appeared. Django still stamps its own random `Message-ID` on the
    way out, so the mail stays RFC-shaped; what is gone is *ours*.

    Absent: vector (b) survives and ADR comms-9's de-fanging claim is prose.
    """
    message = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    mail.outbox.clear()

    sent = EmailChannel().send(
        message=message,
        subject=message.subject,
        body="Hello Ada, here is your receipt.",
    )

    assert len(mail.outbox) == 1, "the transport composed exactly one mail"
    composed = mail.outbox[0].message().as_bytes()
    assert sent.provider_message_id, "the product still has a handle for this message"
    assert sent.provider_message_id.encode() not in composed, (
        "the suppression key is printed in the mail this person can forward"
    )
    assert str(message.pk).encode() not in composed, (
        "the id the key is derived from is printed in the mail, which is the same leak"
    )
    assert b"Message-ID:" in composed, "the mail is still RFC-shaped; the id is just not ours"


def test_a_hard_bounce_still_suppresses_exactly_as_it_did(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
    recipient: Recipient,
    receipt: MessageTemplate,
    message: Message,
) -> None:
    """C1-2, R2-2's assertions kept verbatim. **The split narrowed one half only.**

    The negative the soft-bounce test would pass without: a wall that stopped
    suppressing altogether would satisfy "a soft bounce suppresses nobody" and
    would have re-opened the dead-address finding — the product cheerfully mailing
    addresses that are provably dead.

    Absent: ADR comms-9 traded the widening for the wall.
    """
    response = post_status(api, esp, tracking_event(message, "bounced", reject_reason="invalid"))
    assert response.status_code == 202

    row = reread(tenant, message)
    assert row.status == Message.Status.BOUNCED
    assert row.bounce_kind == BounceKind.HARD

    suppressed = preference_for(tenant, recipient)
    assert suppressed is not None and suppressed.suppressed_at is not None
    assert suppressed.organization_id == recipient.organization_id

    audited = AuditEntry.objects.filter(action="comms.suppress_recipient").get()
    assert audited.actor_kind == "system", "nobody clicked this; the transport said it"
    assert audited.actor_user_id is None

    later = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert later.status == Message.Status.SUPPRESSED
    assert later.suppressed_reason == Message.SuppressedReason.SUPPRESSED


@pytest.mark.parametrize("event_type", ["complained", "rejected"])
def test_a_complaint_and_a_rejection_are_hard_whatever_the_reason_says(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    recipient: Recipient,
    receipt: MessageTemplate,
    message: Message,
    event_type: str,
) -> None:
    """C1-2's third clause. **`complained` and `rejected` are unchanged.**

    Both are read by their *event type*, before `reject_reason` is consulted at
    all — which is why the payload here carries a soft-looking one. A spam
    complaint is not a mail server having a bad hour, and an ESP refusing to
    carry the message is not either; reading the reason on these two would let a
    provider's stray field turn a complaint into an advisory.

    **The suppression is what "unchanged" means, and F1m kept it** (ADR comms-9,
    amended): a complaint now silences the address without transitioning the
    message, so the row assertion forks below while the assertion this test
    exists for — the address is silenced, whatever the reason field said — holds
    for both words exactly as it did.

    Absent: the split leaks past the half ADR comms-9 declared, and the two
    strongest signals a mailbox can send become suggestions.
    """
    response = post_status(api, esp, tracking_event(message, event_type, reject_reason="timed_out"))
    assert response.status_code == 202

    row = reread(tenant, message)
    if event_type == "complained":
        assert row.status == Message.Status.SENT, "a complaint is not delivery news"
        assert row.bounce_kind is None, "and carries no kind onto the row"
    else:
        assert row.status == Message.Status.BOUNCED
        assert row.bounce_kind == BounceKind.HARD, "the event type decided, not the reason"

    suppressed = preference_for(tenant, recipient)
    assert suppressed is not None and suppressed.suppressed_at is not None


def test_an_unclassified_bounce_takes_the_conservative_direction(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    recipient: Recipient,
    receipt: MessageTemplate,
    message: Message,
) -> None:
    """C1-2's edge. **"The provider did not say" is not "it was soft".**

    A `bounced` event with no `reject_reason` — most ESPs, most of the time — is
    recorded hard and suppresses, which is what ADR comms-8 already did for the
    whole set and what comms-9 keeps for the part nobody classified. The
    asymmetry is the reason: a wrongly-suppressed address lifts through one
    service call, and a wrongly-mailed dead address is a sender reputation.

    Absent: the split becomes a bypass — every real ESP that reports a bare
    `bounced` stops suppressing, and the dead-address finding is back for the majority
    of traffic rather than closed.
    """
    assert post_status(api, esp, tracking_event(message, "bounced")).status_code == 202

    row = reread(tenant, message)
    assert row.bounce_kind == BounceKind.HARD
    suppressed = preference_for(tenant, recipient)
    assert suppressed is not None and suppressed.suppressed_at is not None


# --- C1-3: the key is gone, and the webhook still lands ---------------------------


def test_the_status_webhook_still_resolves_a_delivery_without_the_echo(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    recipient: Recipient,
    receipt: MessageTemplate,
    message: Message,
) -> None:
    """C1-3's second half. **The id lives in our storage, not in the inbox.**

    Removing the echo would be a fix and a regression together if the join went
    with it. It does not: `provider_message_id` is still minted deterministically
    from the row and still recorded, so an ESP that reports our identifier still
    finds its message. What changed is only where the string is *published*.

    Absent: the de-fanging costs the status contract, and every delivery report
    lands as `unknown_message` in a log line nobody reads.
    """
    assert message.provider_message_id, "the row carries the handle"

    assert post_status(api, esp, tracking_event(message, "delivered")).status_code == 202

    row = reread(tenant, message)
    assert row.status == Message.Status.DELIVERED
    assert row.delivered_at is not None
    assert row.bounce_kind is None, "a delivery is not a bounce and carries no kind"
    assert [str(event.payload["id"]) for event in events(tenant, "comms.message.delivered")] == [
        str(message.pk)
    ]


# --- C1-4, C1-5, C1-6: the tripwire -----------------------------------------------


def bounce_one_address(
    *,
    api: Client,
    tenant: Tenant,
    actor: Actor,
    esp: Connection,
    index: int,
) -> Message:
    """One whole address silenced by a hard bounce, over the real signed door.

    A new recipient each time, because the tripwire counts **distinct
    addresses** — one person whose four in-flight messages all bounce is one
    person, and a counter that said four would let an ordinary fan-out trip an
    alarm about an attack.
    """
    recipient = services.create_recipient(
        tenant=tenant, actor=actor, email=f"bounce-{index}@example.com"
    )
    message = sent_message(tenant=tenant, actor=actor, recipient=recipient)
    assert post_status(api, esp, tracking_event(message, "bounced")).status_code == 202
    return message


def surges(tenant: Tenant) -> list[SuppressionSurge]:
    return list(SuppressionSurge.objects.for_tenant(tenant).order_by("created_at"))


def test_the_tripwire_announces_the_crossing_exactly_once(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
    receipt: MessageTemplate,
) -> None:
    """C1-4. **A degradation is a state the system announces, not a stream.**

    `SURGE_THRESHOLD` addresses silenced on one connection inside an hour opens
    a `SuppressionSurge` and says so once on the spine. The five suppressions
    *past* the threshold are the point of the test rather than padding: they are
    the re-probe-flapping case the announce-on-transition ruling names, and each
    of them must say nothing at all.

    Absent: the owner's scar, verbatim — the wall goes mad, the system tolerates
    it silently, and users report "comms sucks" before any human knows. Or the
    other failure of the same shape: an event per suppression, an alert channel
    nobody can read, and the surge that matters buried in it.
    """
    for index in range(services.SURGE_THRESHOLD - 1):
        bounce_one_address(api=api, tenant=tenant, actor=owner_actor, esp=esp, index=index)

    assert surges(tenant) == [], "under the threshold there is nothing to announce"
    assert events(tenant, "comms.suppression.surged") == []

    bounce_one_address(
        api=api, tenant=tenant, actor=owner_actor, esp=esp, index=services.SURGE_THRESHOLD - 1
    )

    opened = surges(tenant)
    assert len(opened) == 1, "the crossing opened exactly one episode"
    assert opened[0].connection_id == esp.pk
    assert opened[0].ended_at is None
    assert opened[0].suppression_count == services.SURGE_THRESHOLD

    announced = events(tenant, "comms.suppression.surged")
    assert len(announced) == 1, "the crossing was announced exactly once"
    payload = announced[0].payload
    assert payload["v"] == 1
    assert payload["connection_id"] == str(esp.pk)
    assert payload["threshold"] == services.SURGE_THRESHOLD
    assert payload["window_seconds"] == int(services.SURGE_WINDOW.total_seconds())
    assert payload["suppression_count"] == services.SURGE_THRESHOLD
    assert payload["ended_at"] is None

    for extra in range(5):
        bounce_one_address(
            api=api,
            tenant=tenant,
            actor=owner_actor,
            esp=esp,
            index=services.SURGE_THRESHOLD + extra,
        )

    assert len(surges(tenant)) == 1, "a re-probe opened a second episode"
    assert len(events(tenant, "comms.suppression.surged")) == 1, (
        "the wall announced a state that had not changed — the flapping the ruling refuses"
    )
    assert surges(tenant)[0].suppression_count == services.SURGE_THRESHOLD + 5, (
        "the open row did not follow the worst hour it had seen"
    )


def test_the_recovery_is_announced_once_when_the_hour_drains(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
    receipt: MessageTemplate,
) -> None:
    """C1-4's other half. **An alarm that cannot be lowered is an alarm ignored.**

    The window is trailing, so a surge recovers when the hour behind the next
    recording is back under the threshold. Time is moved by ageing the rows the
    count reads — `QuerySet.update`, the house's way around an `auto_now`
    column — rather than by waiting an hour or by patching a clock the service
    does not own.

    Absent: `comms.suppression.surged` is a one-way latch, the alert stays lit
    after the incident, and the next real surge arrives into a channel somebody
    has already muted.
    """
    for index in range(services.SURGE_THRESHOLD):
        bounce_one_address(api=api, tenant=tenant, actor=owner_actor, esp=esp, index=index)

    assert len(events(tenant, "comms.suppression.surged")) == 1
    open_surge = surges(tenant)[0]
    assert open_surge.ended_at is None

    # The hour drains: every bounce so far now sits outside the trailing window.
    aged = timezone.now() - services.SURGE_WINDOW - timedelta(minutes=5)
    Message.objects.for_tenant(tenant).filter(status=Message.Status.BOUNCED).update(bounced_at=aged)

    bounce_one_address(
        api=api, tenant=tenant, actor=owner_actor, esp=esp, index=services.SURGE_THRESHOLD
    )

    closed = surges(tenant)
    assert len(closed) == 1, "recovery closed the episode rather than opening another"
    assert closed[0].pk == open_surge.pk
    assert closed[0].ended_at is not None

    recovered = events(tenant, "comms.suppression.recovered")
    assert len(recovered) == 1, "the recovery was announced exactly once"
    assert recovered[0].payload["connection_id"] == str(esp.pk)
    assert recovered[0].payload["ended_at"] is not None
    assert len(events(tenant, "comms.suppression.surged")) == 1, "and nothing re-surged"


def test_the_tripwire_is_not_a_bypass(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
    receipt: MessageTemplate,
) -> None:
    """C1-5. **The alarm is not the attack's off switch.**

    ADR comms-9 rejected auto-halting suppression above the threshold in as many
    words, and this is the assertion that keeps the rejection true: while a
    surge is open, a hard bounce still suppresses its address and still counts.
    A tripwire that quietly disabled the wall would be a better weapon than the
    one it was built to watch for — a single burst, and then every dead address
    in the tenant is mailable again.

    Absent: the ADR's rejected shape, live.
    """
    for index in range(services.SURGE_THRESHOLD):
        bounce_one_address(api=api, tenant=tenant, actor=owner_actor, esp=esp, index=index)
    assert surges(tenant)[0].ended_at is None, "the surge is open for the assertion below"

    during = services.create_recipient(
        tenant=tenant, actor=owner_actor, email="during-the-surge@example.com"
    )
    message = sent_message(tenant=tenant, actor=owner_actor, recipient=during)
    assert post_status(api, esp, tracking_event(message, "bounced")).status_code == 202

    suppressed = preference_for(tenant, during)
    assert suppressed is not None and suppressed.suppressed_at is not None, (
        "the wall stopped working the moment somebody made it fire"
    )
    assert surges(tenant)[0].suppression_count == services.SURGE_THRESHOLD + 1, (
        "and the suppression during a surge was not counted"
    )

    later = services.send(
        recipient=during,
        template="receipt",
        context={"name": "Ada"},
        channel=Channel.EMAIL,
        tenant=tenant,
        actor=owner_actor,
    )
    assert later.status == Message.Status.SUPPRESSED


def test_a_closed_surge_is_history_and_a_second_flood_is_a_second_row(
    tenant: Tenant,
    other_tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
) -> None:
    """C1-6. **Closed rows are not rewritten, and the ledger is tenant-scoped.**

    Two properties in one test because they are one design decision: an episode
    is a row, so the next episode is the next row, and the uniqueness that keeps
    one *open* per connection is conditional on exactly that. Rewriting the
    closed one would collapse two incidents into a single misleading duration.

    The tenant half is the spot check house rule 8 asks for on any new scoped
    model: `SuppressionSurge` is read through `for_tenant`, and another tenant's
    manager returns nothing.

    Absent: a surge ledger that rewrites itself, and a scoped model whose reads
    were never proved to be scoped.
    """
    acting = system_actor(tenant, root_organization(tenant=tenant))

    first = services.start_suppression_surge(
        tenant=tenant, actor=acting, connection=esp, count=services.SURGE_THRESHOLD
    )
    closed = services.close_suppression_surge(
        tenant=tenant, actor=acting, surge=first, count=services.SURGE_THRESHOLD - 10
    )
    assert closed.ended_at is not None
    ended_at, count = closed.ended_at, closed.suppression_count
    assert count == services.SURGE_THRESHOLD, "the peak stands; a recovery does not lower it"

    second = services.start_suppression_surge(
        tenant=tenant, actor=acting, connection=esp, count=services.SURGE_THRESHOLD + 3
    )
    assert second.pk != first.pk, "a second flood reopened the first episode"

    settled = SuppressionSurge.objects.for_tenant(tenant).get(pk=first.pk)
    assert (settled.ended_at, settled.suppression_count) == (ended_at, count), (
        "the closed episode moved"
    )

    assert set(SuppressionSurge.objects.for_tenant(tenant).values_list("pk", flat=True)) == {
        first.pk,
        second.pk,
    }
    assert not SuppressionSurge.objects.for_tenant(other_tenant).exists(), (
        "another tenant's manager can see this tenant's surges"
    )


# --- F1m: what the split cost the tripwire, declared rather than discovered --------


def complain_about_one_address(
    *,
    api: Client,
    tenant: Tenant,
    actor: Actor,
    esp: Connection,
    index: int,
) -> Message:
    """One whole address silenced by a spam complaint, over the real signed door."""
    recipient = services.create_recipient(
        tenant=tenant, actor=actor, email=f"complaint-{index}@example.com"
    )
    message = sent_message(tenant=tenant, actor=actor, recipient=recipient)
    assert post_status(api, esp, tracking_event(message, "complained")).status_code == 202
    return message


def test_a_flood_of_complaints_silences_everybody_and_does_not_yet_trip_the_wire(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
    receipt: MessageTemplate,
) -> None:
    """F1m's declared blind spot, pinned so that closing it is a red test and not a guess.

    ADR comms-9's tripwire counts **distinct addresses a reported hard bounce
    has silenced** and it counts them off `Message` — `status=bounced`,
    `bounce_kind=hard`, `bounced_at` inside the trailing hour
    (`_suppressed_addresses_since`). The split gives a complaint none of those
    three, by design and without a column, so a flood made **only** of
    complaints suppresses every address and opens no surge.

    The call is not skipped — `_record_complaint` runs `_note_suppression` with
    the same connection a bounce would, so the mechanism is intact and only the
    population is short. **This is the rung's STOP clause firing on one clause of
    the criteria's negatives**, which asked for the complaint to be counted
    exactly as a hard bounce is: the counter is a trailing-window read over a
    timestamped population, and after the split a complaint has no timestamp of
    its own — that is a `complained_at` column (P5's, on comms-9's named
    trigger). The audit trail cannot stand in: `AuditEntry.object_id` holds the
    `ChannelPreference` a suppression returned and not the address, so "how many
    distinct addresses" is not a question that table answers.

    Absent: the wall's alarm quietly stops seeing the half of its traffic that
    is easiest to forge, and nobody finds out until an incident.
    """
    for index in range(services.SURGE_THRESHOLD + 5):
        complain_about_one_address(api=api, tenant=tenant, actor=owner_actor, esp=esp, index=index)

    silenced = ChannelPreference.objects.for_tenant(tenant).filter(
        suppressed_at__isnull=False, channel=Channel.EMAIL
    )
    assert silenced.count() == services.SURGE_THRESHOLD + 5, "the wall did its own job"

    assert surges(tenant) == [], (
        "the tripwire has started counting complaints — good; update this test and "
        "the blind spot in `_record_complaint`"
    )
    assert events(tenant, "comms.suppression.surged") == []


def test_a_flood_of_bounces_still_trips_the_wire_beside_the_complaints(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
    receipt: MessageTemplate,
) -> None:
    """The other half of the blind spot: the bounce population is untouched.

    A mixed flood is the realistic one, and it still announces itself — on its
    bounces. This is what keeps the blind spot above a *narrowing* of the alarm
    rather than the loss of it.

    Absent: the split reached the bounce counter too, and comms-9's tripwire is
    dead rather than short-sighted.
    """
    for index in range(services.SURGE_THRESHOLD - 1):
        complain_about_one_address(api=api, tenant=tenant, actor=owner_actor, esp=esp, index=index)
    for index in range(services.SURGE_THRESHOLD):
        bounce_one_address(api=api, tenant=tenant, actor=owner_actor, esp=esp, index=index)

    opened = surges(tenant)
    assert len(opened) == 1, "the bounces announced themselves"
    assert opened[0].suppression_count == services.SURGE_THRESHOLD, (
        "the count is the bounce population, exactly as comms-9 defined it"
    )
