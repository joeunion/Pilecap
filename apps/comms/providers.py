"""The channel registry: one transport per `Channel`, and how one is added.

A channel provider is the thing that actually carries a message — the built-in
`EmailChannel` below, an SMS or Slack provider a product registers from its own
`AppConfig.ready()`. It mirrors `apps/connections/providers.py` down to
the file name: a `Protocol` rather than a base class, so a product's class
satisfies it by *shape* and never imports a version of this app back into its
own code.

**Why this is its own module rather than three declarations in `services.py`.**
It is not behaviour a caller invokes — it is a registry plus the one transport
this template ships, and `activities.py` (not a service) is what asks it for a
transport and calls it, out at the edge where I/O belongs. House rule 11 keeps
every app to the canonical file set, so an extra module has to be recorded in
`quality/rules.yaml` with its reason, which is exactly what
`extra_modules: {comms: [providers]}` is. That earlier docstring could not make that record — the
concurrency map gave `rules.yaml` to another lane — and said so in its own
module docstring; this module now owns both files and has done the cut and paste.

Keeping it here also keeps `services.py` honest under rule 16: `get_channel`
and `registered_channels` are lookups, not verbs, and a services module whose
public names are nouns is a services module doing something other than
services.

**The second half: a transport also answers backwards.** A channel
carries a message out; hours later the provider says whether it arrived. That
report is the same adapter's job — it is the provider's own vocabulary being
translated into this product's — so `normalize_status` sits on the same
protocol as `send`, and `handle_status_webhook` below is the door it feeds.
Since ADR comms-9 that door asks a second question of the same body: the
OPTIONAL `ReportsEngagement` protocol answers whether it was an open or a click,
which is the one thing this door records that is not a status and the one thing
it records that never moves the message row. That door
is *here* rather than in `api.py` because there is no route: the delivery rides
`apps/connections`' one signed receiver (ADR comms-3), which calls whatever
handler this app registered for its provider slug. `apps.py`'s `ready()` is the
registration, and this module is both the thing registered and the thing that
knows what an ESP event means.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from typing import Any, Protocol, runtime_checkable
from urllib.parse import parse_qsl

# `type: ignore[import-untyped]` — anymail ships no `py.typed` marker, and the
# override that would silence this properly lives in `pyproject.toml`, which no
# lane edits this cycle. The import earns the ignore: `EventType` is anymail's
# own normalised vocabulary, so `EMAIL_STATUS` breaks loudly at import if a
# future release renames one of these events, which a string literal would not.
import httpx
from anymail.signals import EventType, RejectReason  # type: ignore[import-untyped]
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.urls import reverse

# The SMS vendor, and **the two public seams this adapter holds and no more**
# (ADR comms-9's stack ruling; house rule 44's watch answered here rather than
# in a census, because neither of these is a private attribute rebound on
# somebody else's object). `Client` carries a text out; `RequestValidator` is
# the vendor's own compute-and-compare over the request it signed — house rule
# 43's disposition here: **the SDK validates, this repository never
# signs**, exactly as `verify_status_webhook` above delegates Resend's Svix
# scheme to anymail. A hand-rolled HMAC-SHA1 here would be a second
# implementation of somebody else's scheme, agreeing on the day it was written.
from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient

from apps.comms.models import BounceKind, Channel, Message, MessageEngagement
from apps.connections.client import http_client, post_idempotent
from apps.connections.models import Connection, InboundWebhook
from apps.connections.selectors import list_connections
from apps.core.actor import Actor, system_actor
from apps.core.exceptions import Invalid, NotFound
from apps.core.log import get_logger
from apps.core.services import root_organization

log = get_logger("apps.comms.providers")


@dataclass(frozen=True)
class Sent:
    """What a transport reports back: who carried it, and what they called it."""

    provider: str
    provider_message_id: str


#: The three things a transport may tell us afterwards, and the whole set. It is
#: closed on purpose: `record_delivery_status` refuses anything outside it by
#: name, so a provider inventing a fourth word cannot quietly become a
#: `Message.status` nothing in the product knows how to read.
STATUS_VALUES: frozenset[str] = frozenset(
    {Message.Status.DELIVERED.value, Message.Status.BOUNCED.value, Message.Status.FAILED.value}
)


@dataclass(frozen=True)
class ProviderStatus:
    """What a transport says became of a message it took. **In our words.**

    `provider_message_id` is the handle the transport gave us when it accepted
    the message — the value `Message.provider_message_id` holds — because that
    is the only join a provider's webhook offers back to a row here.

    `status` is one of `STATUS_VALUES` and never the provider's own spelling:
    the translation happens in `normalize_status`, at the adapter, so the
    service behind it has one vocabulary to know rather than one per ESP.

    `detail` is what the provider said in prose — "550 mailbox unavailable" —
    and it lands on `Message.error`, which is the thing a support agent reads
    when a customer says they never got their receipt.

    `bounce_kind` is `hard` or `soft` when `status` is `bounced`, and empty
    otherwise (ADR comms-9). It is the adapter's judgement and not the service's,
    for the reason the whole protocol exists: what "soft" means is a fact about
    one ESP's vocabulary, and a service that guessed it would be guessing per
    provider from a column with one spelling. Empty on a bounce means *the
    provider did not say*, which `services` treats as hard — the conservative
    direction, stated once there rather than defaulted here.

    `is_complaint` says the report was somebody pressing "report spam" (ADR
    comms-9, amended). It is a **field and not a column**: the message row keeps
    no complaint of its own, because a complaint by definition follows a
    delivery and a row cannot say "delivered, and also the recipient reported
    it" without a second vocabulary. The fact is carried by the suppression, the
    audit row and `comms.message.complained`; this field is only how the adapter
    tells the service which kind of news it is holding.

    It rides beside `status` rather than replacing it because a complaint is
    still, at the adapter, one of the words that means *stop mailing this
    address* — `EMAIL_STATUS` maps it to `bounced` and this flag is what stops
    the service from writing that down.
    """

    provider_message_id: str
    status: str
    detail: str = ""
    bounce_kind: str = ""
    is_complaint: bool = False


@dataclass(frozen=True)
class ProviderEngagement:
    """What a transport says a person DID with a message. **In our words.**

    `normalize_status`' sibling and deliberately a separate shape rather than
    another field on `ProviderStatus` (ADR comms-9): a status is news about
    whether the message arrived and an engagement is news about a person, the
    two are written into two tables, and one dataclass carrying both would be
    the collapse this whole split exists to undo. An adapter that reads an
    `email.opened` returns one of these and no status at all.

    `provider_message_id` is the same join every status report uses — the handle
    the transport gave us when it accepted the message.

    `kind` is one of `MessageEngagement.Kind` and never the provider's own
    spelling: `email.opened`, `open`, `Open` and `MESSAGE_OPENED` are four
    vendors' words for one fact, and the translation happens at the adapter so
    the service behind it has one vocabulary to know.

    `url` is the destination of a click and is empty on an open. The service
    empties it on an open anyway and the database refuses one, which is three
    statements of one rule in the three places a reader looks.

    `occurred_at` is when the PROVIDER says it happened, `None` when it said
    nothing — the service defaults that to now rather than guessing here,
    because "we do not know" and "it happened when we heard" are different
    claims and only one of them is the row's.

    `provider_event_id` is the transport's handle for THE EVENT (not for the
    message), and it is what makes a redelivery idempotent. It is often empty
    from an adapter reading a body alone: several vendors put the event id in a
    HEADER, which the adapter never sees — `handle_status_webhook` fills that
    gap from the receiver's own stored `delivery_id`, which is the same string.
    """

    provider_message_id: str
    kind: str
    url: str = ""
    occurred_at: datetime | None = None
    provider_event_id: str = ""


#: Why a status body produced no status. A **closed set**, for the reason
#: `STATUS_VALUES` is one: each of these words picks a log name, and a log name
#: a dashboard groups by cannot be whatever an adapter felt like saying.
#:
#: The three are genuinely different findings and that is the whole of ADR
#: comms-13. `non_terminal` is the door working — an open, a click, a deferral,
#: and the run keeps waiting. `untranslatable` is a **deployment** fault: a body
#: arrived in a vocabulary this door cannot read, which is somebody posting raw
#: ESP JSON at a stack with no ESP configured to translate it. `no_message_id`
#: is a **provider** fault: the event was read and it was terminal, and it named
#: no handle to join it to a row with. Collapsing them into one `ignored`
#: would be a log name claiming a judgement that was never made.
DROP_NON_TERMINAL = "non_terminal"
DROP_UNTRANSLATABLE = "untranslatable"
DROP_NO_MESSAGE_ID = "no_message_id"


@dataclass(frozen=True)
class StatusDrop:
    """An adapter's own account of why it produced no status.

    `reason` is one of the three words above. `event_type` is the word the
    adapter actually **read** out of the body after whatever translation it can
    do — empty only when it read none, which is exactly the `untranslatable`
    case and is why `comms.status.ignored` can now promise never to print an
    empty one.

    It is a value and not an exception because a dropped webhook is not an
    error: the receiver already answered 202, the body is already stored, and
    the only thing left to decide is what the log line says.
    """

    reason: str
    event_type: str = ""


#: What to do about a body this door could not read. It travels as a log field
#: rather than being formatted into the message, because house rule 19's whole
#: point is that a line assembled into prose is a line nobody can query — and
#: because the remedy is the same sentence every time, so it is a constant.
UNTRANSLATABLE_REMEDY = (
    "This door's status vocabulary is anymail's normalised one (ADR comms-13): "
    "post an `event_type` from `anymail.signals.EventType` with a `message_id`, "
    "or set EMAIL_BACKEND to an Anymail ESP backend so this provider's own body "
    "can be translated on arrival."
)

#: And for the other provider-side fault. Separate constant, separate sentence:
#: a body that was read and understood needs different advice from one that
#: could not be read at all.
NO_MESSAGE_ID_REMEDY = (
    "The event was read and it is terminal, but it names no `message_id`, so "
    "there is no join back to a message row. Post the provider handle this "
    "deployment recorded at send time."
)


class ChannelProvider(Protocol):
    """One transport, as far as this app needs to know about it.

    Three members and no base class, deliberately: `Protocol` means a product's
    class satisfies this by having the right shape rather than by inheriting
    from this module — which matters because the alternative is an import from
    every provider back into this app, and a version of this app every provider
    is pinned to.

    A transport that has no status webhook still declares `normalize_status`
    and returns `None` from it, which is the honest answer — "this provider
    never tells us" — rather than an absent method the caller has to guess at.
    """

    #: **A read-only property rather than `slug: str`** (T3, and it is a fix
    #: rather than a style choice). A bare annotation on a Protocol declares a
    #: SETTABLE variable, and mypy then refuses any implementation whose `slug`
    #: cannot be assigned to — which is every frozen dataclass, including
    #: `ConnectionChannel` below, the reference adapter whose own docstring
    #: tells a product to write `register_channel(ConnectionChannel(...))`.
    #: That line did not type-check, and nothing noticed because no module
    #: under `apps/` or `config/` calls it: the registrations that ship are all
    #: plain classes. `DevicePushChannel` is the second frozen adapter and it
    #: met the same wall.
    #:
    #: Declaring it read-only is what the protocol always meant — the registry
    #: reads a transport's slug and never assigns one — and it accepts both
    #: shapes: a plain class attribute satisfies a read-only property, and so
    #: does a frozen field.
    @property
    def slug(self) -> str:
        """Which `Channel` this transport carries."""
        ...

    def send(self, *, message: Message, subject: str, body: str, nonce: str = "") -> Sent:
        """Hand the rendered message to the transport, or raise.

        Raising is how a provider says "not this time": the delivery workflow
        retries with backoff and only records `failed` once the attempts are
        spent. Returning a `Sent` means the provider accepted it — which is not
        the same as delivered, and the status column says `sent` rather than
        `delivered` for exactly that reason.

        **`nonce` is the delivery's own opaque id**, the same string
        on every attempt of one delivery and a different one for a second send.
        An adapter that can give its provider a message identifier should give
        it this — that is what lets a vendor collapse the two mails a crash
        between "handed over" and "recorded that we did" produces.

        It has a default, and the default is load-bearing: a product's adapter
        written before this parameter existed satisfies this protocol unchanged and simply never
        stamps anything, which is what it did anyway. **What it is not** is
        `provider_message_id`: that string is a suppression key
        (`record_delivery_status` joins on it) and printing it into a message
        handed the recipient a valid suppression key for themselves. This
        one is accepted by nothing. See `services.delivery_nonce`.
        """
        ...

    def normalize_status(self, *, payload: dict[str, Any]) -> ProviderStatus | None:
        """One inbound status report, in this product's vocabulary — or `None`.

        `None` is not an error and it is not a shrug: it means *this delivery
        says nothing about whether the message arrived*. An open, a click, a
        queue acknowledgement and a deferral are all real events and none of
        them is a terminal answer, so the handler drops them and the run keeps
        waiting. Tracking opens and clicks is a named deferral with its own
        rung, not a status this column can hold.

        It is on this protocol rather than in the handler because the
        translation is the *provider's*: an ESP's word for a hard bounce is the
        one thing that differs between two deployments of identical product
        code.
        """
        ...


@runtime_checkable
class ExplainsStatusDrops(Protocol):
    """The optional fourth member: an adapter that can account for its silence.

    Deliberately a **second** protocol rather than a third member on
    `ChannelProvider`, because the two answer to different needs. Every
    transport owes this app a `send` and a `normalize_status`; none of them owes
    it a diagnostic. A product's adapter that never grows this method keeps
    working and gets the reading `status_drop` below can do for itself — which
    is the same fallback shape `_esp_tracking_view` and `verify_status_webhook`
    already use in this file, and never a silent pass.

    `runtime_checkable` so the handler can ask by `isinstance` rather than by
    `getattr` and a `cast`: the question "does this transport explain itself" is
    a real one with a typed answer, and probing an attribute name in a string
    would be the version of it that a rename breaks silently.

    Returning `None` means *this body is not a drop at all* — the honest answer
    when somebody asks an adapter to explain a payload that does carry a status.
    It is not reachable through `handle_status_webhook`, which asks only after
    `normalize_status` has already answered `None`; it exists so that the method
    has an answer for every input rather than a contract nobody can check.
    """

    def explain_status_drop(self, *, payload: dict[str, Any]) -> StatusDrop | None:
        """Why this body said nothing terminal, in the closed vocabulary above."""
        ...


@dataclass(frozen=True)
class Fakeness:
    """What a stand-in says about itself, in the two sentences a census prints.

    `detail` is what is TRUE — "every text is appended to `fake_sms_outbox` and
    nothing leaves this process" — never the word "fake" repeated. `remedy` is
    what somebody types to make it real. The split is
    `core.integrations.Integration`'s, deliberately: this is the value that
    becomes those two fields, so a transport that declares itself is answering
    the census's question rather than a shape of its own.
    """

    detail: str
    remedy: str


@runtime_checkable
class DeclaresFakeness(Protocol):
    """The optional third protocol: a transport that says it is a stand-in.

    **This exists because of a specific, expensive silence.** A fresh clone
    keeps `FakeSmsChannel` on the `sms` slot by
    design. A real person really texts STOP; Twilio really signs the callback;
    `apps/connections`' receiver really verifies it, stores it and answers 202 —
    and then nothing happens, because the transport that would have understood
    it is not there. Every layer worked. The only thing in the tree that said
    the slot was held by a fake was a comment in this file, and a comment is not
    a surface.

    A filled slot is **more** dangerous than an empty one: the empty one refuses
    and the fake one succeeds. So the census wanted a status for it
    (`IntegrationStatus.FAKE`), and this is how a transport claims it.

    Deliberately a **third** protocol beside `ExplainsStatusDrops` rather than a
    member on `ChannelProvider`, for that protocol's own recorded reason: every
    transport owes this app a `send` and a `normalize_status`; none of them owes
    it a confession. A product's real adapter never implements this and is read
    as real, which is right — and is also this seam's declared blind spot, the
    same one `core.integrations`' docstring names: *nothing here audits the
    claim*. A fake that says it is real is invisible to the census, and the
    honest defence is that the template's own fakes are held to declaring by
    `tests/test_integrations.py`, not that the registry can tell.

    `runtime_checkable` so the census asks by `isinstance` rather than by
    `getattr` and a `cast` — `status_drop`'s argument, one protocol over.
    """

    def fakeness(self) -> Fakeness | None:
        """The confession, or `None` from a transport that really sends."""
        ...


#: What `fakeness()` returns to say "I really send". **A value, not `None`**,
#: and the difference is the whole point: `None` used to mean
#: both *I am real* and *nobody asked me*, so a transport that declared nothing
#: at all was read as real. An optimistic default on a question whose whole
#: purpose is to catch silent fakes is the one default it must not have.
REALLY_SENDS = Fakeness(detail="", remedy="")


def channel_fakeness(provider: ChannelProvider) -> Fakeness | None:
    """What this transport says about being a stand-in.

    Three answers now, where the earlier shape shipped two:

    * a `Fakeness` with content — **it is a stand-in**, and says what it does
      instead and what to type;
    * `REALLY_SENDS` — **it is real, and it said so.** A transport that
      implements `DeclaresFakeness` and returns `None` is claiming this;
    * `None` from here — **nobody asked it**, because it does not implement the
      protocol at all. The census reads that as UNKNOWN, never as configured.

    T-pr collapsed the last two and said so as a declared blind spot: *a
    transport that does not declare is taken at its word, and the word is "I am
    real"*. The comms lane then planted a bare channel and read `configured`
    back, which is that blind spot being the optimistic one — the template's own
    fakes are belt-held by a test, and a PRODUCT's are not. The guess is gone;
    nothing here infers from a class name, and silence is now silence.
    """
    if isinstance(provider, DeclaresFakeness):
        return provider.fakeness() or REALLY_SENDS
    return None


def status_drop(provider: ChannelProvider, *, payload: dict[str, Any]) -> StatusDrop:
    """Why a status body produced no status — the adapter's account, or the door's.

    An adapter that implements `ExplainsStatusDrops` knows, because it is the
    thing that did the reading; anything else gets what this door can see for
    itself, which is whether the body arrived carrying the vocabulary the door's
    contract asks for. That fallback is deliberately conservative and it is a
    declared blind spot of ADR comms-13: a transport that *can* translate a raw
    body but does not explain itself will have a translated non-terminal event
    reported as `untranslatable`. The remedy printed is still the right one for
    a product in that position — implement the method — and no drop is silent
    either way.
    """
    if isinstance(provider, ExplainsStatusDrops):
        explained = provider.explain_status_drop(payload=payload)
        if explained is not None:
            return explained
    event = str(payload.get("event_type", "")).strip().lower()
    return StatusDrop(reason=DROP_NON_TERMINAL if event else DROP_UNTRANSLATABLE, event_type=event)


@runtime_checkable
class ReportsEngagement(Protocol):
    """The optional fifth member: an adapter that can read an open or a click.

    A **second** protocol rather than another member on `ChannelProvider`, for
    exactly the reason `ExplainsStatusDrops` above is one, and the trade is worth
    restating because it is the one a reviewer will ask about. Every transport
    owes this app a `send` and a `normalize_status`; **not one of them owes it
    engagement**. An SMS gateway cannot observe an open, a chat tool's "read
    receipt" is a different fact with a different consent story, and a fourth
    REQUIRED member would break every adapter a product has already written
    against the three — silently, at the type checker, in a file this app cannot
    see. ADR comms-9 says "normalize_status's sibling on the provider protocol";
    a sibling protocol in this module is that sentence built the way this module
    already builds optional members.

    `runtime_checkable` so the caller asks by `isinstance` rather than by
    `getattr` and a `cast`: "does this transport report engagement" is a real
    question with a typed answer, and probing an attribute name in a string is
    the version of it a rename breaks silently.

    `None` means *this body is not an engagement* — a bounce, a deferral, a
    queue acknowledgement, anything at all. It is not an error and there is no
    fallback for it: unlike a status drop, this door cannot read an engagement
    out of a body for itself, because what an ESP calls an open is precisely the
    knowledge that lives in the adapter.
    """

    def normalize_engagement(self, *, payload: dict[str, Any]) -> ProviderEngagement | None:
        """One inbound engagement report, in this product's vocabulary — or `None`."""
        ...


