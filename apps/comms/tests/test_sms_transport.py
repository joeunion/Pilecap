"""The SMS transport: Twilio's own words, Twilio's own signature.

ADR comms-9's channels half (ING-4 T2), and the wire half T1 left owed. T1 pinned
`record_delivery_status`'s STOP contract **at the service** — a complaint
suppresses the person and leaves the message row exactly where it was — and
proved, in its own frontier note, that no real opt-out could reach it: nothing on
the `sms` slot could read a word Twilio says. This module is that gap closed, and
every test here is one of four claims:

* **a real, vendor-signed STOP suppresses over the wire.** Twilio's own
  `X-Twilio-Signature`, over Twilio's own form body, through the one signed
  receiver this product has, into the service T1 pinned. The opt-out arrives as
  `MessageStatus=undelivered` with `ErrorCode=21610` against the sid of a message
  we sent, which is what a `STOP` text has become by the time Twilio tells us;
* **the signature is the vendor's and this repository signs nothing.** The check
  is `twilio.request_validator.RequestValidator` — the SDK's own
  compute-and-compare — exactly as the ESP door delegates Resend's Svix scheme to
  anymail (house rule 43's disposition here). The tests below sign with
  the same object, which is the only honest way to drive it;
* **`undelivered` is not one word.** An opt-out is consent news and leaves the
  row alone; a dead number is address news and bounces hard; an unreachable
  handset is soft and suppresses nobody; a `failed` is our own fault and touches
  neither the address nor the person's file;
* **the engagement path stays email-only, and says so.** SMS has no opens.
  `TwilioSmsChannel` deliberately does not implement `ReportsEngagement`, the
  same deliberate absence `FakeSmsChannel` carries, and the test at the foot of
  this module is that absence asserted rather than assumed.

**No vendor account is involved.** Signatures are computed with the vendor
library against a token this module generates, and the one send test drives the
SDK's own `http_client` seam with a recorded `Messages.json` response — the same
trade `test_esp_webhook.py` records for Resend: a proof of the mechanism, not of
the provider. What is NOT proven here is named in the rung's report: nobody has
pointed a real Twilio account at this door.
"""

from __future__ import annotations

import json
import logging
import secrets as _secrets
from typing import Any
from urllib.parse import parse_qsl, urlencode

import pytest
from django.conf import settings
from django.test import Client, override_settings
from django.urls import reverse
from twilio.http.response import Response as TwilioResponse
from twilio.request_validator import RequestValidator

from apps.comms import providers, services
from apps.comms.models import (
    BounceKind,
    Channel,
    ChannelPreference,
    Message,
    MessageEngagement,
    Recipient,
)
from apps.comms.providers import (
    SMS_STATUS_PROVIDER,
    TWILIO_SIGNATURE_HEADER,
    ReportsEngagement,
    TwilioSmsChannel,
    register_channel,
    registered_channels,
    status_callback_url,
)
from apps.connections.models import Connection, InboundWebhook
from apps.connections.services import create_connection
from apps.core.actor import Actor
from apps.core.exceptions import Invalid
from apps.core.models import Tenant
from apps.events.models import Event

pytestmark = pytest.mark.django_db

FORM = "application/x-www-form-urlencoded"

#: Twilio's account sid shape. Not a credential — the sid is public in every
#: Twilio URL — but generated rather than pinned so nothing here reads as one.
ACCOUNT_SID = "AC" + "0" * 32


def auth_token() -> str:
    """An auth token in the shape Twilio hands one out in, per run.

    Twilio's auth token is BOTH the API credential and the webhook signing key,
    which is the fact `_twilio_auth_token` exists for — see its docstring.
    """
    return _secrets.token_hex(16)


# --- the door, and the vendor's own signature -----------------------------------


def status_url(connection: Connection) -> str:
    """The path the test client posts to — the receiver's own route."""
    return reverse("api:connection-webhook", kwargs={"connection_id": connection.pk})


def twilio_signature(*, token: str, url: str, fields: dict[str, str]) -> str:
    """The header Twilio would send, computed with the vendor's own code."""
    return str(RequestValidator(token).compute_signature(url, fields))


