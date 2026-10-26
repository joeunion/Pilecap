"""The ESP edge: a real provider's own signature, a real provider's own words.

`test_delivery_status.py` proves the status contract over payloads already
written in Anymail's normalised vocabulary and signed with this template's own
HMAC. Its module docstring names what it does not reach, and this module is
that gap closed:

> the ESP signature schemes real providers use (Mailgun's timestamp-token,
> SendGrid's ECDSA) are outside this door's one HMAC-over-body shape

**Every payload in this module is Resend's own shape** — `{"type":
"email.bounced", "data": {…}}` — and every request is signed the way Resend
signs, with Svix over `svix-id`, `svix-timestamp` and `svix-signature`. Nothing
here hand-writes an `event_type`: the translation into the three words this
product keeps is Anymail's, driven through `providers.esp_normalized`, which is
the same method Anymail's own webhook view would have called. That is ADR
comms-12's whole claim in a test file — *the seam is Anymail, the provider is
the product's `EMAIL_BACKEND`* — and it is why these tests are about the door
and the fork rather than about Resend.

**What is proven here and what is proven on the wire.** The signatures below are
computed with the vendor library, against a secret this module generates, over
bodies whose *shape* is Resend's. That makes them a proof of the mechanism, not
of the provider: E1′'s report carries the send that actually left through
Resend and the id Resend gave it back. A payload signed by Resend's own servers
needs a webhook endpoint only the account owner can create, which the rung's
report names as the item it stopped on.

**One mapping is absent and it is a finding, not an omission.** Anymail's Resend
adapter can produce only `BLOCKED`, `BOUNCED` or `OTHER` as a reject reason
(`anymail/webhooks/resend.py`), and all three are HARD here. Resend's
`email.delivery_delayed` normalises to `DEFERRED`, which is not terminal and is
dropped. So **Resend cannot produce a soft bounce through this seam at all** —
the soft half of ADR comms-9's fork stays proven by
`test_suppression_wall.py`'s fixtures, and a product on Resend should know that
its soft branch is unreachable rather than untested.
"""

from __future__ import annotations

import base64
import json
import secrets as _secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.core.mail import EmailMultiAlternatives, get_connection
from django.test import Client, override_settings
from svix.webhooks import Webhook as SvixWebhook

from apps.comms import services
from apps.comms.models import (
    BounceKind,
    Channel,
    ChannelPreference,
    Message,
    MessageTemplate,
    Recipient,
)
from apps.comms.providers import (
    STATUS_PROVIDER,
    EmailChannel,
    _accepted_handle,
    _anymail_esp,
    esp_normalized,
    verify_status_webhook,
)
from apps.connections.api import SIGNATURE_HEADER, SIGNATURE_PREFIX
from apps.connections.models import Connection, InboundWebhook
from apps.connections.providers import webhook_verifier
from apps.connections.services import create_connection
from apps.core.actor import Actor, system_actor
from apps.core.audit import AuditEntry
from apps.core.exceptions import Conflict
from apps.core.models import Tenant
from apps.core.services import root_organization
from apps.events.models import Event

pytestmark = pytest.mark.django_db

JSON = "application/json"

#: The backend that makes `_anymail_esp()` answer `"resend"`. It is the setting
#: and only the setting — no code path in this repository branches on the word.
RESEND_BACKEND = "anymail.backends.resend.EmailBackend"

#: Resend's simulator addresses, which is what E1′ drove the live send at.
BOUNCE_SIMULATOR = "bounced@resend.dev"

#: Resend's complaint simulator, and the address E1′'s live drive reported from.
COMPLAINT_SIMULATOR = "complained@resend.dev"

#: A secret belonging to some *other* integration, for the test that proves the
#: template's own HMAC door is untouched here. The pragma is
#: detect-secrets' documented mitigation and matches `test_delivery_status.py`'s
#: convention: a line-scoped comment rather than a `.secrets.baseline` entry,
#: because the baseline is a shared file four lanes would conflict on.
OTHER_SECRET = "a-secret-of-its-own"  # noqa: S105 — a signing secret the test both signs and verifies with  # pragma: allowlist secret