#: Keys a sender plausibly reaches for that this product does not read, mapped
#: to the one it does. **Documented as a
#: near miss, never as a synonym**: nothing below reads the wrong key as if it
#: were the right one.
#:
#: The ruling is the narrow one, and both halves matter. **Refusing an unknown
#: key is wrong** — a provider webhook is somebody else's payload and adding a
#: field to it is a thing providers do; a door that refused unrecognised keys
#: would break on the vendor's next release and would be the template deciding
#: what other people's schemas may contain. **Silence was also wrong**: a click
#: posted with `url` recorded a legal `clicked` row with an empty link, no
#: refusal and NO LOG LINE AT ALL — strictly worse than the `message_id`
#: confusion beside it, which at least logs `unknown_message`. So the permissive
#: read survives and the zero-diagnostic path dies.
#:
#: One entry today. It grows when a real sender reaches for a real wrong key,
#: not when somebody imagines one.
NEAR_MISS_KEYS: dict[str, str] = {"url": "click_url"}


def _warn_near_miss_keys(*, payload: Mapping[str, Any], read: str, kind: str) -> None:
    """Say so when a body carries an adjacent key instead of the one we read.

    Structured, through `core.log` (rule 19), naming **both** keys — the one
    that was sent and the one this product reads — because a diagnostic that
    named only the mistake would still leave the reader guessing at the fix.

    Only fires when the key we DO read is absent: a body carrying both is a
    sender who found the right one and kept the old one, which is not a mistake
    and does not need telling. And only for a body that already produced
    something — the caller below has a `kind` in hand — so a payload this
    deployment cannot read at all is `untranslatable_body`'s finding and not
    this one's.
    """
    for sent, reads in NEAR_MISS_KEYS.items():
        if sent in payload and not str(payload.get(reads, "") or "").strip():
            log.warning(
                "comms.engagement.near_miss_key",
                sent_key=sent,
                expected_key=reads,
                kind=kind,
                read=read,
            )


def engagement_of(
    provider: ChannelProvider, *, payload: dict[str, Any]
) -> ProviderEngagement | None:
    """What this adapter makes of the body as an engagement. `None` if it cannot.

    Two ways to answer `None` and they are deliberately one answer here: the
    transport does not implement `ReportsEngagement` at all, or it does and this
    body is not an engagement. Neither is a finding — the caller's next move is
    the same in both cases, which is to fall through to the drop vocabulary that
    already exists — and telling them apart would be a fourth drop reason for a
    distinction nobody acts on.
    """
    if not isinstance(provider, ReportsEngagement):
        return None
    read = provider.normalize_engagement(payload=payload)
    if read is not None:
        # Here rather than inside an adapter's `normalize_engagement`,
        # because the near miss is a fact about the BODY and not about any one
        # vendor's reading of it — a product's own adapter gets the tell for
        # free, which is the half that makes this a seam rather than one class's
        # good manners.
        _warn_near_miss_keys(payload=payload, read=read.url, kind=read.kind)
    return read


_channels: dict[str, ChannelProvider] = {}


def register_channel(provider: ChannelProvider) -> None:
    """Add a transport.

    A product's own channels register from its `AppConfig.ready()`, which is the
    one place Django guarantees the app registry is complete. The bundled
    `EmailChannel` at the foot of this module is the exception and can afford to
    be: it lives in the same module as the registry, so there is no import to
    order and nothing to be half-loaded.
    """
    _channels[str(provider.slug).strip().lower()] = provider


def unregister_channel(slug: str) -> None:
    """Take one out again. For a test that planted one."""
    _channels.pop(str(slug).strip().lower(), None)


def registered_channels() -> dict[str, ChannelProvider]:
    """Every transport this deployment can actually send on."""
    return dict(_channels)


def get_channel(slug: str) -> ChannelProvider:
    """The transport for a channel, or the domain's not-found.

    `NotFound` rather than `KeyError`, because the caller is one step from a
    door: a deployment with no SMS provider and a template asking for SMS is
    indistinguishable, to a client, from asking for a channel that does not
    exist.
    """
    provider = _channels.get(str(slug).strip().lower())
    if provider is None:
        raise NotFound(f"No transport is registered for the {slug!r} channel.")
    return provider


def _email_provider_name() -> str:
    """What to record in `Message.provider` for an email send.

    Read off `EMAIL_BACKEND`, because that *is* the answer: `smtp` on a laptop
    pointing at Mailpit, `locmem` under pytest, and the ESP's own name once a
    deployment points the setting at an Anymail backend. Swapping provider is
    therefore a setting and a credential, never a code path here — which is the
    property `architecture.md` asked for.
    """
    backend = str(getattr(settings, "EMAIL_BACKEND", "") or "")
    parts = [part for part in backend.split(".") if part and part != "EmailBackend"]
    if not parts:
        return "email"
    if parts[0] == "anymail":
        return f"anymail:{parts[-1]}"
    return parts[-1]


def _anymail_esp() -> str:
    """Which Anymail ESP this deployment sends through, in Anymail's own spelling.

    `anymail.backends.resend.EmailBackend` → `"resend"`, and an empty string for
    every backend that is not Anymail's — console, locmem, smtp, a product's own.
    Read off `EMAIL_BACKEND` for the same reason `_email_provider_name` is: that
    setting *is* the answer to "who carries our mail", and a second setting
    naming the ESP would be a second thing to get out of step with the first.

    The name matters beyond a log line because Anymail ships one webhook view
    per ESP — the vendor's signature scheme and the vendor's event vocabulary,
    both already written — and this string is how `_esp_tracking_view` finds the
    right one. Which is the whole shape of ADR comms-12: **the seam is Anymail,
    the provider is the product's setting.**
    """
    parts = str(getattr(settings, "EMAIL_BACKEND", "") or "").split(".")
    if len(parts) >= 3 and parts[0] == "anymail" and parts[1] == "backends":
        return parts[2]
    return ""


#: The attribute Anymail's Svix-signing webhook views name their signature
#: secret with. Reading it off the class rather than knowing it is what makes
#: this adapter a statement about *Anymail* rather than a statement about
#: Resend: any ESP whose view declares one is driven by exactly this code.
SECRET_ATTR = "_secret_setting_name"  # pragma: allowlist secret — an attribute NAME