def post_twilio(
    api: Client,
    connection: Connection,
    fields: dict[str, str],
    *,
    token: str,
    url: str = "",
    tamper: bool = False,
) -> Any:
    """One Twilio delivery at the real door, signed the way Twilio signs.

    `url` overrides what the signature is computed over, which is how the
    wrong-`PUBLIC_BASE_URL` case is driven: Twilio signs the URL it was given,
    so a deployment whose public URL has moved verifies nothing.

    `tamper` alters a field **after** the signature is computed — a signature
    over one body and a request carrying another, which is exactly what somebody
    who captured a delivery has.
    """
    signed = url or status_callback_url(connection)
    signature = twilio_signature(token=token, url=signed, fields=fields)
    sent = dict(fields)
    if tamper:
        sent["MessageStatus"] = "delivered"
    return api.post(
        status_url(connection),
        data=urlencode(sent),
        content_type=FORM,
        headers={TWILIO_SIGNATURE_HEADER: signature},
    )


def status_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """Every `comms.*` line written in this block, parsed back from JSON.

    The same helper `test_delivery_status.py` uses and for the same reason: what
    a dashboard groups by is the rendering, not the event dict on its way there.
    """
    lines: list[dict[str, Any]] = []
    for record in caplog.records:
        try:
            parsed = json.loads(record.getMessage())
        except ValueError:
            continue
        if isinstance(parsed, dict) and str(parsed.get("event", "")).startswith("comms."):
            lines.append(parsed)
    return lines


# --- fixtures -------------------------------------------------------------------


@pytest.fixture
def token() -> str:
    return auth_token()


@pytest.fixture
def sms(tenant: Tenant, owner_actor: Actor, token: str) -> Connection:
    """The tenant's Twilio connection, holding the account's own credentials."""
    return create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider=SMS_STATUS_PROVIDER,
        name="Twilio",
        credentials={
            "account_sid": ACCOUNT_SID,
            "auth_token": token,
            "from_number": "+15550000000",
        },
    )


@pytest.fixture
def twilio_slot() -> Any:
    """Twilio in the `sms` slot, exactly as a product's `ready()` would put it.

    And the teardown **restores the previous occupant** rather than emptying the
    slot: the registry is process-global, and T1's own module records what an
    unregister-on-teardown did to the tests that were relying on the shipped
    fake. What ships is `FakeSmsChannel`; what a deployment with an account
    registers is this.
    """
    previous = registered_channels().get(Channel.SMS.value)
    channel = TwilioSmsChannel()
    register_channel(channel)
    yield channel
    if previous is not None:
        register_channel(previous)


@pytest.fixture
def texted(tenant: Tenant, owner_actor: Actor) -> Recipient:
    return services.create_recipient(
        tenant=tenant,
        actor=owner_actor,
        email="texted@example.com",
        display_name="A Reader",
        phone="+15550001111",
    )


@pytest.fixture
def sms_template(tenant: Tenant, owner_actor: Actor) -> None:
    services.create_template(
        tenant=tenant,
        actor=owner_actor,
        name="sms-receipt",
        subject="",
        body="Your receipt, {{ name }}.",
        channel=Channel.SMS,
        category="transactional",
        context_schema={"required": ["name"], "properties": {"name": {"type": "string"}}},
    )


def a_sent_text(*, tenant: Tenant, actor: Actor, recipient: Recipient, sid: str) -> Message:
    """One text Twilio accepted, recorded under **Twilio's** sid.

    Through the services, never the manager: a row written by hand can be a row
    the product could not have produced.
    """
    queued = services.send(
        recipient=recipient,
        template="sms-receipt",
        context={"name": "Ada"},
        channel=Channel.SMS,
        tenant=tenant,
        actor=actor,
    )
    return services.record_message_sent(
        tenant=tenant,
        actor=actor,
        message=queued,
        provider=providers.TWILIO_PROVIDER,
        provider_message_id=sid,
    )