def whsec() -> str:
    """A Svix signing secret in the shape Resend hands one out in.

    Generated per call rather than pinned, so nothing in this file is a string
    that could be mistaken for a credential somebody has to rotate.
    """
    return "whsec_" + base64.b64encode(_secrets.token_bytes(24)).decode()


def svix_headers(
    *, secret: str, body: bytes, when: datetime | None = None, msg_id: str = ""
) -> dict[str, str]:
    """The three headers Resend puts on a webhook, computed with the vendor's own code."""
    moment = when or datetime.now(tz=UTC)
    identifier = msg_id or f"msg_{uuid4().hex[:20]}"
    signature = SvixWebhook(secret).sign(msg_id=identifier, timestamp=moment, data=body.decode())
    return {
        "svix-id": identifier,
        "svix-timestamp": str(int(moment.timestamp())),
        "svix-signature": signature,
    }


def resend_event(
    kind: str, *, email_id: str, to: str = "ada@example.com", **data: Any
) -> dict[str, Any]:
    """One webhook body in **Resend's** shape. No Anymail key anywhere in it."""
    return {
        "type": kind,
        "created_at": "2026-08-22T02:00:00.000Z",
        "data": {
            "email_id": email_id,
            "to": [to],
            "created_at": "2026-08-22T01:59:00.000Z",
            **data,
        },
    }


HARD_BOUNCE_TEXT = (
    "The recipient's email provider sent a hard bounce message, and the address is not valid."
)


def complaint(email_id: str, *, to: str = COMPLAINT_SIMULATOR) -> dict[str, Any]:
    """`email.complained` in the shape Resend actually posts one.

    Taken from E1′'s live drive at the simulator address: a complaint carries no
    `bounce` block at all — the event type is the whole of the news — and the
    `data` block is the same envelope every other Resend event uses.
    """
    return resend_event(
        "email.complained",
        email_id=email_id,
        to=to,
        subject="Receipt",
        **{"from": "receipts@example.com"},
    )


# --- fixtures -------------------------------------------------------------------


@pytest.fixture
def signing_secret() -> str:
    return whsec()


@pytest.fixture
def esp(tenant: Tenant, owner_actor: Actor, signing_secret: str) -> Connection:
    """The tenant's Resend connection, holding the Svix signing secret on its row."""
    return create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider=STATUS_PROVIDER,
        name="Resend",
        credentials={"webhook_secret": signing_secret, "access_token": "an-esp-key"},
        is_signature_v2_required=False,
    )


@pytest.fixture
def email_id() -> str:
    """Resend's own handle for a message — a bare UUID, not our `<pk@domain>`."""
    return str(uuid4())


@pytest.fixture
def message(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    email_id: str,
) -> Message:
    """A message Resend accepted, recorded under **Resend's** id."""
    queued = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    return services.record_message_sent(
        tenant=tenant,
        actor=owner_actor,
        message=queued,
        provider="anymail:resend",
        provider_message_id=email_id,
    )


def post_resend(
    api: Client,
    connection: Connection,
    payload: dict[str, Any],
    *,
    secret: str,
    when: datetime | None = None,
    msg_id: str = "",
    tamper: bool = False,
) -> Any:
    """One Resend delivery at the real door, signed the way Resend signs.

    `tamper` alters the body **after** the signature is computed, which is the
    only honest way to write this test: a signature over one body and a request
    carrying another is exactly what an attacker who captured a delivery has.
    """
    body = json.dumps(payload).encode()
    headers = svix_headers(secret=secret, body=body, when=when, msg_id=msg_id)
    if tamper:
        altered = dict(payload)
        altered["type"] = "email.delivered"
        body = json.dumps(altered).encode()
    return api.post(
        f"/api/v1/connections/{connection.pk}/webhook/",
        data=body,
        content_type=JSON,
        headers=headers,
    )