def _esp_tracking_view_class(esp: str) -> type | None:
    """Anymail's tracking webhook view for one ESP, or `None`.

    Found by import and by shape — `anymail.webhooks.<esp>`, the class in *that*
    module whose name ends `TrackingWebhookView` — rather than by a table of
    fifteen ESPs this file would have to keep in step with Anymail's releases. A
    product on an ESP Anymail supports gets this for free; a product on one it
    does not gets `None`, and `None` is a fallback and never a silent pass.
    """
    try:
        module = import_module(f"anymail.webhooks.{esp}")
    except ImportError:
        return None
    for name in dir(module):
        candidate = getattr(module, name)
        if (
            isinstance(candidate, type)
            and name.endswith("TrackingWebhookView")
            and candidate.__module__ == module.__name__
        ):
            return candidate
    return None


class _EspRequest:
    """The two attributes Anymail's webhook views read off an `HttpRequest`.

    A stand-in rather than the real request, because this adapter is called from
    two places that do not both have one: the door has a request, and
    `normalize_status` has a stored `InboundWebhook` row that was received
    minutes or hours ago. Handing both the same two-attribute object is what
    lets one adapter serve both without the row's replay pretending to be a
    live request.
    """

    def __init__(self, *, body: bytes, headers: Mapping[str, str]) -> None:
        self.body = body
        self.headers = dict(headers)


def _esp_tracking_view(esp: str, *, secret: str = "") -> Any | None:
    """One constructed Anymail tracking view, or `None` if it cannot be built.

    `secret`, when given, is handed to whatever setting the view names as its
    signature secret — so **the credential stays on the tenant's `Connection`
    row**, encrypted, where every other webhook secret in this product already
    lives, rather than becoming one deployment-wide value in settings that every
    tenant's provider would have to share.

    The warning filter is narrow and earned: Anymail warns when its own
    `WEBHOOK_SECRET` basic auth is unset, which is advice for a deployment that
    mounted Anymail's view at a URL of its own. This product did not — ADR
    comms-3's one receiver is the door, and that door's credential is checked
    before this object is ever built.
    """
    view_class = _esp_tracking_view_class(esp)
    if view_class is None:
        return None
    kwargs: dict[str, Any] = {}
    secret_kwarg = getattr(view_class, SECRET_ATTR, "")
    if secret and secret_kwarg:
        kwargs[secret_kwarg] = secret
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return view_class(**kwargs)
    except Exception:
        # A view this deployment has not configured enough to build. Anymail
        # raises its own configuration error, the vendor library may raise
        # anything at all, and either way the honest answer upwards is "no
        # adapter" — which every caller reads as a fallback and none as a pass.
        log.info("comms.esp.view_unavailable", esp=esp)
        return None


def verify_status_webhook(
    *, connection: Connection, body: bytes, headers: Mapping[str, str]
) -> bool | None:
    """The ESP's own signature check, driven by Anymail. Or no opinion.

    Registered on `apps/connections`' verifier registry from this app's
    `ready()`, and answering that registry's three values (see
    `connections.providers.WebhookVerifier`):

    * `True` / `False` — this deployment sends through an Anymail ESP whose
      webhook view declares a signature secret, the connection is carrying one,
      and Anymail checked the request with the vendor's own scheme. For Resend
      that is Svix over `svix-id`, `svix-timestamp` and `svix-signature`, with a
      five-minute window the vendor library enforces and this product does not
      re-implement;
    * `None` — anything else: a laptop on Mailpit, pytest on locmem, an ESP
      whose Anymail view verifies by basic auth alone, a connection whose
      credentials were revoked. The receiver falls back to its own HMAC, which
      is always present and always checked.

    **No branch returns `True` without a signature having been verified**, which
    is the property to keep if this function is ever edited: an ESP that cannot
    be checked must reach `None` (fall back to the door's own credential) and
    never `True`.

    The broad `except` is deliberate and is a *refusal*, not a shrug. A
    signature header that is not base64, is missing its version prefix, or
    carries a timestamp that will not parse comes out of a vendor library as
    whatever that library felt like raising, and every one of those is somebody
    posting a malformed credential at a public door. The answer to that is 401,
    never a 500 that tells them their payload reached our stack trace.
    """
    esp = _anymail_esp()
    if not esp:
        return None
    view = _esp_tracking_view(esp, secret=connection.webhook_secret)
    if view is None:
        return None
    # **The check that the check exists.** Anymail's webhook views are built to
    # be mounted at a URL and to run whatever validation they were configured
    # for — which, given no secret, is *none at all*, silently, returning
    # cleanly from `run_validators`. A view whose signature secret did not
    # actually arrive would therefore say `True` to a forged body, which is the
    # precise shape of "the receiver ends up open" that `signature_matches`
    # refuses an empty secret for. So this reads the secret back **off the
    # constructed instance**, under the name the class itself declares: proof
    # that a secret got in, not a hope that one did.
    secret_attr = getattr(type(view), SECRET_ATTR, "")
    if not secret_attr or not getattr(view, secret_attr, None):
        return None
    try:
        view.run_validators(_EspRequest(body=body, headers=headers))
    except Exception:
        log.info("comms.esp.signature_refused", esp=esp, connection_id=str(connection.pk))
        return False
    return True


def esp_normalized(payload: dict[str, Any]) -> dict[str, Any] | None:
    """One raw ESP webhook body, translated into Anymail's normalised vocabulary.

    This is the other half of what `django-anymail` is for and the half a
    deployment usually gets by mounting Anymail's view at a URL. This product
    does not mount it (ADR comms-3: one inbound route), so it calls the
    translation directly — `esp_to_anymail_event`, the same method the view
    would have called — and gets Anymail's fourteen-ESP normalisation without a
    second door.

    Returns the five keys `EmailChannel.normalize_status` already reads, so a
    raw Resend body and a pre-normalised one converge one line later and the
    fork, the suppression and the tests below them never learn which arrived.

    `None` means *this is not an ESP body this deployment can read*: no Anymail
    backend configured, no view for that ESP, or a payload the translation
    could not make sense of. The caller treats the body as already-normalised,
    which is what every fixture and every product-supplied adapter sends.
    """
    esp = _anymail_esp()
    if not esp:
        return None
    view = _esp_tracking_view(esp)
    if view is None:
        return None
    try:
        event = view.esp_to_anymail_event(payload, _EspRequest(body=b"", headers={}))
    except Exception:
        log.info("comms.esp.unreadable_event", esp=esp)
        return None
    moment = getattr(event, "timestamp", None)
    return {
        "event_type": str(getattr(event, "event_type", "") or ""),
        "message_id": str(getattr(event, "message_id", "") or ""),
        "description": str(getattr(event, "description", "") or ""),
        "reject_reason": str(getattr(event, "reject_reason", "") or ""),
        "mta_response": str(getattr(event, "mta_response", "") or ""),
        # The three ADR comms-9's engagement half reads. Additive on purpose:
        # `normalize_status` reads the five above and never learns these exist,
        # so the bounce path is byte-identical to what it was.
        #
        # `event_id` is Anymail's, and on several ESPs — Resend among them — it
        # comes off a REQUEST HEADER rather than out of the body. This function
        # replays a stored delivery and hands the view no headers, so the value
        # is usually empty here and the door fills it from the receiver's own
        # `delivery_id`, which is the same string read at the same door.
        "event_id": str(getattr(event, "event_id", "") or ""),
        # ISO-8601, so one vocabulary crosses this seam: everything else in this
        # dict is a string, and a payload a product's own adapter posts
        # pre-normalised writes a string too.
        "timestamp": moment.isoformat() if moment is not None else "",
        "click_url": str(getattr(event, "click_url", "") or ""),
    }


def _message_id_domain() -> str:
    """The right-hand side of the `Message-ID` this app mints.

    From `DEFAULT_FROM_EMAIL`, so the id a provider and a recipient's mail
    client both see names the sender rather than whichever host happened to run
    the worker.
    """
    sender = str(getattr(settings, "DEFAULT_FROM_EMAIL", "") or "")
    _, _, domain = sender.rpartition("@")
    return domain.strip("> ") or "localhost"


#: Anymail's normalised event types, mapped to the three words this product
#: keeps. Absent from this dict means "says nothing terminal" — see
#: `EmailChannel.normalize_status`.
EMAIL_STATUS: dict[str, str] = {
    EventType.DELIVERED: Message.Status.DELIVERED.value,
    EventType.BOUNCED: Message.Status.BOUNCED.value,
    EventType.COMPLAINED: Message.Status.BOUNCED.value,
    EventType.REJECTED: Message.Status.BOUNCED.value,
    EventType.FAILED: Message.Status.FAILED.value,
}

#: Anymail's normalised **engagement** events, mapped to the two kinds this
#: product records (ADR comms-9). Absent from this dict means "not an
#: engagement" — which is every other event Anymail can name, terminal or not.
#:
#: Two entries and there is no third, because there is no third *fact*: an
#: `unsubscribed` is consent news and goes through the suppression wall, a
#: `complained` is consent news and has its own name, and both would be the
#: collapse ADR comms-9 spent a rung undoing if they landed here.
EMAIL_ENGAGEMENT: dict[str, str] = {
    EventType.OPENED: MessageEngagement.Kind.OPENED.value,
    EventType.CLICKED: MessageEngagement.Kind.CLICKED.value,
}

#: Anymail's normalised **reject reasons**, split into the two kinds of bounce
#: (ADR comms-9). This is the reference provider's mapping and a product with a
#: different ESP re-judges it in its own adapter — which is exactly what
#: `normalize_status` sits on the protocol for.
#:
#: **On Resend the soft branch is unreachable, and that is a finding rather than
#: a gap** (E1′, F1m-5): anymail's Resend adapter reads the kind out of one
#: human-readable sentence and can produce only `blocked`, `bounced` or `other`
#: (`anymail/webhooks/resend.py`) — the first two hard here, the third empty and
#: resolved to hard by `services`. `timed_out` is a word that adapter never
#: says, so **anymail maps every Resend bounce hard — the soft branch is
#: unreachable on this provider**, pinned by
#: `test_esp_webhook.test_every_resend_bounce_shape_is_hard_so_the_soft_branch_is_unreachable`
#: and proven for other ESPs by `test_suppression_wall.py`'s fixtures. Resend's
#: own non-terminal delivery problem, `email.delivery_delayed`, normalises to
#: `DEFERRED` and is dropped before this dict is consulted.
#:
#: Only `timed_out` is soft, and the reason is anymail's own gloss on it:
#: "(previous) repeated failed delivery attempts" — the receiving server was
#: there and would not take it yet. Everything else in the enum is a statement
#: about the address itself (`invalid`, `bounced`, `spam`, `unsubscribed`) or
#: about the ESP refusing to carry mail to it again (`blocked`), and continuing
#: to mail those is the reputational harm suppression exists to prevent.
#: `other` is the ESP's catch-all and is absent on purpose: it means the
#: provider did not classify, which `_bounce_kind` reports as empty and
#: `services` resolves — one default, in one place.
BOUNCE_KIND: dict[str, str] = {
    RejectReason.INVALID: BounceKind.HARD.value,
    RejectReason.BOUNCED: BounceKind.HARD.value,
    RejectReason.SPAM: BounceKind.HARD.value,
    RejectReason.UNSUBSCRIBED: BounceKind.HARD.value,
    RejectReason.BLOCKED: BounceKind.HARD.value,
    RejectReason.TIMED_OUT: BounceKind.SOFT.value,
}

#: The two event types that are a bounce **by their own name**, whatever the
#: reject reason says. A spam complaint and an ESP rejection are facts about the
#: address and the relationship, not about a mail server having a bad hour, so
#: they take the hard branch without consulting `BOUNCE_KIND` at all — which is
#: what keeps ADR comms-9's "`complained` and `rejected` unchanged" true by
#: construction rather than by a mapping somebody could edit.
ALWAYS_HARD: frozenset[str] = frozenset({EventType.COMPLAINED, EventType.REJECTED})

#: The event types that are **consent news** rather than address news (ADR
#: comms-9, amended). A sibling of `ALWAYS_HARD` and deliberately its own set:
#: `rejected` is in that one and not this one, because an ESP refusing to carry
#: the message is a fact about the address and keeps the bounce path, while a
#: person pressing "report spam" is a fact about consent and leaves it.
COMPLAINT_EVENTS: frozenset[str] = frozenset({EventType.COMPLAINED})

#: Where a provider puts its own prose about a status, best first. Anymail fills
#: `description` with the ESP's human text, `reject_reason` with its normalised
#: reason and `mta_response` with the receiving server's raw line.
DETAIL_KEYS: tuple[str, ...] = ("description", "reject_reason", "mta_response")


def _is_complaint(event: str) -> bool:
    """Whether this report is somebody pressing "report spam" (ADR comms-9, amended).

    Read off the **event type** and nothing else, exactly as `ALWAYS_HARD` is:
    a complaint is a fact about consent, and no reject reason, prose field or
    status word can make one out of a report that was not one. `rejected` is
    deliberately not in `COMPLAINT_EVENTS` — an ESP refusing to carry the
    message is a fact about the address, and it keeps the bounce path.
    """
    return event in COMPLAINT_EVENTS