def callback(sid: str, status: str, *, code: str = "", **extra: str) -> dict[str, str]:
    """One status callback in **Twilio's** shape. No house vocabulary in it."""
    fields = {
        "MessageSid": sid,
        "SmsSid": sid,
        "MessageStatus": status,
        "SmsStatus": status,
        "AccountSid": ACCOUNT_SID,
        "To": "+15550001111",
        "From": "+15550000000",
        **extra,
    }
    if code:
        fields["ErrorCode"] = code
    return fields


def reread(tenant: Tenant, message: Message) -> Message:
    return Message.objects.for_tenant(tenant).get(pk=message.pk)


def preference_for(tenant: Tenant, recipient: Recipient) -> ChannelPreference | None:
    return (
        ChannelPreference.objects.for_tenant(tenant)
        .filter(recipient=recipient, channel=Channel.SMS)
        .first()
    )


# --- the STOP, over the wire ------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_signed_twilio_stop_suppresses_the_recipient_over_the_wire(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    token: str,
    twilio_slot: Any,
    sms_template: None,
    texted: Recipient,
) -> None:
    """**The wire half T1 left owed.** Twilio's opt-out, end to end.

    A person texts STOP. Twilio records the opt-out against their number and
    refuses the next message we hand it — `undelivered`, error `21610`,
    "attempt to send to unsubscribed recipient", against the sid of OUR message.
    That is a real provider STOP arriving over the wire, and what it does is what
    T1 pinned a complaint does: **suppress the person, leave the row alone.**

    *Absent:* the 401 this test opened its life as — a genuine, correctly signed
    Twilio delivery refused at the door because no verifier claimed the scheme,
    and a person who asked us to stop still being texted.
    """
    sid = "SM" + "1" * 32
    message = a_sent_text(tenant=tenant, actor=owner_actor, recipient=texted, sid=sid)
    before = (message.status, message.bounced_at, message.bounce_kind, message.error)

    response = post_twilio(api, sms, callback(sid, "undelivered", code="21610"), token=token)
    assert response.status_code == 202, "a Twilio-signed delivery is accepted at the door"

    preference = preference_for(tenant, texted)
    assert preference is not None and preference.suppressed_at is not None, (
        "the person said STOP and is suppressed on the channel they said it on"
    )
    after = reread(tenant, message)
    assert (after.status, after.bounced_at, after.bounce_kind, after.error) == before, (
        "a STOP is consent news; the message row is delivery news and is untouched"
    )
    assert Event.objects.for_tenant(tenant).filter(name="comms.message.complained").count() == 1
    assert MessageEngagement.objects.for_tenant(tenant).count() == 0, (
        "a complaint is not an engagement, over SMS least of all"
    )


@pytest.mark.django_db(transaction=True)
def test_the_next_send_after_a_wire_stop_is_refused(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    token: str,
    twilio_slot: Any,
    sms_template: None,
    texted: Recipient,
) -> None:
    """The comms-8 chain, re-proven over the wire rather than at the service.

    *Absent:* a STOP that records a preference row nothing reads — the
    unread-preference finding, which is the whole reason the suppression is consulted inside
    `send()` rather than reported in a dashboard.
    """
    sid = "SM" + "2" * 32
    a_sent_text(tenant=tenant, actor=owner_actor, recipient=texted, sid=sid)
    assert (
        post_twilio(api, sms, callback(sid, "undelivered", code="21610"), token=token).status_code
        == 202
    )

    refused = services.send(
        recipient=texted,
        template="sms-receipt",
        context={"name": "Ada"},
        channel=Channel.SMS,
        tenant=tenant,
        actor=owner_actor,
    )
    assert refused.status == Message.Status.SUPPRESSED
    assert refused.suppressed_reason == Message.SuppressedReason.SUPPRESSED


# --- the signature: the vendor's, and only the vendor's ---------------------------