def deliver(api: Client, esp: Connection, *, secret: str, email_id: str, msg_id: str = "") -> Any:
    """The delivery a complaint follows. Resend's own `email.delivered`."""
    return post_resend(
        api,
        esp,
        resend_event("email.delivered", email_id=email_id, to="delivered@resend.dev"),
        secret=secret,
        msg_id=msg_id,
    )


def reread(tenant: Tenant, message: Message) -> Message:
    return Message.objects.for_tenant(tenant).get(pk=message.pk)


def preference_for(tenant: Tenant, recipient: Recipient) -> ChannelPreference | None:
    return (
        ChannelPreference.objects.for_tenant(tenant)
        .filter(recipient=recipient, channel=Channel.EMAIL)
        .first()
    )


def events(tenant: Tenant, name: str) -> list[Event]:
    return list(Event.objects.for_tenant(tenant).filter(name=name))


# --- E1′-1: the handle that round-trips -----------------------------------------


def test_the_esp_is_read_off_the_setting_and_nothing_else() -> None:
    """ADR comms-12. The provider is `EMAIL_BACKEND`; no code path names Resend."""
    assert _anymail_esp() == "", "pytest is on locmem, which is not an ESP"
    with override_settings(EMAIL_BACKEND=RESEND_BACKEND):
        assert _anymail_esp() == "resend"
    with override_settings(EMAIL_BACKEND="anymail.backends.mailgun.EmailBackend"):
        assert _anymail_esp() == "mailgun", "the seam is Anymail's, not one vendor's"