def _moment(value: Any) -> datetime | None:
    """An ISO-8601 instant from a translated body, or `None`. **Never a guess.**

    `None` means the provider named no time, and the service turns that into
    `now` where the row is written — one place, stated once. Doing it here would
    make "the provider said 09:31" and "we did not know" the same value at the
    seam that is supposed to tell them apart.

    A naive instant is read as UTC rather than refused: a product adapter posting
    a pre-normalised body may hand over a bare timestamp, and Django refuses to
    store a naive datetime at all, so the choice is between a documented default
    and a `RuntimeWarning` followed by a lost engagement.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _status_detail(payload: dict[str, Any]) -> str:
    """The provider's own words about this status, or an empty string."""
    for key in DETAIL_KEYS:
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _bounce_kind(*, event: str, status: str, payload: dict[str, Any]) -> str:
    """Hard or soft, for a bounce; empty for anything that is not one.

    Three answers in order, and the order is the argument (ADR comms-9):

    1. a status that is not `bounced` has no kind — `delivered` and `failed`
       are not statements about an address at all;
    2. `complained` and `rejected` are hard by their event type, whatever the
       reject reason says, because both are facts about the address and the
       relationship rather than about a transient delivery attempt;
    3. otherwise anymail's normalised `reject_reason` decides through
       `BOUNCE_KIND`.

    An unmapped or absent reason returns **empty**, meaning *this provider did
    not classify it*, and the service resolves that to hard. The default lives
    there and not here deliberately: `record_delivery_status` is reachable
    without an adapter, and two copies of "what do we do when nobody said" is
    the drift SEC-R1b was.
    """
    if status != Message.Status.BOUNCED.value:
        return ""
    if event in ALWAYS_HARD:
        return BounceKind.HARD.value
    reason = str(payload.get("reject_reason", "") or "").strip().lower()
    return BOUNCE_KIND.get(reason, "")


def _accepted_handle(*, mail: EmailMultiAlternatives, message: Message) -> str:
    """The join key a status webhook will name this message by. **The ESP's, if it gave one.**

    Every Anymail backend records what the ESP called the message it accepted on
    `message.anymail_status.message_id`, and every Anymail *webhook* reports
    status against that same id. So when a deployment is on an ESP, the ESP's id
    is the only handle that round-trips, and minting our own would guarantee
    that every bounce arrives naming a key no row here holds — the message stays
    `sent` forever, nobody is suppressed, and nothing anywhere says why. E1′
    found exactly that against Resend.

    The minted `<pk@domain>` handle stays as the fallback and is what a laptop
    on Mailpit, pytest on locmem and plain SMTP all still get: no ESP, no id, so
    the row's own primary key is the honest identifier (ADR comms-9 — and it is
    still not written into the mail, for the reason `EmailChannel` gives).

    A backend that reports a *set* of ids — Anymail's shape for a message with
    several recipients — is read only when the set holds exactly one, because
    this transport sends to exactly one recipient and anything else means the
    assumption underneath that has changed.

    **Absence is `None` and not falsiness.** Anymail says "this ESP told us
    nothing" by leaving `message_id` as `None`, and an id is whatever the vendor
    chose to make it — a UUID at Resend, an integer in Anymail's own test
    backend. Reading `reported or ""` would quietly discard the id `0` and mint
    over it, which is a bug that only ever shows up under the one backend a test
    suite uses.
    """
    reported = getattr(getattr(mail, "anymail_status", None), "message_id", None)
    if isinstance(reported, (set, frozenset)):
        reported = next(iter(reported)) if len(reported) == 1 else None
    handle = "" if reported is None else str(reported).strip()
    return handle or f"<{message.pk}@{_message_id_domain()}>"