@pytest.mark.django_db(transaction=True)
def test_a_tampered_twilio_body_is_refused_at_the_door(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    token: str,
    twilio_slot: Any,
    sms_template: None,
    texted: Recipient,
) -> None:
    """A signature over one body and a request carrying another. 401, nothing stored.

    *Absent:* anyone who learned the URL can suppress anyone, which is what a
    door that reads a body it did not authenticate amounts to.
    """
    sid = "SM" + "3" * 32
    a_sent_text(tenant=tenant, actor=owner_actor, recipient=texted, sid=sid)
    response = post_twilio(
        api, sms, callback(sid, "undelivered", code="21610"), token=token, tamper=True
    )
    assert response.status_code == 401
    assert InboundWebhook.objects.for_tenant(tenant).count() == 0, "refused before the store"
    assert preference_for(tenant, texted) is None


@pytest.mark.django_db(transaction=True)
def test_a_signature_over_another_url_is_refused(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    token: str,
    twilio_slot: Any,
) -> None:
    """Twilio signs the URL it was given, so this door checks the URL it published.

    The failure this pins is a deployment one: `PUBLIC_BASE_URL` that no longer
    matches where Twilio actually posts. It fails CLOSED and says so in
    `comms.sms.signature_refused` — the alternative, verifying whatever host the
    request claimed, would let anyone who can set a `Host` header choose what we
    verify against.
    """
    response = post_twilio(
        api,
        sms,
        callback("SM" + "4" * 32, "delivered"),
        token=token,
        url="https://somewhere-else.example/api/v1/connections/x/webhook/",
    )
    assert response.status_code == 401


@pytest.mark.django_db(transaction=True)
def test_a_body_with_no_twilio_signature_falls_back_to_the_house_credential(
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    token: str,
) -> None:
    """`None` is the verifier's third answer, and it is what keeps the door open.

    A request with no `X-Twilio-Signature` is not Twilio's and this verifier has
    no opinion about it: the receiver's own HMAC stands, unchanged, which is what
    every house-signed post at a `comms-sms` connection has always relied on
    (`test_escalation.py` posts one).

    *Absent:* a verifier that answered `False` to anything it did not recognise,
    and one rung's new vendor closing a door another rung's tests came through.
    """
    verdict = providers.verify_sms_webhook(
        connection=sms, body=b"MessageStatus=delivered", headers={}
    )
    assert verdict is None
    signed = providers.verify_sms_webhook(
        connection=sms,
        body=b"MessageStatus=delivered",
        headers={TWILIO_SIGNATURE_HEADER: "not-a-signature"},
    )
    assert signed is False, "a signature that IS offered is checked, and this one is wrong"


@pytest.mark.django_db(transaction=True)
def test_a_connection_carrying_no_auth_token_has_no_opinion(
    tenant: Tenant,
    owner_actor: Actor,
) -> None:
    """No token, no check — and never a `True` from a branch that checked nothing.

    *Absent:* the failure mode `verify_status_webhook` reads its secret back off
    the constructed view to avoid — a verifier that says yes because it had
    nothing to compare with.
    """
    bare = create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider=SMS_STATUS_PROVIDER,
        name="Twilio, uncredentialed",
        credentials={"account_sid": ACCOUNT_SID},
    )
    assert (
        providers.verify_sms_webhook(
            connection=bare,
            body=b"MessageStatus=delivered",
            headers={TWILIO_SIGNATURE_HEADER: "anything"},
        )
        is None
    )


# --- `undelivered` is not one word ------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_dead_number_bounces_hard_and_suppresses(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    token: str,
    twilio_slot: Any,
    sms_template: None,
    texted: Recipient,
) -> None:
    """`30005`, unknown destination handset: address news, and the row moves.

    The contrast with the STOP above is the whole of ADR comms-9's split — same
    Twilio status word, two different facts, two different effects on the row.
    """
    sid = "SM" + "5" * 32
    message = a_sent_text(tenant=tenant, actor=owner_actor, recipient=texted, sid=sid)
    response = post_twilio(api, sms, callback(sid, "undelivered", code="30005"), token=token)
    assert response.status_code == 202

    after = reread(tenant, message)
    assert after.status == Message.Status.BOUNCED
    assert after.bounce_kind == BounceKind.HARD
    assert after.error, "the vendor's own account of it, on the column support reads"
    preference = preference_for(tenant, texted)
    assert preference is not None and preference.suppressed_at is not None