@override_settings(EMAIL_BACKEND="anymail.backends.test.EmailBackend")
def test_the_handle_recorded_is_the_one_the_esp_gave_us(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """E1′-1's join, and the bug E1′ found.

    Every Anymail webhook reports status against the id the ESP returned when it
    accepted the message. Minting our own instead meant every real bounce would
    arrive naming a key no row holds: the message stays `sent` for ever, nobody
    is suppressed, and nothing anywhere says why.

    *Absent:* `provider_message_id` reads `<uuid@localhost>` after a send through
    an ESP, and the round trip is broken before it starts.
    """
    queued = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    accepted = EmailChannel().send(message=queued, subject="Receipt", body="Thanks, Ada.")

    assert accepted.provider == "anymail:test"
    assert not accepted.provider_message_id.startswith("<"), (
        "the ESP's own id was thrown away and ours minted over it"
    )
    assert str(queued.pk) not in accepted.provider_message_id


def test_a_backend_with_no_esp_id_still_gets_the_minted_handle(
    tenant: Tenant, owner_actor: Actor, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """The negative. Mailpit, locmem and plain SMTP report nothing, and still work."""
    queued = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    mail = EmailMultiAlternatives(subject="s", body="b", to=["ada@example.com"])
    assert _accepted_handle(mail=mail, message=queued) == f"<{queued.pk}@localhost>"


# --- E1′-2: the fork, over Resend's own vocabulary ------------------------------


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_a_resend_bounce_is_hard_and_suppresses_the_address(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
    signing_secret: str,
    recipient: Recipient,
    receipt: MessageTemplate,
    message: Message,
    email_id: str,
) -> None:
    """E1′-2. Resend's words in, this product's fork out.

    *Absent:* the Message stays `sent`, no `ChannelPreference` row exists, and
    the next send goes out to an address the provider just told us is dead.
    """
    assert preference_for(tenant, recipient) is None

    response = post_resend(
        api,
        esp,
        resend_event(
            "email.bounced",
            email_id=email_id,
            to=BOUNCE_SIMULATOR,
            bounce={"message": HARD_BOUNCE_TEXT},
        ),
        secret=signing_secret,
    )
    assert response.status_code == 202

    settled = reread(tenant, message)
    assert settled.status == Message.Status.BOUNCED
    assert settled.bounce_kind == BounceKind.HARD
    assert HARD_BOUNCE_TEXT[:20] in settled.error

    suppressed = preference_for(tenant, recipient)
    assert suppressed is not None and suppressed.suppressed_at is not None

    later = services.send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    assert later.status == Message.Status.SUPPRESSED


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_a_resend_complaint_is_read_by_its_own_event_type(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    signing_secret: str,
    recipient: Recipient,
    message: Message,
    email_id: str,
) -> None:
    """`email.complained` carries no bounce block at all — the event type decides.

    **Re-pointed by F1m** (ADR comms-9, amended). What the event type decides is
    no longer "this is a hard bounce" but "this is a complaint": the adapter
    still collapses it onto `bounced` so one suppression rule reads one word,
    and carries `is_complaint` out with it so the service suppresses without
    transitioning. The assertion that the *row* came out `bounced` is what the
    split removed, and the two tests below it are where the row's contract now
    lives.
    """
    read = EmailChannel().normalize_status(payload=complaint(email_id))
    assert read is not None
    assert read.status == Message.Status.BOUNCED.value, "the collapse is still the adapter's"
    assert read.bounce_kind == BounceKind.HARD, "hard by its event type, with no bounce block"
    assert read.is_complaint is True, "and marked as the consent news it is"

    response = post_resend(api, esp, complaint(email_id), secret=signing_secret)
    assert response.status_code == 202
    settled = reread(tenant, message)
    assert settled.status == Message.Status.SENT, "the row is not what a complaint is about"
    assert preference_for(tenant, recipient) is not None


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_a_resend_delivery_settles_the_row_and_suppresses_nobody(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    signing_secret: str,
    recipient: Recipient,
    message: Message,
    email_id: str,
) -> None:
    """The third arm of E1′-2's fork, and the one that must touch no wall."""
    response = post_resend(
        api,
        esp,
        resend_event("email.delivered", email_id=email_id, to="delivered@resend.dev"),
        secret=signing_secret,
    )
    assert response.status_code == 202
    assert reread(tenant, message).status == Message.Status.DELIVERED
    assert preference_for(tenant, recipient) is None
    assert reread(tenant, message).error == "", "a delivery wrote prose into the error column"


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_a_delayed_delivery_says_nothing_terminal(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    signing_secret: str,
    message: Message,
    email_id: str,
) -> None:
    """`email.delivery_delayed` → Anymail's `DEFERRED` → dropped, and the run waits.

    This is the mapping finding in the module docstring, asserted rather than
    described: Resend's only non-terminal delivery problem does not become a
    soft bounce here, because Anymail does not normalise it to one.
    """
    response = post_resend(
        api,
        esp,
        resend_event("email.delivery_delayed", email_id=email_id),
        secret=signing_secret,
    )
    assert response.status_code == 202
    assert reread(tenant, message).status == Message.Status.SENT
    assert InboundWebhook.objects.for_tenant(tenant).count() == 1, "the delivery is still stored"


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_the_anymail_mapping_is_pasted_by_the_translation_itself() -> None:
    """The mapping E1′ owes its report, read out of the code rather than typed."""
    translated = esp_normalized(
        resend_event("email.bounced", email_id="an-id", bounce={"message": HARD_BOUNCE_TEXT})
    )
    assert translated is not None
    assert translated["event_type"] == "bounced"
    assert translated["reject_reason"] == "bounced"
    assert translated["message_id"] == "an-id"

    suppressed_by_resend = esp_normalized(
        resend_event(
            "email.bounced",
            email_id="an-id",
            bounce={"message": "Resend has suppressed sending to this address"},
        )
    )
    assert suppressed_by_resend is not None
    assert suppressed_by_resend["reject_reason"] == "blocked", "still hard, by a different road"


# --- E1′-3: the signature, and the second delivery -------------------------------


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_a_tampered_body_is_refused_and_stores_nothing(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    signing_secret: str,
    recipient: Recipient,
    message: Message,
    email_id: str,
) -> None:
    """E1′-3. The signature is over the bytes, so changed bytes are a different message.

    *Absent:* a forged POST returns 2xx and anyone who learns the URL can settle
    — or suppress — a tenant's recipients.
    """
    response = post_resend(
        api,
        esp,
        resend_event("email.bounced", email_id=email_id, bounce={"message": HARD_BOUNCE_TEXT}),
        secret=signing_secret,
        tamper=True,
    )
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()
    assert reread(tenant, message).status == Message.Status.SENT
    assert preference_for(tenant, recipient) is None


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_a_signature_from_another_secret_is_refused(
    api: Client, tenant: Tenant, esp: Connection, message: Message, email_id: str
) -> None:
    """A well-formed Svix signature is not a credential unless it is *this* row's."""
    response = post_resend(
        api,
        esp,
        resend_event("email.bounced", email_id=email_id, bounce={"message": HARD_BOUNCE_TEXT}),
        secret=whsec(),
    )
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_a_stale_delivery_is_refused_by_the_vendors_own_window(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    signing_secret: str,
    message: Message,
    email_id: str,
) -> None:
    """Svix signs the timestamp too, so a captured delivery expires. We do not re-implement it.

    *Absent:* a delivery captured from a proxy log last week still settles a row
    today, which is a replay this door's own HMAC cannot see either.
    """
    response = post_resend(
        api,
        esp,
        resend_event("email.bounced", email_id=email_id, bounce={"message": HARD_BOUNCE_TEXT}),
        secret=signing_secret,
        when=datetime.now(tz=UTC) - timedelta(hours=2),
    )
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_the_same_delivery_twice_transitions_once_and_suppresses_once(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    signing_secret: str,
    recipient: Recipient,
    message: Message,
    email_id: str,
) -> None:
    """E1′-3's other half. Every ESP redelivers; one bounce is one bounce.

    *Absent:* the second delivery double-counts toward ADR comms-9's
    mass-suppression surge, and the spine carries two `comms.message.bounced`
    events for one fact.
    """
    payload = resend_event("email.bounced", email_id=email_id, bounce={"message": HARD_BOUNCE_TEXT})
    first = post_resend(api, esp, payload, secret=signing_secret, msg_id="msg_the_same_one")
    second = post_resend(api, esp, payload, secret=signing_secret, msg_id="msg_the_same_one")

    assert first.status_code == 202
    assert second.status_code == 202
    assert len(events(tenant, "comms.message.bounced")) == 1
    assert (
        ChannelPreference.objects.for_tenant(tenant)
        .filter(recipient=recipient, channel=Channel.EMAIL)
        .count()
        == 1
    )
    assert reread(tenant, message).status == Message.Status.BOUNCED


# --- F1m: a complaint is consent news, not delivery news --------------------------
#
# E1′'s live drive found the hole these tests close. A complaint **by
# definition follows a delivery**, and `record_delivery_status` gated every
# report on `OPEN_TO_STATUS = {queued, sending, sent}` — so
# `complained@resend.dev` came back `Conflict("That message is delivered and
# can no longer be bounced.")`, loudly, and nobody was suppressed. Zero
# preference rows for a person who had just reported us as spam.
#
# The split (ADR comms-9, amended): a complaint is a fact about **consent**, a
# bounce a fact about the **address**, a delivery a fact about the **message**.
# The complaint leaves the collapsed status set — it transitions nothing,
# always suppresses, and says so under its own name.


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_a_complaint_after_delivery_suppresses_and_leaves_the_message_delivered(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    esp: Connection,
    signing_secret: str,
    recipient: Recipient,
    receipt: MessageTemplate,
    message: Message,
    email_id: str,
) -> None:
    """F1m-1, red first. **The order a complaint actually arrives in.**

    The mail is delivered; the person then presses "report spam"; Resend posts
    `email.complained` against the same `email_id`. On the baseline tree the
    receiver's handler raised `Conflict("That message is delivered and can no
    longer be bounced.")`, the 202 stood because the door swallows a handler's
    exception into a savepoint, and **nothing was suppressed**.

    Afterwards the three facts are separate: the message is still `delivered`
    (the provider never said otherwise), the recipient's email channel is
    suppressed, and the complaint has its own name on the spine.

    *Absent:* a person who reported us as spam stays mailable — the owner's scar
    in the consent direction — or the Conflict, or a send that goes out.
    """
    assert deliver(api, esp, secret=signing_secret, email_id=email_id).status_code == 202
    delivered = reread(tenant, message)
    assert delivered.status == Message.Status.DELIVERED
    assert delivered.delivered_at is not None
    assert preference_for(tenant, recipient) is None, "the delivery suppressed nobody"

    response = post_resend(api, esp, complaint(email_id), secret=signing_secret)
    assert response.status_code == 202

    settled = reread(tenant, message)
    assert settled.status == Message.Status.DELIVERED, "a complaint is not delivery news"
    assert settled.delivered_at == delivered.delivered_at, "the delivery stamp was rewritten"
    assert settled.bounce_kind is None, "a complaint is not a bounce and carries no kind"
    assert settled.bounced_at is None

    suppressed = preference_for(tenant, recipient)
    assert suppressed is not None and suppressed.suppressed_at is not None

    complained = events(tenant, "comms.message.complained")
    assert len(complained) == 1, "the complaint has its own name or it has no name at all"
    assert complained[0].v == 1
    assert complained[0].payload["v"] == 1
    assert complained[0].payload["id"] == str(message.pk)
    assert complained[0].payload["status"] == "delivered", "the payload is the row's own truth"
    assert complained[0].payload["provider_message_id"] == email_id
    assert events(tenant, "comms.message.bounced") == [], "the message did not bounce"

    audited = AuditEntry.objects.filter(action="comms.suppress_recipient").get()
    assert audited.actor_kind == "system", "nobody clicked this; the transport said it"
    assert audited.door == "webhook"
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


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_a_complaint_against_a_sent_message_leaves_it_sent(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    signing_secret: str,
    recipient: Recipient,
    message: Message,
    email_id: str,
) -> None:
    """F1m-2. **The contract change, shown as one.**

    Before the split a complaint from `sent` transitioned the row to `bounced`
    and emitted `comms.message.bounced`; the sibling tests that asserted that
    are re-pointed in this same change. `sent` is what the provider last said
    about the message, and a complaint says nothing about the message — so the
    row stays `sent`, honestly, and the suppression happens all the same.

    *Absent:* the status flips to `bounced`, and a message the ESP accepted is
    logged as one it refused.
    """
    assert post_resend(api, esp, complaint(email_id), secret=signing_secret).status_code == 202

    settled = reread(tenant, message)
    assert settled.status == Message.Status.SENT
    assert settled.bounce_kind is None
    assert settled.bounced_at is None

    suppressed = preference_for(tenant, recipient)
    assert suppressed is not None and suppressed.suppressed_at is not None
    assert len(events(tenant, "comms.message.complained")) == 1
    assert events(tenant, "comms.message.bounced") == []


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_a_bounce_after_delivery_is_still_refused(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    signing_secret: str,
    recipient: Recipient,
    message: Message,
    email_id: str,
) -> None:
    """F1m-3. **The guard the split did not touch.**

    A delivered message did not bounce. The refusal is asserted against the
    service rather than the door because the receiver swallows a handler's
    exception into a savepoint by design — the 202 is about the *store*, and
    the sentence below is what the log carries.

    *Absent:* the complaint's exemption was written as an exemption for the
    whole settled-status guard, and a delivered message can be turned `bounced`
    by any signed report.
    """
    assert deliver(api, esp, secret=signing_secret, email_id=email_id).status_code == 202

    with pytest.raises(Conflict) as refused:
        services.record_delivery_status(
            tenant=tenant,
            actor=system_actor(tenant, root_organization(tenant=tenant)),
            provider_message_id=email_id,
            status=Message.Status.BOUNCED,
            bounce_kind=BounceKind.HARD,
        )
    assert str(refused.value) == "That message is delivered and can no longer be bounced."

    assert reread(tenant, message).status == Message.Status.DELIVERED
    assert preference_for(tenant, recipient) is None, "a refused bounce suppressed somebody"


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_the_same_complaint_twice_suppresses_once_and_says_so_once(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    signing_secret: str,
    recipient: Recipient,
    message: Message,
    email_id: str,
) -> None:
    """F1m-4, C4. **The provider event id is the key.**

    Every ESP redelivers, and Resend names each delivery with `svix-id`, which
    the receiver dedupes on (`inboundwebhook_unique_delivery_per_connection`).
    So the second copy of one complaint never reaches the service at all: one
    preference row, one event, one audit row.

    *Absent:* two `comms.message.complained` events for one fact, and a
    redelivery storm that reads on the spine as a complaint storm.
    """
    assert deliver(api, esp, secret=signing_secret, email_id=email_id).status_code == 202
    payload = complaint(email_id)
    first = post_resend(api, esp, payload, secret=signing_secret, msg_id="msg_one_complaint")
    second = post_resend(api, esp, payload, secret=signing_secret, msg_id="msg_one_complaint")

    assert (first.status_code, second.status_code) == (202, 202)
    assert len(events(tenant, "comms.message.complained")) == 1
    assert (
        ChannelPreference.objects.for_tenant(tenant)
        .filter(recipient=recipient, channel=Channel.EMAIL)
        .count()
        == 1
    )
    assert AuditEntry.objects.filter(action="comms.suppress_recipient").count() == 1
    assert reread(tenant, message).status == Message.Status.DELIVERED


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_every_resend_bounce_shape_is_hard_so_the_soft_branch_is_unreachable() -> None:
    """F1m-5. The module docstring's finding, pinned rather than described.

    Anymail's Resend adapter (`anymail/webhooks/resend.py`) reads the bounce
    kind out of one human-readable sentence and can produce exactly three
    reject reasons — `blocked`, `bounced`, `other` — plus `None` when the event
    carries no `bounce` block at all. `BOUNCE_KIND` maps the first two hard;
    the other two come back empty and `services` resolves *that* to hard. There
    is no road from a Resend payload to `soft`, and `RejectReason.TIMED_OUT` —
    the only soft member — is a word this adapter never says.

    *Absent:* a product on Resend believes its soft branch is tested, and the
    day it swaps ESP nothing tells it which half was proven.
    """
    shapes = {
        "hard bounce": {"message": HARD_BOUNCE_TEXT},
        "general bounce": {
            "message": "The recipient's email provider sent a general bounce message."
        },
        "full mailbox": {
            "message": (
                "The recipient's email provider sent a bounce message because the "
                "recipient's inbox was full."
            )
        },
        "esp suppression": {"message": "Resend has suppressed sending to this address"},
        "unclassified": {"message": "Something Resend has not seen before."},
    }
    for name, block in shapes.items():
        status = EmailChannel().normalize_status(
            payload=resend_event("email.bounced", email_id="an-id", bounce=block)
        )
        assert status is not None, name
        assert status.status == Message.Status.BOUNCED.value, name
        assert status.bounce_kind != BounceKind.SOFT.value, f"{name} reached the soft branch"

    no_block = EmailChannel().normalize_status(
        payload=resend_event("email.bounced", email_id="an-id")
    )
    assert no_block is not None
    assert no_block.bounce_kind == "", "no bounce block means the provider did not say"


# --- the seam itself: three answers, and never a silent pass ---------------------


def test_comms_claimed_the_signature_check_at_startup() -> None:
    """The registration, asserted where a reader looks for it."""
    assert webhook_verifier(STATUS_PROVIDER) is verify_status_webhook


def test_the_verifier_has_no_opinion_when_there_is_no_esp(esp: Connection) -> None:
    """pytest is on locmem. `None` is the answer, and the door's HMAC decides."""
    assert verify_status_webhook(connection=esp, body=b"{}", headers={}) is None


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_the_verifier_has_no_opinion_when_the_connection_carries_no_secret(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """A revoked connection cannot be checked — and must never be waved through.

    *Absent:* `True` from a verifier that checked nothing, which is the one
    failure mode this three-valued protocol exists to make impossible.
    """
    bare = create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider=STATUS_PROVIDER,
        name="Resend, no secret",
        credentials={"access_token": "an-esp-key"},
        is_signature_v2_required=False,
    )
    assert verify_status_webhook(connection=bare, body=b"{}", headers={}) is None


@override_settings(EMAIL_BACKEND=RESEND_BACKEND)
def test_a_connection_with_no_secret_is_refused_at_the_door(
    api: Client, tenant: Tenant, owner_actor: Actor, message: Message, email_id: str
) -> None:
    """And the fallback the `None` lands on refuses too, because an empty secret is False."""
    bare = create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider=STATUS_PROVIDER,
        name="Resend, no secret",
        credentials={"access_token": "an-esp-key"},
        is_signature_v2_required=False,
    )
    response = post_resend(
        api,
        bare,
        resend_event("email.bounced", email_id=email_id, bounce={"message": HARD_BOUNCE_TEXT}),
        secret=whsec(),
    )
    assert response.status_code == 401
    assert not InboundWebhook.objects.for_tenant(tenant).exists()


def test_the_templates_own_hmac_still_carries_a_normalised_payload(
    api: Client,
    tenant: Tenant,
    esp: Connection,
    signing_secret: str,
    message: Message,
    email_id: str,
) -> None:
    """The negative that keeps the seam a seam.

    With no ESP configured — every laptop, every test run, every product that
    has not chosen one — the door is exactly what it was: an HMAC over the body,
    carrying an Anymail-normalised payload. Nothing about E1′ narrowed it.
    """
    import hashlib
    import hmac

    body = json.dumps(
        {
            "event_type": "delivered",
            "message_id": email_id,
            "timestamp": "2026-08-20T09:00:00+00:00",
        }
    ).encode()
    signature = (
        SIGNATURE_PREFIX + hmac.new(signing_secret.encode(), body, hashlib.sha256).hexdigest()
    )
    response = api.post(
        f"/api/v1/connections/{esp.pk}/webhook/",
        data=body,
        content_type=JSON,
        headers={SIGNATURE_HEADER: signature},
    )
    assert response.status_code == 202
    assert reread(tenant, message).status == Message.Status.DELIVERED


def test_a_connection_nobody_registered_a_verifier_for_is_unchanged(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """Most integrations are outbound-only or sign the template's way. They get the HMAC."""
    assert webhook_verifier("example") is None
    other = create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider="example",
        name="Something else",
        credentials={"webhook_secret": OTHER_SECRET},
        is_signature_v2_required=False,
    )
    assert other.webhook_secret == OTHER_SECRET


def test_the_email_backend_is_reachable_for_the_esp_this_cycle_proved() -> None:
    """Rule 23's other half in miniature: the extra actually landed and imports.

    *Absent:* `django-anymail[resend]` resolved but the vendor library did not,
    and every signature check silently becomes `None` — the fallback — in a
    deployment that believes it is verifying Resend.
    """
    absent = {"RESEND_API_KEY": "x"}  # pragma: allowlist secret — the backend never calls out here
    with override_settings(EMAIL_BACKEND=RESEND_BACKEND, ANYMAIL=absent):
        backend = get_connection()
    assert backend.__class__.__module__ == "anymail.backends.resend"
    assert SvixWebhook is not None


def test_the_anymail_internal_we_hold_still_exists() -> None:
    """The installed Anymail still names its signing secret where `SECRET_ATTR` reads it.

    A rename upstream would silently demote ESP signature checking to the house HMAC.
    """
    from apps.comms.providers import SECRET_ATTR, _esp_tracking_view_class

    view = _esp_tracking_view_class("resend")
    assert view is not None, "anymail.webhooks.resend has no tracking view"
    assert getattr(view, SECRET_ATTR, ""), f"{view.__name__} no longer declares {SECRET_ATTR}"