class EmailChannel:
    """The built-in transport: Django's mail path, and therefore every backend.

    It does not know what an ESP is, and that is the design. Mailpit on a
    laptop, locmem under pytest, SMTP or an Anymail ESP backend in production —
    all of them are `EMAIL_BACKEND`, so this class is the same code on all
    three and a provider swap never reaches this file.

    **The handle is minted here and it is deterministic** — the message's own
    primary key — and since ADR comms-9 it is **not written into the mail**.
    Now a DIFFERENT string is: see `send` below, and the two costs comms-9
    wrote down at the bottom of this docstring, one of which is now paid.

    It used to be, as the `Message-ID` header, and the argument for that was
    good: one string served as the log's handle, the ESP's join key and the
    thing a provider could dedupe a retried send on. That also turned out to be
    what it served as. `provider_message_id` is the key `record_delivery_status` accepts
    a bounce against, so printing it into every mail handed the recipient — and
    anybody they forwarded to — a valid suppression key for themselves
    (vector (b)). The key now lives only in our storage.

    Two costs, both real and both stated rather than discovered:

    * **provider-side dedup of a retry is gone.** ~~Django stamps its own random
      `Message-ID` per send~~ — **now paid.** comms-9 named the deferred
      per-message nonce id as the way out and named its own trigger:
      comms-10 widened the window from "a crash" to "a
      day" by writing a `sending` row back to `queued` and sleeping. `send`
      below now stamps `Message-ID: <nonce@domain>` from
      `services.delivery_nonce`, which is derived from the row, identical on
      every attempt of one delivery, different for a second send — and, the
      whole point, **is not the suppression key**. The recipient can forward it
      to anybody; `record_delivery_status` has never heard of it. Temporal's
      at-least-once is still the honest limit and `deliver_message` still
      refuses to re-enter a transport for a row whose story is over; what
      changed is that a provider can now help;
    * **an ESP that reports only the header no longer round-trips.** That is the
      case a product's own adapter is for — a different `normalize_status` on
      the same protocol, joining on the ESP's own id — and it is the named
      trigger for ADR comms-9's deferred per-message nonce ids: a provider whose
      status webhooks cannot carry our delivery identifier.
    """

    slug = Channel.EMAIL.value

    def fakeness(self) -> Fakeness | None:
        """**Real, and it says so.** `None` is the claim, not a shrug.

        This adapter really hands each message to Django's mail path; whether
        mail then LEAVES the process is `EMAIL_BACKEND`'s question and is
        `apps.core.integrations`' `outbound-email` row, not this one's.

        Answering at all is the point. Before this protocol existed a transport that stayed
        silent was read as real, so this method's absence and a product's
        forgetfulness were the same thing to the census. Now the shipped real
        adapter is the worked example of claiming it.
        """
        return None

    def send(self, *, message: Message, subject: str, body: str, nonce: str = "") -> Sent:
        # **The header is back, and it is a different string.** ADR
        # comms-9 took `provider_message_id` out of the mail because it is the
        # key `record_delivery_status` accepts a bounce against and a header is
        # forwardable (vector (b)). That reasoning is untouched: what goes
        # on the wire here is `services.delivery_nonce`, an opaque digest that
        # is accepted by nothing, joins nothing, and cannot be turned back into
        # the pk. What it buys is the dedup comms-9 wrote down as the cost of
        # taking the old one out.
        #
        # Absent nonce → no header, and Django fills in its own random one, so
        # the mail is RFC-shaped either way and every caller that predates this
        # header gets exactly the behaviour it had.
        headers = {"Message-ID": f"<{nonce}@{_message_id_domain()}>"} if nonce else {}
        mail = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=str(settings.DEFAULT_FROM_EMAIL),
            to=[message.recipient.email],
            headers=headers,
        )
        accepted = mail.send()
        if not accepted:
            # The backend answered "nothing sent" without raising. Raising here
            # is what puts the attempt back in the workflow's hands rather than
            # recording a `sent` that never left.
            raise RuntimeError(f"The email backend accepted 0 of 1 message for {message.pk}.")
        return Sent(
            provider=_email_provider_name(),
            provider_message_id=_accepted_handle(mail=mail, message=message),
        )

    def normalize_status(self, *, payload: dict[str, Any]) -> ProviderStatus | None:
        """An ESP tracking event, in this product's three words.

        The keys read here — `event_type`, `message_id`, and the prose fields —
        are **Anymail's**, from `anymail.signals.AnymailTrackingEvent`, and the
        values are `anymail.signals.EventType`'s. That is why this maps cleanly:
        Anymail already normalises fourteen ESPs' webhook vocabularies into one,
        so a deployment that verifies its ESP's signature and posts the
        normalised event at the connections receiver gets this adapter for free,
        whichever ESP it is.

        `EMAIL_STATUS` is the mapping and its shape is the argument:
        `complained` and `rejected` join `bounced` because all three mean *this
        address must stop being mailed*, and collapsing them is what lets one
        suppression rule read one column. `failed` stays separate because it is
        the ESP's own machinery, not the address. Everything else — `opened`,
        `clicked`, `queued`, `deferred`, `sent`, and any word a future ESP
        invents — is `None`: not terminal, therefore not a status.

        **The collapse now carries a marker out with it** (ADR comms-9,
        amended). `complained` still maps to `bounced` here, because *this
        address must stop being mailed* is exactly what the suppression rule
        needs to read — but `is_complaint` travels beside it, and the service
        uses that to suppress **without transitioning the row**. A complaint
        follows a delivery, and a mapping that could only speak in statuses had
        to claim a delivered message failed.

        **The join is `message_id`.** This class mints a deterministic handle
        from the row's primary key and records it as `provider_message_id`, so
        an ESP that echoes our identifier round-trips. Since ADR comms-9 that
        identifier is no longer printed into the mail (see `send`), so an ESP
        that can only report the header it saw is a product's adapter to write —
        the same class shape, a different `normalize_status` — which is the
        reason this sits on the protocol at all, and the named trigger for the
        deferred nonce-id work.

        **The bounce kind is read here** (ADR comms-9), off anymail's normalised
        `reject_reason`, because what an ESP's words mean is the adapter's
        knowledge and not the service's. `complained` and `rejected` are hard by
        their own event type — a spam complaint is not a mail server having a
        bad hour. A bounce this provider did not classify comes back empty and
        the service resolves it, conservatively, to hard.

        **The `None` is accountable now** (ADR comms-13). The whole read lives
        in `_read` below and answers either a `ProviderStatus` or a
        `StatusDrop`; this method keeps the protocol's two-valued shape, and
        `explain_status_drop` hands the other half to `handle_status_webhook`,
        so the log line after a drop says *which* of the three drops it was
        rather than printing `ignored` over an event nobody managed to read.
        """
        read = self._read(payload=payload)
        return read if isinstance(read, ProviderStatus) else None

    def explain_status_drop(self, *, payload: dict[str, Any]) -> StatusDrop | None:
        """Why this body said nothing terminal — `None` when it did say something.

        The same traversal as `normalize_status`, run a second time rather than
        cached, because this is the **cold** path: the handler asks only after a
        body has already failed to produce a status, and one repeated
        translation on a webhook that is being dropped costs less than a seam
        holding two callers' results in step.
        """
        read = self._read(payload=payload)
        return None if isinstance(read, ProviderStatus) else read

    def normalize_engagement(self, *, payload: dict[str, Any]) -> ProviderEngagement | None:
        """An open or a click, in this product's two words — or `None` (ADR comms-9).

        The `ReportsEngagement` half, and it reads the SAME translated body
        `normalize_status` does: `EMAIL_ENGAGEMENT` names the two Anymail events
        that are engagement and everything else — every bounce, every deferral,
        every queue acknowledgement, and any word a future ESP invents — is
        `None`.

        **This method can never produce a status and `normalize_status` can never
        produce an engagement**, because the two maps are disjoint by
        construction: `EMAIL_STATUS` holds the terminal five and
        `EMAIL_ENGAGEMENT` holds the two, and no key is in both. That is what
        makes the handler's order — status first, engagement second — a matter of
        reading convenience rather than of precedence.

        The join is `message_id`, exactly as it is for a status; an event that
        names none is dropped here rather than recorded against a message this
        deployment had to guess at.

        `event_id` is usually empty through this seam and that is Anymail's
        shape, not a gap: on Resend and its siblings the event id is an HTTP
        header, and `esp_normalized` replays a stored body with no headers. The
        door fills it from the receiver's own `delivery_id`, which is the same
        string, read at the same door, before this method ever ran.
        """
        body, translated = self._translated(payload=payload)
        if not translated:
            return None
        event = str(body.get("event_type", "")).strip().lower()
        kind = EMAIL_ENGAGEMENT.get(event)
        if kind is None:
            return None
        provider_message_id = str(body.get("message_id", "") or "").strip()
        if not provider_message_id:
            # Real news about a message the provider would not name. There is no
            # row to hang it on and inventing one is worse than dropping it.
            return None
        return ProviderEngagement(
            provider_message_id=provider_message_id,
            kind=kind,
            # A click's destination only. An `opened` carrying one would be a
            # link for an event that has none, and the database refuses it.
            url=(
                str(body.get("click_url", "") or "")
                if kind == MessageEngagement.Kind.CLICKED.value
                else ""
            ),
            occurred_at=_moment(body.get("timestamp", "")),
            provider_event_id=str(body.get("event_id", "") or "").strip(),
        )

    def _translated(self, *, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """The body in Anymail's vocabulary, and whether it got there.

        Extracted so the status read and the engagement read share ONE
        translation rather than each carrying a copy: a raw ESP body has to be
        put through Anymail once whichever question is being asked of it, and two
        copies of that decision is the drift SEC-R1b was, one seam over.

        A **raw ESP body**, straight off that vendor's webhook — Resend's
        `{"type": "email.bounced", "data": {…}}` and every other shape Anymail
        knows — goes through `esp_normalized`, which runs Anymail's own
        translation for whichever ESP `EMAIL_BACKEND` names and hands back the
        keys both readers use. So from the caller's next line down there is
        exactly one vocabulary and neither fork learns which door it came in.

        The test is the *absence* of `event_type` rather than the presence of
        anything: a payload that already carries Anymail's own key is already
        normalised — by a product's adapter, by a deployment that does mount
        Anymail's view, or by a fixture — and re-translating it would be reading
        one vendor's words out of another's.
        """
        if "event_type" in payload:
            return payload, True
        normalized = esp_normalized(payload)
        if normalized is not None:
            return normalized, True
        return payload, False

    def _read(self, *, payload: dict[str, Any]) -> ProviderStatus | StatusDrop:
        """One pass over a status body: the status, or the account of its absence.

        Every `return` on the drop side names which of the three it is, which is
        the property ADR comms-13 asked for: the three ways this can end are
        three different findings for three different people — nobody, a
        deployment, and a provider — and the caller can only tell them apart if
        this method says so at the point it knows.
        """
        payload, translated = self._translated(payload=payload)
        event = str(payload.get("event_type", "")).strip().lower()
        if not translated or not event:
            # **Nothing was read.** Either no translation was available for this
            # vendor's body (no Anymail ESP configured, no view for it, a shape
            # the translation could not make sense of), or one ran and produced
            # no word. Both are the same finding to whoever has to fix it, and
            # it is a finding about the *deployment* —
            # `ignored` may no longer be printed here.
            return StatusDrop(reason=DROP_UNTRANSLATABLE, event_type=event)
        status = EMAIL_STATUS.get(event)
        if status is None:
            # Read, understood, and not terminal — an open, a click, a deferral.
            # The door is working and the run is still waiting.
            return StatusDrop(reason=DROP_NON_TERMINAL, event_type=event)
        provider_message_id = str(payload.get("message_id", "") or "").strip()
        if not provider_message_id:
            # Terminal, and unjoinable. A separate word because it is a separate
            # fault: the provider said something real about a message it would
            # not name, and `ignored` said nothing about that at all.
            return StatusDrop(reason=DROP_NO_MESSAGE_ID, event_type=event)
        return ProviderStatus(
            provider_message_id=provider_message_id,
            status=status,
            detail=_status_detail(payload),
            bounce_kind=_bounce_kind(event=event, status=status, payload=payload),
            # Which *kind* of news this is (ADR comms-9, amended). The mapping
            # above still collapses `complained` onto `bounced` — that is what
            # makes one suppression rule read one word — and this is what stops
            # the service writing that word onto a row the provider never said
            # anything new about.
            is_complaint=_is_complaint(event),
        )


# The built-in transport, registered at import. Every other channel a product
# adds registers from that product's `AppConfig.ready()` — see
# `register_channel`.
register_channel(EmailChannel())


# --- The reference adapter: a channel whose transport is a Connection -------------


@dataclass(frozen=True)
class ConnectionChannel:
    """A channel carried by one of the tenant's own `Connection` rows.

    **This is the shape an SMS or chat vendor takes in this product**, and it
    ships as a worked adapter rather than as a vendor: a product registers one
    from its `AppConfig.ready()` naming the provider slug it opened a connection
    under, and nothing in this app changes.

        register_channel(ConnectionChannel(slug="sms", provider="twilio", path="/Messages.json"))

    Three properties are the reason it is a class here rather than an example in
    a docstring:

    * **the credential is never in this module.** It is read inside
      `connections.client.http_client`, from the connection's encrypted column,
      and put on the request as a header. Nothing here holds a token in a local
      variable it might log;
    * **the call happens from an activity.** `deliver_message` is what invokes a
      channel, so this runs on a worker thread with a retry policy and a
      deadline around it — never inside a request. That is house rule "anything
      that waits or retries is a workflow", kept by construction;
    * **the POST is idempotent by key.** `post_idempotent(key=message.pk)` sends
      the message's own primary key, which is stable across every retry of one
      logical send, so a vendor that honours the header does not text somebody
      twice because our worker was restarted.

    `address` names which field on the `Recipient` this channel reaches — `phone`
    for SMS, `chat_handle` for chat — because that is the only thing that
    genuinely differs between two `ConnectionChannel`s, and a missing address is
    a refusal rather than a request to nowhere.

    `transport` is how a test injects `httpx.MockTransport`: the same seam
    `http_client` documents, so what a test exercises is the retry policy and
    the headers the product ships rather than a copy of them.
    """

    slug: str
    provider: str
    path: str = "/messages"
    address: str = "phone"
    transport: httpx.BaseTransport | None = None

    def fakeness(self) -> Fakeness | None:
        """Real: it reaches a gateway over the network. See `EmailChannel`."""
        return None

    def send(self, *, message: Message, subject: str, body: str, nonce: str = "") -> Sent:
        connection = (
            # The system actor: a provider looking up its own credential is the
            # platform reading for itself, and `list_connections` asks
            # `connection.read` since Phase R (ADR core-27). There is no person
            # here — a send runs inside an activity — and `allows` passes a
            # `system` actor at step 1 while the scoped manager still fences the
            # read to this tenant.
            list_connections(tenant=message.tenant, actor=system_actor(message.tenant))
            .filter(provider=self.provider, status=Connection.Status.CONNECTED)
            .first()
        )
        if connection is None:
            raise NotFound(
                f"This tenant has no connected {self.provider!r} connection to send "
                f"{self.slug!r} through."
            )
        to = str(getattr(message.recipient, self.address, "") or "").strip()
        if not to:
            # Fail closed. A send with no address is not a message that went
            # somewhere unhelpful; it is a message that went nowhere, and the row
            # should say so rather than say `sent`.
            raise Invalid(
                {self.address: [f"This recipient has no {self.address} to reach them on."]}
            )
        with http_client(connection, transport=self.transport) as client:
            response = post_idempotent(
                client,
                self.path,
                key=str(message.pk),
                json={"to": to, "subject": subject, "body": body},
            )
        response.raise_for_status()
        return Sent(provider=self.provider, provider_message_id=_vendor_handle(response, message))

    def normalize_status(self, *, payload: dict[str, Any]) -> ProviderStatus | None:
        """Nothing, until a product's vendor adapter says otherwise.

        A vendor's delivery-receipt vocabulary is the vendor's, and inventing one
        here would be inventing a mapping nobody can check. A product that wants
        SMS delivery receipts subclasses or replaces this method and adds its
        connection slug to `STATUS_PROVIDERS`.
        """
        return None


def _vendor_handle(response: httpx.Response, message: Message) -> str:
    """What the vendor called this message, or our own id as the fallback.

    Falling back rather than raising: a vendor that accepted the message and
    answered `204` has still accepted it, and refusing to record that because
    the body was empty would turn a successful send into a retry.
    """
    try:
        body = response.json()
    except ValueError:
        return str(message.pk)
    if not isinstance(body, dict):
        return str(message.pk)
    # `name` joined at T3, for FCM: its HTTP v1 send answers
    # `{"name": "projects/<p>/messages/<id>"}` and nothing else, so a push
    # gateway would otherwise record our own primary key as the vendor's handle
    # — which is the one column a status webhook has to join on. Last in the
    # tuple deliberately: it is the least specific of the four names and a
    # vendor answering both `id` and `name` means the former.
    for key in ("id", "message_id", "sid", "name"):
        value = body.get(key)
        if value:
            return str(value)
    return str(message.pk)


# --- The fake: the SMS path, proved with no vendor and no account ----------------


#: What `Message.provider` records for anything the fake carried. Every row this
#: transport touches says `fake-sms`, so no message log ever claims a real
#: vendor sent something a fake did.
FAKE_SMS_PROVIDER = "fake-sms"


@dataclass(frozen=True)
class FakeSms:
    """One text this deployment pretended to send. `mail.outbox`, for SMS."""

    to: str
    body: str
    provider_message_id: str


#: Everything `FakeSmsChannel` has "sent", in order. A module-level list for the
#: same reason `django.core.mail.outbox` is one: a test asserts against what went
#: out, and a transport that swallowed its messages could not be tested at all.
fake_sms_outbox: list[FakeSms] = []


class FakeSmsChannel:
    """The worked SMS transport: a complete send with nothing on the other end.

    It exists for the reason `connections.ExampleProvider` and `apps/example` do
    — so the path is exercised by the test suite and by a developer's own
    machine from an empty database, with **no vendor, no account and no
    network** — and it follows the same convention: registered at import,
    obviously fake by name, and replaced by a product's real transport under the
    same slug from that product's `AppConfig.ready()`.

    Three things keep it from ever being mistaken for a vendor:

    * every row it carries records `provider="fake-sms"`, so the message log
      names it;
    * every send logs at **warning**, so a deployment running it is loud in the
      log sink rather than quietly texting nobody;
    * `ConnectionChannel` above is the real shape, sitting immediately next to
      it, so "what do I replace this with" has an answer in the same file.

    It reports delivery statuses in the same normalised vocabulary
    `EmailChannel` reads, which is what lets an escalation's *first* step be an
    SMS whose `delivered` webhook stops the chain — the property C2b-4 exists to
    prove — without a vendor to send it.
    """

    slug = Channel.SMS.value

    def send(self, *, message: Message, subject: str, body: str, nonce: str = "") -> Sent:
        to = str(message.recipient.phone or "").strip()
        if not to:
            raise Invalid({"phone": ["This recipient has no phone to reach them on."]})
        handle = f"{FAKE_SMS_PROVIDER}:{message.pk}"
        fake_sms_outbox.append(FakeSms(to=to, body=body, provider_message_id=handle))
        log.warning(
            "comms.fake_sms.sent",
            provider=FAKE_SMS_PROVIDER,
            message_id=str(message.pk),
            recipient_id=str(message.recipient_id),
        )
        return Sent(provider=FAKE_SMS_PROVIDER, provider_message_id=handle)

    def fakeness(self) -> Fakeness:
        """**Says so, out loud, to the integrations census.**

        The fourth thing that keeps this from being mistaken for a vendor, and
        the first one that reaches somebody who is not reading this file: the
        row this produces is what `scripts/setup.sh`'s epilogue prints on a
        fresh clone, what `manage.py integrations` answers, what the standing
        prober watches, and what `deploy/release.sh --wall` refuses to release
        past.
        """
        return Fakeness(
            detail=(
                "FakeSmsChannel holds the 'sms' slot: every text is appended to "
                "providers.fake_sms_outbox and logged at warning, and nothing leaves "
                "this process — including the STOP a real recipient sends back."
            ),
            remedy=(
                "register_channel(TwilioSmsChannel()) from your own AppConfig.ready(), "
                "then give each tenant a 'comms-sms' connection and point the Messaging "
                "Service status callback at this deployment "
                "(docs/runbooks/deploy.md, 'The other transports: SMS and push')."
            ),
        )

    def normalize_status(self, *, payload: dict[str, Any]) -> ProviderStatus | None:
        """The same three words, read out of the same normalised shape.

        Deliberately `EMAIL_STATUS` rather than a second mapping: a fake's
        vocabulary is ours to choose, and choosing the one the product already
        reads means this transport proves the *status contract* end to end
        instead of proving a second contract nobody ships.
        """
        return EmailChannel().normalize_status(payload=payload)

    def explain_status_drop(self, *, payload: dict[str, Any]) -> StatusDrop | None:
        """And the same account of a drop, for the same reason.

        Delegated rather than re-derived: a fake whose *diagnostics* diverged
        from the transport it stands in for would be a fake that proves a
        different contract from the one shipped, which is the one thing it must
        not be.
        """
        return EmailChannel().explain_status_drop(payload=payload)


register_channel(FakeSmsChannel())


# --- The real SMS transport: Twilio ----------------------------------------------
#
# ADR comms-9's stack ruling (SMS = Twilio) and ING-4's T2 rung. What is new here
# is **the way back**: T1 pinned `record_delivery_status`'s STOP contract at the
# service and proved no real opt-out could reach it, because nothing on the
# `sms` slot could read a word Twilio says. This is that half.
#
# **It ships registered-on-demand, not enabled.** `FakeSmsChannel` above holds
# the `sms` slot on a fresh clone, and a deployment that has a Twilio account
# puts the real one in its place from its own `AppConfig.ready()` —
# `register_channel(TwilioSmsChannel())` — which is the replacement the fake's
# own docstring documents. Enabling it here would mean a template whose test
# suite and whose laptop both need vendor credentials to send a text, and the
# credentials are per TENANT (a `Connection` row) rather than per deployment, so
# there is no setting this module could read to decide the question anyway.
#
# **And this comment is no longer the only place that says so.**
# The whole enablement procedure — how to tell
# which transport is holding a slot, the `AppConfig.ready()` replacement, the
# per-tenant connection, and the status callback without which a `STOP` is
# silently dropped — is `docs/runbooks/deploy.md`, "The other transports: SMS
# and push". An operator does not read `providers.py`, and a fact that lives
# only here is a fact that is not documented.

#: What `Message.provider` records for anything Twilio carried, and the
#: `Connection.provider` slug the credentials live on. Both are the same word in
#: two registries on purpose: the connection IS the account.
TWILIO_PROVIDER = "twilio"

#: The connection slug this transport's status webhooks arrive under — the entry
#: already in `STATUS_PROVIDERS` below, named here so the adapter and the map
#: cannot drift.
SMS_STATUS_PROVIDER = "comms-sms"

#: The header Twilio puts its signature in. A declared constant and never a
#: literal at the read (house rule 40): a second spelling of a header name fails
#: OPEN — the read finds nothing, `verify_sms_webhook` answers "no opinion", and
#: the door quietly falls back to a credential Twilio does not send.
TWILIO_SIGNATURE_HEADER = "X-Twilio-Signature"

#: Twilio's `MessageStatus` words, mapped to the three this product keeps. Absent
#: means "says nothing terminal" — `accepted`, `scheduled`, `queued`, `sending`,
#: `sent` and `read` are all real events and none of them is an answer about
#: arrival, exactly as a deferral is not one on the email side.
#:
#: `undelivered` and `failed` are deliberately different words here and not one:
#: Twilio says `undelivered` when the carrier refused the message (a fact about
#: the address, which is what `bounced` means in this product and what
#: suppression reads) and `failed` when the send itself never happened — an
#: unroutable account, a suspended balance, our own configuration. Collapsing
#: them would suppress a person for our billing problem.
TWILIO_STATUS: dict[str, str] = {
    "delivered": Message.Status.DELIVERED.value,
    "undelivered": Message.Status.BOUNCED.value,
    "failed": Message.Status.FAILED.value,
}

#: Twilio's error code for **the opt-out**: "attempt to send to unsubscribed
#: recipient". This is what a `STOP` text becomes by the time it reaches us — the
#: person tells Twilio, Twilio records the opt-out against the number, and the
#: next message we hand it comes back `undelivered` with this code against OUR
#: message's sid. It is consent news wearing a delivery status, which is exactly
#: what `ProviderStatus.is_complaint` exists to say: the recipient is suppressed
#: and the message row is left where it was (ADR comms-9 as amended, and T1's
#: `test_a_stop_suppresses_the_recipient_and_leaves_the_message_row_alone`).
TWILIO_STOP_CODE = "21610"

#: Twilio's error codes on an `undelivered`, split into the two kinds of bounce
#: (ADR comms-9). Absent means **the vendor did not classify**, which `services`
#: resolves to hard — the conservative direction, stated once there.
#:
#: The split is the same judgement `BOUNCE_KIND` makes one channel over: a code
#: that is a fact about the ADDRESS is hard, and a code that means "the handset
#: was not reachable just now" is soft. `30001` (queue overflow) and `30003`
#: (unreachable handset — off, out of range, roaming) are the two that describe a
#: moment rather than a number; everything else here says the number is wrong,
#: is not a mobile, or will not accept our traffic again.
#: `21610` is in this dict and is **deliberately unreachable through
#: `normalize_status`**: the opt-out fork returns above it. It is kept because a
#: kind is a fact about the code and not about which branch reads it — a reader
#: comparing this table with Twilio's own should find every terminal code in it
#: — and because the day somebody removes the fork, the classification is still
#: right rather than absent.
TWILIO_BOUNCE_KIND: dict[str, str] = {
    "21211": BounceKind.HARD.value,  # invalid 'To' number
    "21408": BounceKind.HARD.value,  # this account cannot send to that region
    "21610": BounceKind.HARD.value,  # unsubscribed — see TWILIO_STOP_CODE
    "21614": BounceKind.HARD.value,  # not a mobile number
    "30001": BounceKind.SOFT.value,  # queue overflow
    "30003": BounceKind.SOFT.value,  # unreachable handset
    "30004": BounceKind.HARD.value,  # message blocked
    "30005": BounceKind.HARD.value,  # unknown destination handset
    "30006": BounceKind.HARD.value,  # landline or unreachable carrier
    "30007": BounceKind.HARD.value,  # carrier violation — filtered as spam
}

#: The words a person texts to opt out, as Twilio's own Advanced Opt-Out
#: publishes them. Read as a **fallback** to the `OptOutType` field, which is the
#: field Twilio fills when a deployment has Advanced Opt-Out switched on: a
#: deployment without it gets an ordinary inbound message whose whole body is one
#: of these words.
TWILIO_STOP_WORDS: frozenset[str] = frozenset(
    {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}
)

#: What a body of that shape is called in the drop vocabulary's `event_type`
#: field. One word, because a dashboard groups by it.
TWILIO_OPT_OUT_EVENT = "opt_out"

#: The credential keys a `comms-sms` connection carries, in Twilio's own console
#: spelling. `auth_token` is BOTH the API credential and the signing key — Twilio
#: signs every webhook with the account's auth token — which is why this adapter
#: reads it rather than `Connection.webhook_secret`: the two would be one string
#: written twice, and the day somebody rotated one the door would still open.
#: `access_token` is the house's own reserved key and is read as the fallback, so
#: a connection created through the ordinary OAuth-shaped door still works.
TWILIO_ACCOUNT_SID_KEY = "account_sid"
TWILIO_AUTH_TOKEN_KEY = "auth_token"  # pragma: allowlist secret — a KEY NAME
TWILIO_FROM_KEY = "from_number"


def _twilio_auth_token(connection: Connection) -> str:
    """The account's auth token off the encrypted row. **Never from settings.**

    The same decision `config/settings/base.py` records for every ESP webhook
    secret, and for the same reason: this product's inbound signatures are
    checked per TENANT, and a deployment-wide token in settings would be every
    tenant's Twilio account sharing one credential. The value is decrypted on
    read by `Connection.credentials` and is never logged here.
    """
    credentials = connection.credentials or {}
    return str(credentials.get(TWILIO_AUTH_TOKEN_KEY) or connection.access_token or "")


def status_callback_url(connection: Connection) -> str:
    """The URL Twilio posts to, built the way this deployment builds every link.

    `PUBLIC_BASE_URL` plus the receiver's own reversed path, so there is one
    answer to "where do our webhooks arrive" and a worker with no request can
    give it. It is used twice and that is the point: it is handed to Twilio on
    the way OUT as `status_callback`, and it is what the signature is verified
    against on the way BACK, because Twilio signs the URL it was given.

    The consequence is worth stating because it is a refusal a deployment can
    walk into: a `PUBLIC_BASE_URL` that does not match the URL Twilio actually
    called — a proxy rewriting the host, a stale value after a domain move —
    makes every signature fail. That is fail-closed and deliberate; the fix is
    the setting, and `comms.sms.signature_refused` is the line that says so.
    """
    path = reverse("api:connection-webhook", kwargs={"connection_id": connection.pk})
    return f"{str(settings.PUBLIC_BASE_URL).rstrip('/')}{path}"


def _twilio_field(payload: Mapping[str, Any], *names: str) -> str:
    """The first of these fields Twilio actually filled, stripped."""
    for name in names:
        value = str(payload.get(name, "") or "").strip()
        if value:
            return value
    return ""


def _is_opt_out(payload: Mapping[str, Any]) -> bool:
    """Whether this body is a person texting STOP.

    Two readings and the declared field wins: `OptOutType` is what Twilio fills
    when Advanced Opt-Out is on, and the body text is what a deployment without
    it receives. Both are the same fact and neither is a status.
    """
    declared = _twilio_field(payload, "OptOutType").lower()
    if declared:
        return declared == "stop"
    return _twilio_field(payload, "Body").lower() in TWILIO_STOP_WORDS


# NOT `frozen=True`, and the reason is the registry rather than taste:
# `ChannelProvider.slug` is a protocol VARIABLE, so a class satisfies it only
# with a settable attribute, and a frozen dataclass offers a read-only one.
# `ConnectionChannel` above is frozen and gets away with it because nothing in
# the tree hands it to `register_channel` under that annotation; this one is
# registered by a product's `ready()` and by this module's tests, so it has to
# satisfy the protocol mypy checks rather than the one prose describes.
@dataclass
class TwilioSmsChannel:
    """The SMS transport: Twilio's REST API out, Twilio's status callbacks back.

    **Three properties, and they are why this is a class and not a page of
    prose in the fake above.**

    * **the credential is never in this module and never in settings.** Account
      sid, auth token and sending number are read off the tenant's own
      `comms-sms` `Connection` — encrypted at rest, one account per tenant —
      exactly as every ESP webhook secret in this product already is;
    * **the call happens from an activity.** `deliver_message` is what invokes a
      channel, so the vendor call runs on a worker with a retry policy and a
      deadline around it, never inside a request;
    * **the way back is wired at the moment of sending.** `status_callback` is
      handed to Twilio on every message, so a deployment does not have to
      remember to paste a URL into a console for delivery receipts and opt-outs
      to arrive. The console still owns the *inbound message* webhook, which is
      a different hook and is named as what it cannot set.

    `http_client` is the SDK's own injection seam and is how a test drives this
    without an account: pass anything with the `request(...)` signature
    `twilio.http.HttpClient` declares and the vendor library's own request
    building, retries and response parsing still run.
    """

    slug: str = Channel.SMS.value
    provider: str = SMS_STATUS_PROVIDER
    http_client: Any = None

    def _connection(self, tenant: Any) -> Connection:
        connection = (
            # The system actor, for the reason the send path gives above.
            list_connections(tenant=tenant, actor=system_actor(tenant))
            .filter(provider=self.provider, status=Connection.Status.CONNECTED)
            .first()
        )
        if connection is None:
            raise NotFound(
                f"This tenant has no connected {self.provider!r} connection to send "
                f"{self.slug!r} through."
            )
        return connection

    def send(self, *, message: Message, subject: str, body: str, nonce: str = "") -> Sent:
        """Hand the text to Twilio, or raise. **Fails closed on every absence.**

        `subject` is unused and that is the channel and not an oversight: a text
        has a body and nothing else, which is why `send()` refuses an SMS
        template with a subject one layer up.

        `nonce` is unused too, and for a reason worth stating rather than
        leaving as silence: Twilio has no caller-supplied message identifier on
        the send API — the `sid` is theirs and is minted on acceptance — so
        there is nothing here to stamp it on. The parameter is accepted because
        the protocol carries it; an adapter for a vendor that DOES take one
        (an `Idempotency-Key`, a client reference) should pass it through, which
        is what `ConnectionChannel` and `DevicePushChannel` already do by keying
        their POST on the message.
        """
        connection = self._connection(message.tenant)
        to = str(message.recipient.phone or "").strip()
        if not to:
            raise Invalid({"phone": ["This recipient has no phone to reach them on."]})
        credentials = connection.credentials or {}
        account_sid = str(credentials.get(TWILIO_ACCOUNT_SID_KEY, "") or "").strip()
        token = _twilio_auth_token(connection)
        sender = str(credentials.get(TWILIO_FROM_KEY, "") or "").strip()
        missing = [
            name
            for name, value in (
                (TWILIO_ACCOUNT_SID_KEY, account_sid),
                (TWILIO_AUTH_TOKEN_KEY, token),
                (TWILIO_FROM_KEY, sender),
            )
            if not value
        ]
        if missing:
            # Named, because "the text did not go" with no reason is the support
            # ticket this product exists not to generate. The VALUES are never
            # logged or raised — only which key is empty.
            raise Invalid({"credentials": [f"This connection is missing {', '.join(missing)}."]})
        client = TwilioClient(account_sid, token, http_client=self.http_client)
        created = client.messages.create(
            to=to,
            from_=sender,
            body=body,
            status_callback=status_callback_url(connection),
        )
        return Sent(provider=TWILIO_PROVIDER, provider_message_id=str(created.sid))

    def normalize_status(self, *, payload: dict[str, Any]) -> ProviderStatus | None:
        """One Twilio status callback, in this product's vocabulary — or `None`.

        **The opt-out is the branch this exists for.** `undelivered` with
        error `21610` is what a `STOP` text has become by the time Twilio tells
        us about it, and it is consent news rather than address news: the flag
        goes up, `record_delivery_status` forks into `_record_complaint`, the
        person is suppressed and the message row is not touched. Reading it as
        an ordinary hard bounce would write `bounced` onto a row whose message
        Twilio in fact refused to send — and would say the address is dead when
        what happened is that its owner asked us to stop.
        """
        slug = TWILIO_STATUS.get(_twilio_field(payload, "MessageStatus", "SmsStatus").lower())
        if slug is None:
            return None
        sid = _twilio_field(payload, "MessageSid", "SmsSid")
        if not sid:
            return None
        code = _twilio_field(payload, "ErrorCode")
        detail = _twilio_field(payload, "ErrorMessage")
        if code and not detail:
            # Twilio does not always send the prose, and a support agent reading
            # `Message.error` needs something to search for.
            detail = f"Twilio error {code}"
        if code == TWILIO_STOP_CODE:
            return ProviderStatus(
                provider_message_id=sid, status=slug, detail=detail, is_complaint=True
            )
        return ProviderStatus(
            provider_message_id=sid,
            status=slug,
            detail=detail,
            bounce_kind=TWILIO_BOUNCE_KIND.get(code, ""),
        )

    def explain_status_drop(self, *, payload: dict[str, Any]) -> StatusDrop | None:
        """Why a Twilio body said nothing terminal, in the door's closed vocabulary.

        **The inbound STOP lands here, as `no_message_id`, and that is the honest
        answer rather than a convenient one.** A person texting STOP produces an
        INBOUND message webhook: it carries their number, the word, and the sid
        of *their* message — and no reference at all to anything we sent. The
        event was read and it is terminal, and it names no handle to join it to a
        row with, which is precisely what `DROP_NO_MESSAGE_ID` says. Suppressing
        on it would mean resolving a person from a phone number and picking a
        message to file the complaint against, which is a write this door cannot
        make honestly — see ADR comms-9's own note that
        the join is the provider's handle.

        It costs nothing in practice and the reason is `TWILIO_STOP_CODE`: Twilio
        remembers the opt-out itself and refuses the next message we hand it,
        which arrives here as a status against a sid we do know. The person is
        suppressed on that report, one message later at the worst.
        """
        if _is_opt_out(payload):
            return StatusDrop(reason=DROP_NO_MESSAGE_ID, event_type=TWILIO_OPT_OUT_EVENT)
        word = _twilio_field(payload, "MessageStatus", "SmsStatus").lower()
        if not word:
            return StatusDrop(reason=DROP_UNTRANSLATABLE)
        if word in TWILIO_STATUS:
            # A terminal word that produced no status: it named no sid. Same
            # finding as the opt-out's and the same remedy — a provider fault.
            return StatusDrop(reason=DROP_NO_MESSAGE_ID, event_type=word)
        return StatusDrop(reason=DROP_NON_TERMINAL, event_type=word)


def verify_sms_webhook(
    *, connection: Connection, body: bytes, headers: Mapping[str, str]
) -> bool | None:
    """Twilio's own signature check, driven by Twilio. Or no opinion.

    Registered on `apps/connections`' verifier registry for the `comms-sms` slug,
    and answering that registry's three values exactly as the ESP verifier above
    does:

    * `True` / `False` — the request carried an `X-Twilio-Signature`, the
      connection is carrying an auth token, and **the vendor's own
      `RequestValidator` recomputed the signature over the URL and the form
      fields and compared it**. This repository computes nothing (house rule 43's
      disposition, the anymail precedent one function up);
    * `None` — *no opinion*: no Twilio signature on the request, or no auth token
      on the connection. The receiver falls back to its own HMAC, which is always
      present and always checked, so a house-signed body at a `comms-sms`
      connection keeps working — which is what `test_escalation.py` has always
      posted.

    **No branch returns `True` without a signature having been verified**, which
    is the property to keep if this is ever edited.

    The JSON case is deliberately not supported and is not silent: Twilio's
    validator covers a JSON body through a `bodySHA256` query parameter, and this
    door's URL carries no query, so a JSON post from Twilio cannot verify and is
    refused rather than waved through.
    """
    signature = ""
    for name, value in headers.items():
        if str(name).lower() == TWILIO_SIGNATURE_HEADER.lower():
            signature = str(value or "").strip()
            break
    if not signature:
        return None
    token = _twilio_auth_token(connection)
    if not token:
        return None
    params: dict[str, str] = dict(
        parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True)
    )
    if RequestValidator(token).validate(status_callback_url(connection), params, signature):
        return True
    log.info("comms.sms.signature_refused", connection_id=str(connection.pk))
    return False