@pytest.mark.django_db(transaction=True)
def test_an_unreachable_handset_is_soft_and_suppresses_nobody(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    token: str,
    twilio_slot: Any,
    sms_template: None,
    texted: Recipient,
) -> None:
    """`30003`: the phone was off. Recorded, and nobody's address is written off.

    *Absent:* a person who spent a weekend out of signal suppressed for ever —
    the same suppression risk one channel over, and why `SUPPRESSING_KINDS` is a fork.
    """
    sid = "SM" + "6" * 32
    message = a_sent_text(tenant=tenant, actor=owner_actor, recipient=texted, sid=sid)
    assert (
        post_twilio(api, sms, callback(sid, "undelivered", code="30003"), token=token).status_code
        == 202
    )

    after = reread(tenant, message)
    assert (after.status, after.bounce_kind) == (Message.Status.BOUNCED, BounceKind.SOFT)
    assert preference_for(tenant, texted) is None, "a soft bounce records and does not act"


@pytest.mark.django_db(transaction=True)
def test_a_failed_send_is_our_fault_and_touches_nobodys_file(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    token: str,
    twilio_slot: Any,
    sms_template: None,
    texted: Recipient,
) -> None:
    """`failed` is Twilio saying it never sent — a suspended account, a bad config.

    *Absent:* the collapse this mapping refuses. `undelivered` and `failed` are
    two words because they are two facts, and folding them would suppress a
    person for our own billing problem.
    """
    sid = "SM" + "7" * 32
    message = a_sent_text(tenant=tenant, actor=owner_actor, recipient=texted, sid=sid)
    assert (
        post_twilio(api, sms, callback(sid, "failed", code="30002"), token=token).status_code == 202
    )

    assert reread(tenant, message).status == Message.Status.FAILED
    assert preference_for(tenant, texted) is None