# --- The way back: a provider's status webhook -----------------------------------
#
# `apps/connections` owns the one signature-verified inbound route in the
# product (ADR comms-3). It stores every delivery and then calls whatever
# handler the receiving app registered for that connection's provider slug;
# `apps/comms/apps.py`'s `ready()` registers the function below under
# `STATUS_PROVIDER`. Nothing here is a route, nothing here is `auth=None`, and
# there is no second signature scheme to get wrong.


#: The `Connection.provider` a deployment gives the connection its ESP posts
#: status webhooks to. A slug rather than "email", because it names an
#: *integration* — the thing that holds the webhook secret — and a product may
#: hold several, one per ESP, each with its own connection row and secret.
STATUS_PROVIDER = "comms-email"

#: And the same for every other channel kind that can report back. The map is
#: what tells the handler **which adapter's vocabulary a payload is written in**
#: — comms-a hard-coded email, which was right while email was the only kind
#: that could report and is a bug the moment SMS can. A product adding a second
#: ESP or a real SMS vendor adds its connection slug here beside the channel it
#: speaks for; the webhook route, the signature check and the handler are
#: unchanged.
STATUS_PROVIDERS: dict[str, str] = {
    STATUS_PROVIDER: Channel.EMAIL.value,
    SMS_STATUS_PROVIDER: Channel.SMS.value,
}

#: And **which verifier checks the signature on each slug's deliveries**. A map
#: rather than one function for all of them, because a scheme belongs to whoever
#: invented it: Resend signs with Svix and Twilio signs with an HMAC over the URL
#: and the form fields, and the one thing both verifiers have in common is that
#: neither of them is written here — each delegates to the vendor's own library
#: (house rule 43's disposition; ADR comms-12's seam, one channel over).
#:
#: A slug absent from this map gets `verify_status_webhook`, which answers
#: "no opinion" on every deployment that is not sending through an Anymail ESP —
#: so a product's new connection slug keeps the door's own HMAC until somebody
#: registers a verifier for it, which is the fail-safe direction.
STATUS_VERIFIERS: dict[str, Any] = {
    STATUS_PROVIDER: verify_status_webhook,
    SMS_STATUS_PROVIDER: verify_sms_webhook,
}

#: The media type a form-encoded delivery arrives as. Twilio posts one for every
#: messaging webhook it sends — Resend and most ESPs post JSON — so this door
#: reads both, and reads WHICH by the sender's own declared content type rather
#: than by guessing from the bytes: a JSON body parsed as a form does not fail,
#: it produces one nonsense key, and an adapter would then be reading a body
#: nobody sent.
FORM_MEDIA_TYPE = "application/x-www-form-urlencoded"


def _content_type(received: InboundWebhook) -> str:
    """What the sender said the body was, off the receiver's own stored headers."""
    for name, value in (received.headers or {}).items():
        if str(name).lower() == "content-type":
            return str(value or "").split(";")[0].strip().lower()
    return ""


def _record_engagement(*, received: InboundWebhook, engagement: ProviderEngagement) -> None:
    """One read engagement, recorded. **The only new write this door does.**

    Split out of the handler rather than inlined so the handler keeps reading as
    the list of outcomes its docstring claims, and so the two `except NotFound`
    stories stay separate: a status naming an unknown message and an engagement
    naming one are different log lines for the same reason the three drop
    reasons are different log lines — a dashboard that grouped them could not
    tell "an ESP is reporting on somebody else's mail" from "our engagement
    wiring is pointed at the wrong tenant".

    **The hat is the tenant's root**, for the same reason the status path's is:
    an ESP has no idea a branch exists, and the message it is reporting on may
    belong to any of them. Where the ROW lands is a different question and is not
    this hat's: `MessageEngagement.derive_org_from` puts it in the message's own
    branch (ADR comms-9, C9), which is what makes it readable by the people whose
    message it is about.

    **The event id falls back to the receiver's `delivery_id`**, and that is not
    a convenience. Several ESPs put the event's identity in an HTTP header —
    Resend's is `svix-id` — which an adapter reading a body alone cannot see, and
    which `apps/connections` has ALREADY read and stored on the row as the key it
    dedupes redeliveries on. So the same string that makes the receiver
    idempotent makes the engagement idempotent, rather than a second identity
    being invented one layer up. An adapter that CAN read an event id out of its
    body wins, because it is reading the vendor's own field.
    """
    from apps.comms import services  # deferred: services imports this module

    tenant = received.tenant
    acting = system_actor(tenant, root_organization(tenant=tenant))
    try:
        services.record_engagement(
            tenant=tenant,
            actor=acting,
            provider_message_id=engagement.provider_message_id,
            kind=engagement.kind,
            occurred_at=engagement.occurred_at,
            url=engagement.url,
            provider_event_id=engagement.provider_event_id or str(received.delivery_id or ""),
        )
    except NotFound:
        # No message in THIS connection's tenant carries that provider id. The
        # cross-tenant wall answering, and the same not-there/not-yours refusal
        # the status path gets — see `handle_status_webhook`'s own note on the
        # two sources this catch cannot tell apart.
        log.info(
            "comms.engagement.unknown_message",
            inbound_webhook_id=str(received.pk),
            tenant_id=str(tenant.pk),
            kind=engagement.kind,
        )
        return
    log.info(
        "comms.engagement.recorded",
        inbound_webhook_id=str(received.pk),
        connection_id=str(received.connection_id),
        kind=engagement.kind,
    )


def handle_status_webhook(*, received: InboundWebhook, actor: Actor) -> None:
    """One stored delivery, read as a status and recorded. **Or dropped, quietly.**

    Several ways this ends and every one of them leaves the receiver's 202
    alone, because the store already happened and the ESP's retry is the
    recovery path for anything that did not. **Each one has its own log name,
    and that is the contract** (ADR comms-13): a drop this door cannot explain
    is a drop nobody can act on, and one name over three causes is how a
    deployment fault once turned into a field test blaming the worker.

    * the body is neither a JSON object nor a form post with pairs in it —
      logged, dropped. Which language it is read in is the sender's own
      `Content-Type` and never a guess: ESPs post JSON and Twilio posts a form,
      and a parser that raised here would turn somebody else's malformed payload
      into a 500 on our door;
    * no transport is registered for the connection's slug —
      `comms.status.no_adapter`. Nothing to read the payload *with*;
    * the event is an **open or a click** — `comms.engagement.recorded`, and a
      `MessageEngagement` row (ADR comms-9). The message row does not move: an
      engagement is a provider's inference about a person, not news about
      whether the message arrived, and the delivery run keeps waiting exactly as
      it did. An engagement naming a message this tenant does not hold is
      `comms.engagement.unknown_message`;
    * the event says nothing terminal and is not an engagement either (a
      deferral, a queue acknowledgement) — `comms.status.ignored`, **carrying
      the word it read**, and the run keeps waiting. This is the door working;
    * the body carries no vocabulary this deployment can read —
      `comms.status.untranslatable_body`, with the remedy. This is a
      **deployment** fault: raw ESP JSON arrived at a stack with no ESP
      configured to translate it;
    * the event is terminal and names no message — `comms.status.no_message_id`,
      with the remedy. This is a **provider** fault: real news about a message
      it would not identify;
    * no message in *this connection's tenant* carries that provider id —
      `NotFound` from the selector, logged. This is the cross-tenant wall: a
      webhook naming somebody else's message id finds nothing, because the read
      is scoped to the tenant the connection belongs to and not to whatever the
      payload claims;
    * it is a real status for one of our messages — the service records it.

    **The hat is the tenant's root**, and that is a decision rather than a
    convenience. A provider status is a fact about the tenant, not about the
    branch that pressed send: the ESP has no idea a branch exists, and the
    message it is reporting on may belong to any of them. `visible_to(root)` is
    the whole tenant and nothing beyond it, which is exactly the reach this
    door needs and exactly the reach house rule 24 asks it to state.

    `actor` is the receiver's own system actor, kept in the signature because it
    is what the registry hands every handler and because a handler for another
    app may well authorize with it. This one re-hats: see above.
    """
    from apps.comms import services  # deferred: services imports this module

    payload: dict[str, Any]
    if _content_type(received) == FORM_MEDIA_TYPE:
        # A form post — Twilio's shape, and every vendor that speaks it. The
        # pairs are the payload, and no pairs at all is a body this door could
        # not read, which is the same finding an unparseable JSON body is.
        payload = dict(parse_qsl(received.body, keep_blank_values=True))
        if not payload:
            log.info(
                "comms.status.unreadable_body",
                inbound_webhook_id=str(received.pk),
                connection_id=str(received.connection_id),
            )
            return
    else:
        try:
            parsed = json.loads(received.body)
        except ValueError:
            log.info(
                "comms.status.unreadable_body",
                inbound_webhook_id=str(received.pk),
                connection_id=str(received.connection_id),
            )
            return
        if not isinstance(parsed, dict):
            log.info("comms.status.not_an_object", inbound_webhook_id=str(received.pk))
            return
        payload = parsed

    channel = STATUS_PROVIDERS.get(received.connection.provider)
    if channel is None or channel not in registered_channels():
        # Registered for a slug this deployment has no transport for. Nothing to
        # read the payload with, and guessing is how a Teams status ends up
        # filed against an email.
        log.info(
            "comms.status.no_adapter",
            inbound_webhook_id=str(received.pk),
            provider=received.connection.provider,
        )
        return

    provider = get_channel(channel)
    status = provider.normalize_status(payload=payload)
    if status is None:
        # **The engagement fork** (ADR comms-9). An open and a click used to be
        # exactly the `non_terminal` drop below: read, understood,
        # and thrown away with a log line. They are still not a status — nothing
        # about the message row moves — but they ARE a fact, and this is where
        # the door stops discarding it. Asked only after `normalize_status` has
        # answered `None`, so the bounce path is untouched; and the two maps in
        # this module are disjoint, so the order is readability rather than
        # precedence.
        engagement = engagement_of(provider, payload=payload)
        if engagement is not None:
            _record_engagement(received=received, engagement=engagement)
            return
        # **Three drops, three names** (ADR comms-13). What used to stand here
        # was one `comms.status.ignored` over an `event_type` read straight off
        # the raw payload — so a body the adapter could not translate at all was
        # filed under a word meaning "read and judged non-terminal", with the
        # event_type field empty because there was nothing to put in it. A log
        # name claiming a judgement that was never made is worse than no log
        # line: a field test once blamed the worker for it.
        drop = status_drop(provider, payload=payload)
        if drop.reason == DROP_NON_TERMINAL:
            log.info(
                "comms.status.ignored",
                inbound_webhook_id=str(received.pk),
                connection_id=str(received.connection_id),
                event_type=drop.event_type,
            )
        elif drop.reason == DROP_NO_MESSAGE_ID:
            log.info(
                "comms.status.no_message_id",
                inbound_webhook_id=str(received.pk),
                connection_id=str(received.connection_id),
                event_type=drop.event_type,
                remedy=NO_MESSAGE_ID_REMEDY,
            )
        else:
            log.info(
                "comms.status.untranslatable_body",
                inbound_webhook_id=str(received.pk),
                connection_id=str(received.connection_id),
                provider=received.connection.provider,
                esp=_anymail_esp(),
                remedy=UNTRANSLATABLE_REMEDY,
            )
        return

    tenant = received.tenant
    acting = system_actor(tenant, root_organization(tenant=tenant))
    try:
        services.record_delivery_status(
            tenant=tenant,
            actor=acting,
            provider_message_id=status.provider_message_id,
            status=status.status,
            detail=status.detail,
            bounce_kind=status.bounce_kind,
            # Which kind of news the adapter read (ADR comms-9, amended). A
            # complaint suppresses and transitions nothing; the door passes the
            # adapter's judgement through and takes none of its own.
            is_complaint=status.is_complaint,
            # The door this report came through, and therefore the thing the
            # mass-suppression tripwire counts against (ADR comms-9). It is the
            # receiver's own row and never anything the payload said: a
            # connection named in a body would be an attacker choosing which
            # counter their own traffic lands on.
            connection=received.connection,
        )
    except NotFound:
        # **Two sources now, and the second one is not harmless** (SEC-R1b, L4).
        #
        # 1. the message did not resolve — not one of this tenant's, or one this
        #    deployment never sent. Nothing to say back to the provider; it is
        #    telling the truth about somebody else's mail.
        # 2. since R2, a bounce also runs `suppress_recipient` *inside*
        #    `record_delivery_status`'s transaction, and that call ends in
        #    `may_be_named`, which refuses `NotFound` too.
        #
        # The consequence differs, and this handler cannot tell them apart. The
        # service is atomic: a `NotFound` from the suppression half rolls the
        # status stamp and its event back with it, so the provider's report
        # would be swallowed here having recorded nothing — logged as an unknown
        # message when the message was known and the *suppression* was refused.
        #
        # Behaviour is deliberately unchanged: SEC-1 judged the second source
        # unreachable today, because the actor is the system actor a verified
        # webhook acts as, resolved at the tenant root, and `may_be_named` is
        # downward-true for every org-scoped row beneath it. A hierarchy change
        # that narrowed that hat, or a second caller of this service, would make
        # it reachable — at which point this comment is the finding and the fix
        # is to separate the two, not to widen the catch.
        log.info(
            "comms.status.unknown_message",
            inbound_webhook_id=str(received.pk),
            tenant_id=str(tenant.pk),
            status=status.status,
        )