@pytest.mark.django_db(transaction=True)
def test_a_queued_status_is_a_drop_that_names_the_word_it_read(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    token: str,
    twilio_slot: Any,
    sms_template: None,
    texted: Recipient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Twilio reports every hop. Only three of its words are answers.

    *Absent:* ADR comms-13's three-name drop vocabulary going dark on the second
    transport — a `queued` filed as untranslatable is a deployment fault claimed
    over a body that was read perfectly well.
    """
    sid = "SM" + "8" * 32
    message = a_sent_text(tenant=tenant, actor=owner_actor, recipient=texted, sid=sid)
    with caplog.at_level(logging.INFO):
        assert post_twilio(api, sms, callback(sid, "queued"), token=token).status_code == 202

    named = [line for line in status_lines(caplog) if line["event"].startswith("comms.status.")]
    assert [line["event"] for line in named] == ["comms.status.ignored"]
    assert named[0]["event_type"] == "queued"
    assert reread(tenant, message).status == Message.Status.SENT


# --- the inbound STOP: read, terminal, and joined to nothing ----------------------


@pytest.mark.django_db(transaction=True)
def test_an_inbound_stop_text_names_no_message_and_says_exactly_that(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    token: str,
    twilio_slot: Any,
    sms_template: None,
    texted: Recipient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """**The declared limit, pinned as a test rather than left as a hope.**

    A person texting STOP produces an INBOUND message webhook: their number, the
    word, and the sid of *their* message — nothing about anything we sent. The
    join this door has is the provider's handle for OUR message, so the event is
    read, it is terminal, and it names no row: `comms.status.no_message_id`, with
    the remedy, which is exactly what that drop reason means.

    Nobody is suppressed on this body and that is the honest answer today. The
    opt-out is not lost: Twilio refuses the next message to that number with
    `21610`, and the test at the head of this module is what happens then.

    *Absent:* a door that resolved a person from a phone number and picked a
    message to file a complaint against — an invented join, written into the
    audit trail as though the provider had said it.
    """
    fields = {
        "MessageSid": "SM" + "9" * 32,
        "From": "+15550001111",
        "To": "+15550000000",
        "Body": "STOP",
        "OptOutType": "STOP",
        "AccountSid": ACCOUNT_SID,
    }
    with caplog.at_level(logging.INFO):
        assert post_twilio(api, sms, fields, token=token).status_code == 202

    named = [line for line in status_lines(caplog) if line["event"].startswith("comms.status.")]
    assert [line["event"] for line in named] == ["comms.status.no_message_id"]
    assert named[0]["event_type"] == providers.TWILIO_OPT_OUT_EVENT
    assert named[0]["remedy"] == providers.NO_MESSAGE_ID_REMEDY
    assert preference_for(tenant, texted) is None


# --- the way out: the vendor SDK, driven with no account -------------------------


class RecordedTwilio:
    """The SDK's own `http_client` seam, answering with a recorded response.

    Not a mock of the adapter: everything the vendor library does — building the
    form, the basic auth, parsing the JSON back into a `MessageInstance` — still
    runs, and what this stands in for is the socket. The response body is the
    shape `POST /2010-04-01/Accounts/{sid}/Messages.json` actually returns.
    """

    def __init__(self, sid: str) -> None:
        self.sid = sid
        self.requests: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        uri: str,
        params: Any = None,
        data: Any = None,
        headers: Any = None,
        auth: Any = None,
        timeout: Any = None,
        allow_redirects: bool = False,
    ) -> TwilioResponse:
        self.requests.append({"method": method, "uri": uri, "data": dict(data or {}), "auth": auth})
        return TwilioResponse(
            201,
            json.dumps(
                {
                    "sid": self.sid,
                    "status": "queued",
                    "to": (data or {}).get("To", ""),
                    "from": (data or {}).get("From", ""),
                    "body": (data or {}).get("Body", ""),
                    "account_sid": ACCOUNT_SID,
                }
            ),
        )


@pytest.mark.django_db(transaction=True)
def test_a_text_goes_out_through_the_vendor_sdk_carrying_the_way_back(
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    sms_template: None,
    texted: Recipient,
) -> None:
    """The send half: the vendor's own client, and the callback URL wired at send.

    `status_callback` is what makes the other half reachable without a
    console step — the URL the delivery receipt and the `21610` opt-out come back
    to is handed over on every message.

    *Absent:* an adapter that sends and is never told about, which is an SMS
    channel whose messages are all `sent` for ever.
    """
    recorded = RecordedTwilio("SM" + "a" * 32)
    channel = TwilioSmsChannel(http_client=recorded)
    queued = services.send(
        recipient=texted,
        template="sms-receipt",
        context={"name": "Ada"},
        channel=Channel.SMS,
        tenant=tenant,
        actor=owner_actor,
    )
    sent = channel.send(message=queued, subject="", body="Your receipt, Ada.")

    assert sent.provider == providers.TWILIO_PROVIDER
    assert sent.provider_message_id == recorded.sid
    assert len(recorded.requests) == 1
    outbound = recorded.requests[0]
    assert outbound["method"] == "POST"
    assert outbound["uri"].endswith(f"/Accounts/{ACCOUNT_SID}/Messages.json")
    assert outbound["data"]["To"] == "+15550001111"
    assert outbound["data"]["From"] == "+15550000000"
    assert outbound["data"]["Body"] == "Your receipt, Ada."
    assert outbound["data"]["StatusCallback"] == status_callback_url(sms)
    assert outbound["uri"].startswith("https://"), "the vendor's own base URL, over TLS"


@pytest.mark.django_db(transaction=True)
def test_a_connection_missing_a_credential_fails_closed_and_names_the_key(
    tenant: Tenant,
    owner_actor: Actor,
    sms_template: None,
    texted: Recipient,
) -> None:
    """A half-configured account refuses the send. It never names the values.

    *Absent:* a text that silently goes nowhere, or a refusal a support agent
    cannot act on.
    """
    create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider=SMS_STATUS_PROVIDER,
        name="Twilio, half configured",
        credentials={"account_sid": ACCOUNT_SID},
    )
    queued = services.send(
        recipient=texted,
        template="sms-receipt",
        context={"name": "Ada"},
        channel=Channel.SMS,
        tenant=tenant,
        actor=owner_actor,
    )
    with pytest.raises(Invalid) as refusal:
        TwilioSmsChannel(http_client=RecordedTwilio("SM" + "b" * 32)).send(
            message=queued, subject="", body="Your receipt, Ada."
        )
    said = str(refusal.value)
    assert "auth_token" in said and "from_number" in said, "it names the keys that are empty"
    assert "account_sid" not in said, "and not the one that is set"


# --- SMS has no opens -------------------------------------------------------------


def test_the_sms_transports_report_no_engagement_and_that_is_deliberate() -> None:
    """**The engagement path is email-only, and this is where it says so.**

    ADR comms-9 made `ReportsEngagement` an OPTIONAL protocol for exactly this:
    an SMS gateway cannot observe an open. Twilio reports delivery and it reports
    opt-out; there is no vendor event that means "read", and inventing one would
    put a provider's inference into a table whose whole value is that it is
    witnessed. `FakeSmsChannel` has always lacked the method and T1 recorded that
    absence as deliberate; the real transport lands beside it with the same
    absence, asserted here so a later rung cannot add one by accident.

    *Absent:* the day somebody gives `TwilioSmsChannel` a `normalize_engagement`,
    nothing says the population it feeds was designed around one channel's facts.
    """
    assert not isinstance(TwilioSmsChannel(), ReportsEngagement)
    assert not isinstance(providers.FakeSmsChannel(), ReportsEngagement)
    assert isinstance(providers.EmailChannel(), ReportsEngagement), (
        "and the channel that CAN see an open still does"
    )


@pytest.mark.django_db(transaction=True)
def test_an_open_shaped_body_on_the_sms_slot_records_nothing(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    token: str,
    twilio_slot: Any,
    sms_template: None,
    texted: Recipient,
) -> None:
    """The claim above, driven through the door rather than asserted at the class.

    A body naming an open at the SMS connection reaches an adapter that cannot
    read one: no engagement row, no status change, and the drop vocabulary says
    what it saw.

    *Absent:* an engagement fork that answers for every channel because the map
    it consults is the email one.
    """
    sid = "SM" + "c" * 32
    message = a_sent_text(tenant=tenant, actor=owner_actor, recipient=texted, sid=sid)
    fields = {"MessageSid": sid, "MessageStatus": "read", "EventType": "opened"}
    assert post_twilio(api, sms, fields, token=token).status_code == 202

    assert MessageEngagement.objects.for_tenant(tenant).count() == 0
    assert reread(tenant, message).status == Message.Status.SENT


# --- the form language ------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_stored_delivery_is_the_form_twilio_posted(
    api: Client,
    tenant: Tenant,
    owner_actor: Actor,
    sms: Connection,
    token: str,
    twilio_slot: Any,
    sms_template: None,
    texted: Recipient,
) -> None:
    """The receiver stores bytes, and a form body replays as the pairs it was.

    The reading is keyed on the sender's own `Content-Type`, which is why a JSON
    ESP body and a Twilio form arrive at the same door and neither is guessed at.

    *Absent:* a stored delivery a human cannot replay, which is what the store is
    for when a handler drops something.
    """
    sid = "SM" + "d" * 32
    a_sent_text(tenant=tenant, actor=owner_actor, recipient=texted, sid=sid)
    assert post_twilio(api, sms, callback(sid, "delivered"), token=token).status_code == 202
    stored = InboundWebhook.objects.for_tenant(tenant).get()
    replayed = dict(parse_qsl(stored.body))
    assert replayed["MessageSid"] == sid
    assert replayed["MessageStatus"] == "delivered"
    assert settings.PUBLIC_BASE_URL in status_callback_url(sms)


def test_the_callback_lands_on_a_staff_host_named_by_its_tenant(
    tenant: Tenant, sms: Connection
) -> None:
    """A `{tenant}`-slot staff host gets the connection's tenant, never a `ValueError`."""
    with override_settings(SURFACE_HOSTS={"staff": "{tenant}.staff.example.test"}):
        url = status_callback_url(sms)

    assert url.split("/")[2].split(":")[0] == f"{tenant.slug}.staff.example.test"