# --- Push: the channel whose address is a TABLE ----------------------------------
#
# Push is the one kind of reach whose address is not a column on `Recipient`, and
# the two transports below are shaped around that single fact. A person has a
# phone, a tablet and a laptop browser; each install mints its own registration
# token; the platform rotates one without asking. So the address is
# `comms.Device` — see that model's docstring — and both transports resolve it
# through `selectors.list_devices` rather than off `message.recipient`.
#
# **What is OWNER-CLOCKED here, stated rather than implied.** A live FCM
# drive needs a Firebase project, and none was available. What is proven is
# everything up to the vendor's edge: the address resolution, the fan-out to
# several devices, the fail-closed refusal when a contact has none, the
# idempotency key per device, the credential coming off the tenant's encrypted
# `Connection` row and never out of settings, and the response handling — all of
# it driven through `httpx.MockTransport`, which is the same seam
# `apps/connections`' own client documents and the same one `ConnectionChannel`
# is tested through. What is NOT proven is that a real gateway accepts the body
# this builds. That boundary is real and it is the criterion the clock is on.


#: What `Message.provider` records for anything the fake carried. `fake-sms`'s
#: discipline: every row this transport touches names it, so no message log ever
#: claims a real gateway delivered something nothing delivered.
FAKE_PUSH_PROVIDER = "fake-push"

#: The `Connection.provider` slug the real transport's credentials live on. FCM
#: is the gateway this template's worked adapter speaks to, and — exactly as
#: with Twilio — the credentials are per TENANT (a `Connection` row) rather than
#: per deployment, because two tenants of one product push from two different
#: projects.
FCM_PROVIDER = "fcm"


@dataclass(frozen=True)
class Pushed:
    """One notification this deployment pretended to deliver. `mail.outbox`, for push."""

    device_id: str
    title: str
    body: str
    provider_message_id: str


#: Everything `FakePushChannel` has "sent", in order. A module-level list for
#: `fake_sms_outbox`'s reason, which is `django.core.mail.outbox`'s: a test
#: asserts against what went out, and a transport that swallowed its messages
#: could not be tested at all.
fake_push_outbox: list[Pushed] = []


def _devices_for(message: Message) -> list[Any]:
    """The live installs this message may be pushed to. **Fails closed on none.**

    The scoped read, both halves (house rule 24), with the MESSAGE's branch as
    the hat: a device's organization is derived from its contact, so a hat that
    could send to the contact can reach the contact's devices, and a sibling
    branch's cannot.

    A contact with no live device raises rather than returning an empty list,
    and that is `ConnectionChannel`'s fail-closed rule in this channel's
    vocabulary: a push with nowhere to land is not a notification that went
    somewhere unhelpful, it is one that went nowhere, and the message row must
    say so instead of saying `sent`.

    The import is function-local and it is the one in this module that has to
    be: `selectors` is read by a transport at send time, and a module-level
    import would run at the moment `apps.py`'s `ready()` imports this file —
    before the app registry is populated.
    """
    from apps.comms.selectors import list_devices

    devices = list(
        list_devices(
            tenant=message.tenant,
            org=message.organization,
            recipient=message.recipient,
        )
    )
    if not devices:
        raise Invalid({"devices": ["This contact has no registered device to push to."]})
    return devices


class FakePushChannel:
    """The worked push transport: a complete send with no gateway and no project.

    `FakeSmsChannel`'s sibling, deliberately down to the shape, because it is
    making the same promise: the path is exercised by the test suite and by a
    developer's own machine from an empty database, with **no vendor, no
    project and no network**. Registered at import, obviously fake by name, and
    replaced by a product's real transport under the same slug from that
    product's `AppConfig.ready()`.

    Three things keep it from ever being mistaken for a gateway:

    * every row it carries records `provider="fake-push"`, so the message log
      names it;
    * every send logs at **warning**, so a deployment running it is loud in the
      log sink rather than quietly notifying nobody;
    * `DevicePushChannel` below is the real shape, sitting immediately next to
      it, so "what do I replace this with" has an answer in the same file.

    **It resolves the same address the real one does**, which is the half that
    matters: it reads `comms.Device` through the scoped selector, fans out to
    every live install, and refuses a contact with none. A fake that pushed to
    an imaginary address would prove the consent wall and not the channel.
    """

    slug = Channel.PUSH.value

    def send(self, *, message: Message, subject: str, body: str, nonce: str = "") -> Sent:
        devices = _devices_for(message)
        handle = f"{FAKE_PUSH_PROVIDER}:{message.pk}"
        for device in devices:
            fake_push_outbox.append(
                Pushed(
                    device_id=str(device.pk),
                    title=subject,
                    body=body,
                    provider_message_id=f"{handle}:{device.pk}",
                )
            )
        log.warning(
            "comms.fake_push.sent",
            provider=FAKE_PUSH_PROVIDER,
            message_id=str(message.pk),
            recipient_id=str(message.recipient_id),
            device_count=len(devices),
        )
        return Sent(provider=FAKE_PUSH_PROVIDER, provider_message_id=handle)

    def fakeness(self) -> Fakeness:
        """Says so out loud, for `FakeSmsChannel.fakeness`'s reason.

        Push has no inbound webhook, so there is no silently-dropped STOP here —
        the silence this closes is simpler and just as expensive: a deployment
        whose notifications have never left the building, and nothing anywhere
        saying so.
        """
        return Fakeness(
            detail=(
                "FakePushChannel holds the 'push' slot: every notification is appended "
                "to providers.fake_push_outbox and logged at warning, and no device is "
                "ever reached."
            ),
            remedy=(
                "register_channel(DevicePushChannel()) from your own AppConfig.ready() "
                "and give each tenant an 'fcm' connection holding the gateway credential "
                "(docs/runbooks/deploy.md, 'Turning on a real push transport')."
            ),
        )

    def normalize_status(self, *, payload: dict[str, Any]) -> ProviderStatus | None:
        """The same three words, out of the same normalised shape.

        `FakeSmsChannel`'s reasoning verbatim: a fake's vocabulary is ours to
        choose, and choosing the one the product already reads means this
        transport proves the *status contract* end to end instead of proving a
        second contract nobody ships.
        """
        return EmailChannel().normalize_status(payload=payload)

    def explain_status_drop(self, *, payload: dict[str, Any]) -> StatusDrop | None:
        """And the same account of a drop, for the same reason."""
        return EmailChannel().explain_status_drop(payload=payload)


@dataclass(frozen=True)
class DevicePushChannel:
    """The real shape: a push carried by one of the tenant's own `Connection` rows.

    **This is what an FCM (or APNs, or web-push) gateway looks like in this
    product**, and it ships as a worked adapter rather than as a vendor —
    `ConnectionChannel`'s bargain one channel over, with the one difference that
    makes push push::

        register_channel(DevicePushChannel())                        # FCM
        register_channel(DevicePushChannel(provider="apns", path="/3/device"))

    **One request per device, not one per message**, which is the difference the
    address-is-a-table fact forces. Every gateway worth integrating with
    addresses a single install per call, so this fans out, keys each request on
    `<message>:<device>` — stable across every retry of one logical send, so a
    restarted worker does not notify somebody twice — and reports the first
    handle a gateway gave back.

    **No vendor SDK, and that is a decision recorded rather than an
    omission.** `firebase-admin` was the decomposition's expected dependency and
    it buys nothing here: its value is the credential lifecycle and the
    inbound-signature machinery, and push has no inbound webhook to verify
    (house rule 43's census is untouched by this adapter), while the credential
    in this product lives per tenant on an encrypted `Connection` row rather
    than in the process-global app the SDK wants to own. Adding a large
    transitive tree to a *template* for a code path that is left undriveable is
    the trade the other way. House rule 44's watch is answered by construction:
    this adapter holds no library internals, because it holds no library.

    The three properties `ConnectionChannel`'s docstring names hold here too and
    for the same reasons — the credential is never in this module, the call
    happens from an activity, the POST is idempotent by key — and are not
    repeated.
    """

    slug: str = Channel.PUSH.value
    provider: str = FCM_PROVIDER
    path: str = "/messages:send"
    transport: httpx.BaseTransport | None = None

    def fakeness(self) -> Fakeness | None:
        """Real: it reaches a gateway over the network. See `EmailChannel`."""
        return None

    def send(self, *, message: Message, subject: str, body: str, nonce: str = "") -> Sent:
        connection = (
            # The system actor: a provider looking up its own credential is the
            # platform reading for itself, and `list_connections` asks
            # `connection.read` since Phase R (ADR core-27). There is no person
            # here — a send runs inside an activity — and `allows` passes a
            # `system` actor at step 1 while the scoped manager still fences the
            # read to this tenant.
            list_connections(tenant=message.tenant, actor=system_actor(message.tenant))
            .filter(provider=self.provider, status=Connection.Status.CONNECTED)
            .first()
        )
        if connection is None:
            raise NotFound(
                f"This tenant has no connected {self.provider!r} connection to send "
                f"{self.slug!r} through."
            )
        devices = _devices_for(message)
        handles: list[str] = []
        with http_client(connection, transport=self.transport) as client:
            for device in devices:
                response = post_idempotent(
                    client,
                    self.path,
                    key=f"{message.pk}:{device.pk}",
                    json={
                        "message": {
                            "token": device.push_token,
                            "notification": {"title": subject, "body": body},
                        }
                    },
                )
                response.raise_for_status()
                handles.append(_vendor_handle(response, message))
        return Sent(provider=self.provider, provider_message_id=handles[0])

    def normalize_status(self, *, payload: dict[str, Any]) -> ProviderStatus | None:
        """Nothing, until a product's gateway adapter says otherwise.

        `ConnectionChannel.normalize_status`' answer, and the same argument: a
        gateway's delivery-receipt vocabulary is the gateway's, and inventing
        one here would be inventing a mapping nobody can check. A product that
        wants push receipts subclasses or replaces this method and adds its
        connection slug to `STATUS_PROVIDERS`.
        """
        return None


# The built-in push transport is the FAKE, exactly as it is for SMS: a fresh
# clone sends a notification end to end with no project and no account, and a
# deployment that has a gateway replaces it under the same slug from its own
# `AppConfig.ready()` — `register_channel(DevicePushChannel())`. That
# replacement is documented where an operator looks, in
# `docs/runbooks/deploy.md`, and not only in this comment: this file's SMS twin
# was once the only place it was written down, which is
# the whole reason the runbook now carries both.
register_channel(FakePushChannel())
