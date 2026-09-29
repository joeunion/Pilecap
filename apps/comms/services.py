"""The one door out of this product to a person, and what stands behind it.

`send()` is the whole app. A product feature does not call `django.core.mail`,
an SMS SDK or a Slack webhook — it calls this, and consent, quiet hours and
suppression are enforced **inside** it, so no campaign, no feature and no
well-meaning helper can go around them. House rule 25 (C1-1b) is the mechanical
half of that sentence; this module is the half that has to be true first.

### What `send()` refuses, and how it says so

**A refusal writes a row.** A marketing message to somebody who never consented
is not an error — the product behaved correctly — but "we did not email them,
and here is why" is a question support and audit both ask, and an exception
answers it by leaving nothing behind. So a refused send writes
`Message(status=suppressed, suppressed_reason=…)`, emits
`comms.message.suppressed`, and starts no delivery workflow. The caller gets a
`Message` back either way and can read `status` if it cares.

Bad *input*, by contrast, still raises: a template the tenant does not have is
`NotFound`, a context missing a required variable is `Invalid` with the field
named, and neither writes a row. The line is "we could not do what you asked"
(raise) versus "we did what you asked, and the answer was no" (a row).

### Where the transports are

The channel registry — the `ChannelProvider` protocol, `register_channel()`,
`get_channel()` and the built-in `EmailChannel` — lives in `providers.py`,
beside `apps/connections/providers.py` and recorded as this app's one extra
module in `quality/rules.yaml` (house rule 11). C1-1a had it here and said why:
it did not own `rules.yaml` and could not make the record. This rung owns both
files, so the cut and paste it named has been done. **No service in this module
performs the send**: `activities.py` asks `providers.get_channel()` for the
transport and calls it, out at the edge where I/O belongs.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.template import Context as TemplateContext
from django.template import Template as DjangoTemplate
from django.utils import timezone

from apps.accounts.models import User
from apps.comms.events import (
    DEVICE_REGISTERED,
    DEVICE_RETIRED,
    MESSAGE_BOUNCED,
    MESSAGE_CANCELLED,
    MESSAGE_CLICKED,
    MESSAGE_COMPLAINED,
    MESSAGE_DELIVERED,
    MESSAGE_FAILED,
    MESSAGE_OPENED,
    MESSAGE_QUEUED,
    MESSAGE_SENT,
    MESSAGE_SUPPRESSED,
    RECIPIENT_ARCHIVED,
    RECIPIENT_RESTORED,
    SUPPRESSION_RECOVERED,
    SUPPRESSION_SURGED,
    V,
)
from apps.comms.models import (
    BounceKind,
    Category,
    Channel,
    ChannelPreference,
    DeliveryPolicy,
    Device,
    Message,
    MessageEngagement,
    MessageTemplate,
    Recipient,
    SuppressionSurge,
)
from apps.comms.policies import quiet_defer_seconds, tenant_quiet_window
from apps.comms.providers import STATUS_VALUES, registered_channels
from apps.comms.schemas import DeviceOut, MessageEngagementOut, MessageOut, RecipientOut
from apps.comms.selectors import (
    get_device_by_token_hash,
    get_message_by_provider_id,
    get_policy,
    get_preference,
    get_template,
    list_policies,
    list_templates,
)
from apps.comms.types import DeliverMessage, DeliveryStatus, PolicyStep
from apps.connections.models import Connection
from apps.core.actor import Actor
from apps.core.asyncdb import run_async
from apps.core.authz import may_be_named, require
from apps.core.context import value as bound_value
from apps.core.exceptions import Conflict, Invalid, NotFound, as_invalid
from apps.core.log import get_logger
from apps.core.models import Organization, Tenant
from apps.core.service import service
from apps.core.services import root_organization
from apps.core.verbs import archive_row, require_live, restore_row
from apps.events.services import emit
from apps.workflows.services import signal_workflow, start_workflow_on_commit, workflow_id

log = get_logger("apps.comms.services")

# What may appear un-redacted in this app's log lines and audit `input`. An
# allow-list, not a blocklist, and the two absences are the point: **`context`
# is not on it** — it is the customer's own data, names and amounts and order
# numbers, and it must not be copied into the log sink or the audit row — and
# neither is `subject`, which is rendered from that same context.
LOG_KEYS: frozenset[str] = frozenset(
    {
        "template",
        "channel",
        "status",
        "reason",
        "provider",
        "policy",
        "step",
        # ADR comms-9. All three are operational facts about a transport and a
        # report, never about a person: which kind of bounce a provider said it
        # was, which of the tenant's connections said it, and how many addresses
        # the trailing hour had silenced when the tripwire looked. An audit row
        # for a surge that could not name its connection would be an alarm with
        # nowhere to go.
        "bounce_kind",
        "connection",
        "count",
    }
)

# The workflow that delivers, by the name in its `@workflow.defn`, and the
# signal it is waiting on. The signal name is a contract between this module and
# `workflows.py` and it is written down once, here, because a typo in a string
# passed to a running workflow is a message that waits seventy-two hours.
DELIVER_WORKFLOW = "DeliverMessageWorkflow"
DELIVERY_SIGNAL = "delivery_status"

# What a step may say to do when it does not land. **A closed set of two**, and
# it is short on purpose: `delivered` means "go on unless the transport says
# this one arrived", `none` means "this is the end of the chain". `opened` and
# `clicked` are the obvious third and fourth and they are a **named deferral** —
# they ship with the tracking rung that can actually observe them, because an
# escalation that waits for a signal nothing emits is an escalation that never
# escalates.
ESCALATE_DELIVERED = "delivered"
ESCALATE_NONE = "none"
ESCALATE_WHEN: frozenset[str] = frozenset({ESCALATE_DELIVERED, ESCALATE_NONE})

# The statuses a provider report may still change something about. A message
# that has already been reported on, refused for consent, or run out of
# attempts is not waiting for news, and a transition off one of those is a
# `Conflict` rather than a quiet overwrite — a delivered message that became
# bounced would be a log that contradicts itself.
OPEN_TO_STATUS: frozenset[str] = frozenset(
    {
        Message.Status.QUEUED.value,
        Message.Status.SENDING.value,
        Message.Status.SENT.value,
    }
)

# The statuses the delivery workflow's own bookkeeping must not walk back over.
# `sent` is the one it writes; `delivered` and `bounced` outrank it, because
# they are later news from the same transport and a replayed activity arriving
# after a status webhook must not turn "it arrived" back into "we posted it".
#
# **`suppressed` is here for a different reason and it is the load-bearing one**
# (ADR comms-8). The wall now runs again at the transport edge, in
# `mark_message_sending`, so a message can be refused *after* the interpreter
# decided to deliver it — and the interpreter cannot know: workflow code may not
# read a row (house rule 9) and `DeliveryAttempt` carries no status. So
# `finish_message` arrives afterwards saying "record this as sent", and the only
# place that can refuse is here. Without it the row would say `sent` a heartbeat
# after the wall refused it, and `comms.message.sent` would announce a message
# nobody was sent.
REPORTED: frozenset[str] = frozenset(
    {
        Message.Status.SENT.value,
        Message.Status.DELIVERED.value,
        Message.Status.BOUNCED.value,
        Message.Status.SUPPRESSED.value,
    }
)

# The statuses a message may still be **handed to a transport** in, and
# therefore exactly the statuses the wall at the edge has to judge again.
#
# `queued` is a first attempt. `sending` is a *later* one: Temporal guarantees
# an activity runs at least once, so a transport that failed after this row was
# marked leaves it mid-flight, and the retry re-sends it. Everything else —
# sent, delivered, bounced, failed, suppressed — is a row whose story is over or
# was never allowed to start. (The duplicate a retry can produce used to be
# recognisable to the provider by a stable `Message-ID`; ADR comms-9 stopped
# printing that header, because it was also a suppression key — `activities.py`'s
# module docstring carries the trade.)
#
# **It lives here and `activities.py` reads it from here** (SEC-R1b). It used to
# be defined in the activity alone while `mark_message_sending` kept its own
# one-status copy of the same idea, and the two drifted the moment `sending`
# joined the activity's set: the recheck ran on attempt 1 and was skipped on
# every attempt after it, for the whole length of a retry backoff (SEC-1's H1).
# One definition, read by the guard and by the service, is what makes that
# particular drift unrepresentable rather than merely fixed.
SENDABLE: frozenset[str] = frozenset(
    {
        Message.Status.QUEUED.value,
        Message.Status.SENDING.value,
    }
)

# The statuses a caller may still take a message back out of. **Only
# `queued`**, and the narrowness is the whole safety of the verb: `sending`
# means an activity is inside a transport right now, and a row this service
# marked cancelled while a gateway was accepting it would be a message the
# person receives and the log says was cancelled. Everything past that is
# already somebody's news.
#
# A set rather than `== QUEUED` for `SENDABLE`'s reason: the question is "is
# this still ours to withdraw", and a second withdrawable status would join here
# without moving the guard.
CANCELLABLE: frozenset[str] = frozenset({Message.Status.QUEUED.value})

# --- the lever taxonomy (ADR comms-10) ------------------------------------------
#
# The edge wall refuses for several reasons and they are not the same *kind* of
# reason. A suppression or a withdrawn consent is a **permanent** lever: it is a
# fact about the person and about this channel, and nothing but the person
# changing their mind will change it, so the message dies and the run closes.
# Quiet hours is a **temporal** lever: it is a fact about the *clock*, it stops
# being true at a knowable minute, and killing the message for it throws away a
# send the recipient never objected to — a campaign queued at 21:59 and
# judged at 22:01 once lost half an evening's traffic to a wall that only meant
# "later".
#
# One membership today, and the set rather than an `== QUIET_HOURS` because the
# question the fork asks is "which kind of lever is this", not "is this quiet
# hours" — a second temporal lever (a rate limit, a send window) joins here and
# the fork does not move.
LEVER_PERMANENT = "permanent"
LEVER_TEMPORAL = "temporal"

TEMPORAL_REASONS: frozenset[str] = frozenset({Message.SuppressedReason.QUIET_HOURS.value})

# The recorded statuses that are a fact about the **address** rather than about
# the ESP's machinery, and therefore the ones that can suppress it (ADR
# comms-8). One member, and the collapsing is what makes it one:
# `providers.EMAIL_STATUS` already maps `bounced`, `complained` and `rejected`
# onto this single value, because all three mean *stop mailing this address* —
# which is what lets one suppression rule read one column instead of three.
#
# **`failed` is deliberately absent.** A spent retry is infrastructure weather,
# not a fact about the person, and suppressing on it would silence a healthy
# recipient on the strength of a bad afternoon.
#
# **The status is now necessary and not sufficient** (ADR comms-9): the kind
# below decides. The status set stays the outer gate because it is what says
# "this report is about an address at all"; a `delivered` carrying a stray
# `bounce_kind` must not reach the fork.
SUPPRESSING: frozenset[str] = frozenset({Message.Status.BOUNCED.value})

# Which kinds of bounce are a fact about the address (ADR comms-9).
# `SOFT` is recorded on the row and acts on nothing: a full mailbox, a
# greylisting server and an ESP that retried for a day are all reasons to try
# later, and suppressing on them silenced healthy recipients tenant-wide — and,
# because the status arrives over a webhook, made the wall a weapon.
#
# **An unclassified bounce is hard, and that is decided one layer out**, in the
# adapter (`providers._bounce_kind`), where "what did this ESP mean" is
# knowledge. This set is only the question "does this kind suppress", so that a
# provider inventing a third kind is a kind that suppresses nobody rather than a
# `KeyError` on a webhook.
SUPPRESSING_KINDS: frozenset[str] = frozenset({BounceKind.HARD.value})

# What a bounce nobody classified is recorded and treated as. **Hard**, and the
# asymmetry is the reason: a wrongly-suppressed address is lifted by one call to
# `unsuppress_recipient`, and a wrongly-mailed dead address is a sender
# reputation nobody gets back. ADR comms-8 chose that direction for the whole
# collapsed set; comms-9 narrows it to the part no provider spoke about.
#
# **One definition, here and not in the adapter.** `record_delivery_status` is
# reachable without any adapter at all, and a second copy of "what do we do when
# nobody said" living in `providers.py` is precisely the two-hand-kept-sets drift
# SEC-R1b had to come back and fix.
UNCLASSIFIED_BOUNCE: str = BounceKind.HARD.value

# --- the mass-suppression tripwire (ADR comms-9 (c)) -----------------------------
#
# **A ratified constant, in the code and not in the environment**, so that what
# the platform promises is the same number in every deployment and a change to
# it is a diff a reviewer sees rather than a variable an operator sets during an
# incident. Twenty-five addresses silenced on one connection inside an hour is
# far above any real ESP's ordinary bounce rate for a tenant and far below the
# volume a denial-of-comms run needs to matter.
#
# The honest limit, stated where the number is: a slow drip under the threshold
# stays invisible. The tripwire narrows the risk; it does not close malice, and the
# casual-guardrail posture says so out loud rather than implying a wall.
SURGE_THRESHOLD = 25

# How far back the trailing count reaches. A window and not a bucket: an
# attacker who learned the bucket boundary would send twenty-four on each side
# of it.
SURGE_WINDOW = timedelta(hours=1)

# Which event each recorded status publishes. A dict rather than a branch, so
# the closed set in `providers.STATUS_VALUES` and the names in `events.py` are
# lined up in one place a reader can check against both.
STATUS_EVENTS: dict[str, str] = {
    Message.Status.DELIVERED.value: MESSAGE_DELIVERED,
    Message.Status.BOUNCED.value: MESSAGE_BOUNCED,
    Message.Status.FAILED.value: MESSAGE_FAILED,
}

# Which column each recorded status stamps. Same reasoning as `STATUS_EVENTS`.
STATUS_STAMPS: dict[str, str] = {
    Message.Status.DELIVERED.value: "delivered_at",
    Message.Status.BOUNCED.value: "bounced_at",
    Message.Status.FAILED.value: "failed_at",
}

# How much of a provider's refusal is worth keeping on the row. Enough to see
# what it said; not so much that one HTML error page becomes the table.
ERROR_LIMIT = 2000

# JSON-Schema `type` names, mapped to what Python calls them. `bool` is checked
# before `int` everywhere it matters, because `True` is an `int` in Python and
# a template variable typed `integer` that accepts `True` is a template that
# renders "True" into an invoice.
_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


# --- consent, quiet hours, suppression -----------------------------------------


def _refusal(
    *,
    preference: ChannelPreference | None,
    category: str,
    at: datetime,
    tenant: Tenant | None = None,
) -> str:
    """Why this send must not go out, or an empty string. **The consent wall.**

    The order is the precedence, and each step is a different promise:

    1. **no preference row at all** — nobody has said anything. Transactional
       goes (they asked for it by doing something); marketing does not, because
       consent that was never given is not consent;
    2. **suppressed** — a hard bounce, a spam complaint, or the person asking to
       be left alone. It refuses *everything* on this channel, transactional
       included, and it is checked first because it outranks every other answer;
    3. **marketing without live consent** — never given, or given and revoked;
    4. **quiet hours** — non-transactional traffic waits. A receipt at 3am is
       fine because the person just bought something; a campaign is not. Two
       windows can say so and either is enough: the person's own
       (`ChannelPreference`, set through `set_quiet_hours`) and the **tenant's**,
       which arrives through the empty seam above and is `None` on every fresh
       clone. The person's is checked first because it is the more specific
       answer and because it is the one that exists without a product having
       done anything.

    **The tenant seam is consulted here and nowhere else**, which is the whole
    of RUL-2's binding-point clause: `send()` calls this at queue time and
    `mark_message_sending` calls it again at the transport edge, so a window a
    product configures applies to both without either of them knowing the seam
    exists.
    """
    if preference is None:
        return "" if category == Category.TRANSACTIONAL else Message.SuppressedReason.NO_CONSENT
    if preference.suppressed_at is not None:
        return Message.SuppressedReason.SUPPRESSED
    if category != Category.TRANSACTIONAL:
        if not preference.has_marketing_consent:
            return Message.SuppressedReason.NO_CONSENT
        if preference.is_quiet_at(at):
            return Message.SuppressedReason.QUIET_HOURS
        window = tenant_quiet_window(tenant)
        if window is not None and window.is_quiet_at(at):
            return Message.SuppressedReason.QUIET_HOURS
    return ""


#: The per-message delivery nonce's separator inside a workflow id's `key`
#: segment. A full stop and **not** a colon, because `workflows.workflow_id`
#: refuses a key containing `ID_SEPARATOR` — the four-segment grammar is what a
#: human reads in the Temporal UI and a fifth segment smuggled into `key` would
#: break the prefix search that grammar exists for.
NONCE_SEPARATOR = "."


def issue_delivery_nonce(message_id: Any) -> str:
    """The opaque per-message id a transport is told, and a suppression key is not.

    **This is ADR comms-9's deferred nonce, and this is its named trigger firing.**
    comms-9 took the minted `Message-ID` out of the mail for a reason that has
    not weakened: `provider_message_id` is the key `record_delivery_status`
    accepts a bounce against, so printing it into every message handed the
    recipient — and anybody they forwarded to — a valid suppression key for
    themselves (vector (b)). The cost comms-9 wrote down was equally real:
    with no stable identifier on the wire, a crash between handing a message to
    a transport and recording that we did produces two messages a provider
    cannot tell apart, and comms-10's deferral widened that window to a day.

    The way out is a **second** identifier that is not the first. This one:

    * it is **derived**, not random, so a retry computes the same value and rule
      18's "never a random value" holds for the id it rides in;
    * it is **not** `provider_message_id`, is accepted by nothing, and joins
      nothing — `record_delivery_status` resolves a message by the provider's
      handle and has never heard of this. A recipient who forwards it forwards
      an opaque string. `tests/test_nonce.py` drives that, because a claim that
      a value is harmless is worth exactly as much as the test that tries to use
      it;
    * it is **one-way**: a SHA-256 digest of the row's primary key, truncated.
      Recovering the pk from it would make it the pk with extra steps.

    Truncated to 32 hex characters — 128 bits, which is what a `Message-ID`
    wants to be and far past any collision a tenant's message table will reach.
    """
    return hashlib.sha256(str(message_id).encode("utf-8")).hexdigest()[:32]


# --- rendering and context validation ------------------------------------------


def render(*, template: str, context: dict[str, Any]) -> str:
    """One template string and one context, rendered.

    Autoescaping is **off**: these render into an email body and a subject line,
    not into a browser, and an escaped apostrophe in somebody's name is the
    thing every product notices first. A template set that grows an HTML part
    turns it back on for that part, deliberately, in the same place.
    """
    return DjangoTemplate(template).render(TemplateContext(context, autoescape=False))


def _matches_type(value: Any, expected: str) -> bool:
    """Whether a context value is the JSON type the template's schema declared."""
    if expected == "null":
        return value is None
    allowed = _JSON_TYPES.get(expected)
    if allowed is None:
        return True
    if expected in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, allowed)


def _context_errors(*, schema: dict[str, Any], context: dict[str, Any]) -> dict[str, list[str]]:
    """Field-by-field complaints about a template context, in `Invalid`'s shape.

    A deliberately small subset of JSON Schema — `required` and `properties`
    with a `type` — because that is what a template context actually is: a flat
    bag of variables, some of which must be there. A caller that needs more
    validation than that has business logic, and business logic belongs in the
    service that is calling `send()`.

    Returning the errors rather than raising lets `send()` decide, which keeps
    the "raise for bad input, write a row for a refusal" line in one place.
    """
    errors: dict[str, list[str]] = {}
    for field in schema.get("required") or []:
        name = str(field)
        value = context.get(name)
        if name not in context or value is None or value == "":
            errors.setdefault(name, []).append("This template variable is required.")
    properties = schema.get("properties") or {}
    if isinstance(properties, dict):
        for field, spec in properties.items():
            name = str(field)
            if name not in context or name in errors or not isinstance(spec, dict):
                continue
            expected = spec.get("type")
            if isinstance(expected, str) and not _matches_type(context[name], expected):
                errors.setdefault(name, []).append(f"Expected a value of type {expected!r}.")
    return errors


def _payload(message: Message) -> dict[str, Any]:
    """The event payload: the same shape a REST client gets for the same row."""
    return dict(MessageOut.from_orm(message).model_dump(mode="json"))


def _message_row(
    *,
    tenant: Tenant,
    organization: Organization,
    recipient: Recipient,
    template: MessageTemplate,
    channel: str,
    context: dict[str, Any],
    reason: str,
    at: datetime,
    policy_name: str = "",
    policy_version: int | None = None,
    policy_step: int | None = None,
    send_at: datetime | None = None,
    delivery_workflow_id: str = "",
    correlation_id: str = "",
    causation_id: str = "",
) -> Message:
    """The unsaved row a send writes, whichever service is doing the sending.

    Extracted because there are now **two** of them — `send` writes step 1 inside
    a request and `send_step` writes every later rung inside an activity — and
    eighteen fields copied into two places is eighteen chances for the next
    column to land in one of them. What differs between the two callers is where
    the values come from, not which values there are, so the difference is the
    argument list and the row is one definition.

    `reason` empty means the consent wall said yes: the status, the reason column
    and the suppression timestamp are all derived from it here, which is what
    stops a caller writing `status=suppressed` with no reason (the database
    refuses that anyway — `comms_message_suppressed_carries_a_reason` — and this
    is the same invariant one layer earlier, where the error is readable).
    """
    return Message(
        tenant=tenant,
        organization=organization,
        recipient=recipient,
        template=template,
        template_name=template.name,
        template_version=template.version,
        channel=channel,
        category=template.category,
        status=Message.Status.SUPPRESSED if reason else Message.Status.QUEUED,
        suppressed_reason=reason,
        suppressed_at=at if reason else None,
        subject=render(template=template.subject, context=context),
        context=dict(context),
        policy_name=policy_name,
        policy_version=policy_version,
        policy_step=policy_step,
        send_at=send_at,
        delivery_workflow_id=delivery_workflow_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )


# --- the send primitive ---------------------------------------------------------


@dataclass(frozen=True)
class _Plan:
    """What one `send()` is going to do: the first message, and what follows it.

    Private, and a dataclass rather than four return values, because the four
    travel together everywhere they go and a tuple of two strings and a list
    swaps its own elements the first time somebody adds a fifth.

    `steps` empty is a plain send — one message and no escalation. It is what a
    caller with a template and a channel gets, and it is what makes the
    no-policy path the same path rather than a special case beside it.

    `template` is the resolved **row**, not the name: by the time a plan exists
    the name has already been turned into a version, and handing the name on
    would mean resolving it twice and risking two different answers.
    """

    channel: str
    template: MessageTemplate
    steps: list[PolicyStep]
    policy_name: str = ""
    policy_version: int | None = None


def _policy_steps(*, tenant: Tenant, steps: list[dict[str, Any]], actor: Actor) -> list[PolicyStep]:
    """Every rung of a policy, checked against the closed sets. **The one gate.**

    Both writes (`create_policy`, `revise_policy`) and every read that is about
    to be *executed* (`_plan`) come through here, and that is deliberate: a row
    written before a rule tightened, or by a management command that skipped the
    door's schema, fails loudly at the moment it would have sent something
    rather than silently doing the wrong thing.

    Every complaint is collected before any is raised, and each is keyed by
    `steps.<index>.<field>`, so a caller who got three of them wrong is told
    three times rather than made to guess-and-retry three times.

    The template is resolved per step, which is what turns "this policy names an
    SMS template on the email step" from a runtime surprise into a `400` at the
    moment the policy is written.
    """
    if not steps:
        raise Invalid(
            {
                "steps": [
                    "A policy is at least one step; an escalation with no rungs reaches nobody."
                ]
            }
        )
    errors: dict[str, list[str]] = {}
    resolved: list[PolicyStep] = []
    for index, raw in enumerate(steps):
        where = f"steps.{index}"
        slug = str(raw.get("channel", "") or "").strip().lower()
        wanted = str(raw.get("template", "") or "").strip()
        escalate = str(raw.get("escalate_when", ESCALATE_NONE) or "").strip().lower()
        try:
            wait = int(raw.get("wait_seconds", 0) or 0)
        except (TypeError, ValueError):
            wait = -1

        if slug not in Channel.values:
            errors.setdefault(f"{where}.channel", []).append(
                f"{slug!r} is not a channel this product knows."
            )
        if escalate not in ESCALATE_WHEN:
            errors.setdefault(f"{where}.escalate_when", []).append(
                f"{escalate!r} is not one of {sorted(ESCALATE_WHEN)}."
            )
        if wait < 0:
            errors.setdefault(f"{where}.wait_seconds", []).append("A wait cannot be negative.")
        if f"{where}.channel" not in errors:
            try:
                template_row = get_template(tenant=tenant, name=wanted, actor=actor)
            except NotFound:
                errors.setdefault(f"{where}.template", []).append(
                    f"No active template named {wanted!r}."
                )
            else:
                if template_row.channel != slug:
                    errors.setdefault(f"{where}.template", []).append(
                        f"Template {template_row.name!r} is a {template_row.channel!r} "
                        f"template, not {slug!r}."
                    )
        resolved.append(
            PolicyStep(
                channel=slug,
                template=wanted,
                wait_seconds=max(wait, 0),
                escalate_when=escalate,
            )
        )
    if errors:
        raise Invalid(errors)
    return resolved


def _channel(slug: str, *, given: str) -> str:
    """One channel slug, or the refusal that names which half is wrong.

    Two different failures wearing one field name, and telling them apart is
    what makes the message useful: a channel this product has never heard of is
    a typo, and a channel with no registered transport is a deployment that has
    not been given one. Neither is "your template is wrong".
    """
    if slug not in Channel.values:
        raise Invalid({"channel": [f"{given!r} is not a channel this product knows."]})
    if slug not in registered_channels():
        raise Invalid({"channel": [f"No transport is registered for the {slug!r} channel."]})
    return slug


def _plan(*, tenant: Tenant, template: str, channel: str, policy: str, actor: Actor) -> _Plan:
    """Decide what this send is, and refuse it, before anything is written.

    Everything between "a caller asked for something" and "there is a row to
    write" lives here: which channel, which template version, whether the two
    agree, and what happens if it does not land. `send()` is then the write and
    only the write, which is the shape it had before a policy could be named.

    **A template or a policy, never both.** A policy's first step already says
    which template on which channel; a caller passing one alongside means two
    different things at once, and the refusal names the field they passed rather
    than silently resolving it one way. Refused here rather than at the schema
    so the machine door, a management command and a test all get the same answer
    (house rule 14's shape: the service decides, one mapper turns it into a 400).

    With no policy the channel falls back to email, which is where that default
    has always lived in effect — `MessageIn` used to carry it and now does not,
    so a body that omits the channel still sends email and the *service* is
    where you read why.
    """
    named = str(policy or "").strip()
    if named:
        passed = [
            field
            for field, value in (("template", template), ("channel", channel))
            if str(value or "").strip()
        ]
        if passed:
            raise Invalid(
                {
                    field: [
                        f"Policy {named!r} already says which template and channel each step "
                        f"uses; do not pass {field!r} alongside it."
                    ]
                    for field in passed
                }
            )
        row = get_policy(tenant=tenant, name=named, actor=actor)
        steps = _policy_steps(tenant=tenant, steps=list(row.steps or []), actor=actor)
        slug = _channel(steps[0].channel, given=steps[0].channel)
        return _Plan(
            channel=slug,
            template=get_template(tenant=tenant, name=steps[0].template, actor=actor),
            steps=steps,
            policy_name=row.name,
            policy_version=int(row.version),
        )

    wanted = str(template or "").strip()
    if not wanted:
        raise Invalid(
            {"template": ["Name a template to send, or a policy whose first step names one."]}
        )
    slug = _channel(str(channel or "").strip().lower() or Channel.EMAIL.value, given=channel)
    chosen = get_template(tenant=tenant, name=wanted, actor=actor)
    if chosen.channel != slug:
        raise Invalid(
            {
                "channel": [
                    f"Template {chosen.name!r} is a {chosen.channel!r} template, not {slug!r}."
                ]
            }
        )
    return _Plan(channel=slug, template=chosen, steps=[])


@service
def send(
    *,
    recipient: Recipient,
    context: dict[str, Any],
    tenant: Tenant,
    actor: Actor,
    template: str = "",
    channel: str = "",
    policy: str = "",
    send_at: datetime | None = None,
) -> Message:
    """Say one thing to one person. **The only legal sender in the product.**

    Returns the `Message` row in every case that is not bad input — queued when
    it is on its way, suppressed when consent said no. See the module docstring
    for that line.

    The acting **hat** comes from the actor and is never an argument: a caller
    that could name an organization could send from a branch it holds no
    membership over, which is the tenancy hole one level down.

    `policy=` is this door's one addition and it is deliberately the *only*
    one: with a policy this writes step 1 exactly as it would have written a
    plain send, and hands the rest of the plan to the run as a snapshot. Without
    one, nothing about this function's behaviour has moved.

    **`send_at=` schedules it, and quiet hours no longer kill at queue time.**
    Both are the same mechanism — a duration the run sleeps before it
    tries anything — and both are decided in `_wait_for`, which carries the
    argument for each. What matters here: a scheduled send is `queued`
    immediately, and the consent wall runs AGAIN when the timer wakes, so
    scheduling is not a way to bank permission.
    """
    at = timezone.now()
    # House rule 26, and this is the row it matters most for: `recipient` comes
    # straight off the wire. REACHABILITY FIRST — `require` is asked at the node
    # the ROW names, so asking it first said `forbidden` for a branch this hat
    # holds nothing over, which tells the caller the row exists.
    if not may_be_named(actor, recipient):
        raise NotFound()
    require(actor, "message.send", recipient)
    if actor.org is None:
        # Fails closed like every other unresolved scope here: a message row
        # written with no organization would be invisible to every read in the
        # product, including the root's.
        raise Invalid({"organization": ["This request resolved no acting organization."]})

    plan = _plan(tenant=tenant, template=template, channel=channel, policy=policy, actor=actor)
    slug, row = plan.channel, plan.template
    errors = _context_errors(schema=row.context_schema or {}, context=context)
    if errors:
        raise Invalid(errors)

    preference = get_preference(
        tenant=tenant, recipient=recipient, channel=slug, org=actor.org, actor=actor
    )
    reason = _refusal(preference=preference, category=row.category, at=at, tenant=tenant)
    delay, reason = _wait_for(
        reason=reason, preference=preference, tenant=tenant, at=at, send_at=send_at
    )
    # The chain the door started, read and never minted: house rule 20 says a
    # correlation id minted below a door restarts the chain it exists to join.
    # `emit()` reads the same two values, so the message row, the audit row and
    # every `comms.message.*` event for this send carry one id.
    message = _message_row(
        tenant=tenant,
        organization=actor.org,
        recipient=recipient,
        template=row,
        channel=slug,
        context=context,
        reason=reason,
        at=at,
        policy_name=plan.policy_name,
        policy_version=plan.policy_version,
        policy_step=1 if plan.steps else None,
        # The schedule, ON THE ROW. The wait is still the run's timer —
        # that is what survives a deploy — and this is what makes it answerable
        # without the Temporal UI. Written for a quiet-hours deferral too, and
        # deliberately: "why is this still queued" has the same answer in both
        # cases and a column that only spoke for one of them would be a support
        # question with a footnote.
        send_at=(at + timedelta(seconds=delay)) if delay else None,
        correlation_id=str(bound_value("correlation_id") or ""),
        causation_id=str(bound_value("causation_id") or ""),
    )
    # The run's id, on the row, before either exists: the primary key is the
    # model's own default rather than the database's, so the id the start will
    # use is knowable here. Writing it down is what lets a status webhook
    # arriving hours later find the run without rebuilding the id from a rule
    # that stopped holding the moment one run owned several messages.
    #
    # **When there is a run at all**, and the second half of that is comms-b's:
    # a plain send that consent refused starts nothing, exactly as before; a
    # *policy* whose first step was refused still starts one, because the whole
    # point of an escalation is that the next rung is tried when this one did
    # not reach anybody (ADR comms-7). A one-step policy refused at step 1 has
    # nothing left to do and starts nothing either.
    # The nonce is minted from the row, so this id is repeatable: two calls with
    # the same `Message` produce the same string (a RETRY joins the run that
    # exists) and two `send()`s produce two rows, two nonces and two runs (a
    # RE-SEND is a new run, and the person gets the second copy).
    nonce = issue_delivery_nonce(message.pk)
    # `workflow_id(...)` inline, and not behind a helper: house rule 18 reads the
    # CALL SITE and a builder one indirection away is exactly the shape it cannot
    # tell from a random id. The key carries two facts — `<pk>.<nonce>`, which
    # message and which delivery lineage of it — and `NONCE_SEPARATOR` is a full
    # stop because the id's own four-segment grammar refuses a colon in a key.
    run_id = workflow_id(
        tenant=tenant, app="comms", noun="message", key=f"{message.pk}{NONCE_SEPARATOR}{nonce}"
    )
    needs_run = not reason or len(plan.steps) > 1
    if needs_run:
        message.delivery_workflow_id = run_id
    with as_invalid():
        message.full_clean()
    message.save()

    emit(
        name=MESSAGE_SUPPRESSED if reason else MESSAGE_QUEUED,
        tenant=tenant,
        payload=_payload(message),
        actor=actor,
    )
    if not needs_run:
        return message
    # Delivery waits and retries, so it is a workflow and not the rest of this
    # function. The start is registered on this transaction's commit — a send
    # that rolls back emails nobody — and the id is derived from the row (house
    # rule 18), so a retried send starts one run and not two. **One run for the
    # whole escalation**, not one per step: the interpreter is the only
    # orchestrator, and a run per step would be a chain nothing could stop.
    start_workflow_on_commit(
        workflow=DELIVER_WORKFLOW,
        arg=DeliverMessage(
            message_id=str(message.pk),
            steps=plan.steps,
            first_step_status=str(message.status),
            # Seconds and not an instant, for `DeliveryAttempt.defer_seconds`'
            # reason restated in `types.py`: the workflow may import `timedelta`
            # and nothing else from `datetime`, so a duration is a thing it can
            # act on and an instant is a thing it would have to parse.
            delay_seconds=delay,
            nonce=nonce,
        ),
        tenant=tenant,
        user=actor.user,
        org=actor.org,
        id=run_id,
    )
    return message


def _delay_seconds(*, send_at: datetime | None, at: datetime) -> int:
    """`send_at` as a duration. **Zero is the ordinary answer.**

    Naive input is refused by name rather than assumed into the server's zone: a
    scheduled send is a promise about an instant, and a moment with no timezone
    is a moment in somebody's assumption — guessing whose midnight was meant is
    the one mistake a schedule cannot recover from afterwards.

    A moment already **past** is zero, not a refusal. The honest reading of
    "send it at 09:00" received at 09:01 is *send it*, and a client's clock
    running a second fast must not become an error it cannot diagnose.
    """
    if send_at is None:
        return 0
    if timezone.is_naive(send_at):
        raise Invalid(
            {"send_at": ["A scheduled send needs a timezone-aware moment; this one has none."]}
        )
    return max(0, int((send_at - at).total_seconds()))


def _wait_for(
    *,
    reason: str,
    preference: ChannelPreference | None,
    tenant: Tenant,
    at: datetime,
    send_at: datetime | None,
) -> tuple[int, str]:
    """How long this send waits, and which refusal (if any) survives the wait.

    Two questions with one answer, because at queue time they are the same
    question: *is there something to wait for, and does waiting help?*

    **The other half, and it is the whole of that fix.** A temporal lever delays;
    it does not kill (ADR comms-10) — and until this fix that was true at
    the transport edge and false at queue time, so a marketing send submitted at
    22:30 was thrown away while the identical send submitted at 21:59 was
    deferred and delivered at 07:00. The asymmetry was real and had a reason at
    the time: at queue time no run existed to wait in. This starts one.

    So a temporal refusal returns **no refusal**: the caller writes `queued`,
    which is true — the message is still waiting to go out — emits
    `comms.message.queued`, which is also true, and starts the run with the
    seconds the window has left. It wakes into `deliver_message` and re-runs the
    FULL wall, which is where a suppression that landed overnight refuses. The
    sleep is not a way around the wall; it is a way back to it.

    A **permanent** refusal is untouched and still kills: consent that was never
    given does not arrive by waiting, and a suppressed address does not
    un-suppress overnight.

    The two waits **take the longer of themselves**, for the reason
    `quiet_defer_seconds` takes the longer of its two windows: waking early is
    waking into a refusal, and a refusal on the far side of a sleep spends the
    run's one deferral on nothing.
    """
    delay = _delay_seconds(send_at=send_at, at=at)
    if reason not in TEMPORAL_REASONS:
        return delay, reason
    return (
        max(delay, quiet_defer_seconds(preference=preference, tenant=tenant, at=at)),
        "",
    )


# --- the escalation's later rungs -------------------------------------------------


@dataclass(frozen=True)
class StepOutcome:
    """One escalation step, and how long the interpreter should wait for it.

    A **small typed result** rather than the bare `Message`, which is the shape
    `django-conventions` §4 allows a service when the object alone cannot carry
    the answer. It cannot here: "how long is this step deferred for" is a fact
    about this decision and not about the row, and there is deliberately no
    column for it — the wait lives on the run, exactly as `send_at`'s does, and
    `Message.send_at` is the visible record of it.

    The first shape tried was an attribute stuck on the returned model
    instance. `mypy --strict` refused it, correctly: a value a reader cannot
    find on the class is a value the next caller will not know to read.
    """

    message: Message
    #: Seconds the quiet-hours wall held this step for. Zero unless deferred,
    #: which is almost every step.
    deferred_seconds: int = 0


@service
def send_step(
    *,
    tenant: Tenant,
    actor: Actor,
    message: Message,
    step: int,
    channel: str,
    template: str,
) -> StepOutcome:
    """One later rung of an escalation. **The consent wall runs again, here.**

    ADR comms-7, and it is the frame's demanded property: consent is re-checked
    **at each step's own send time**, not snapshotted when the policy was
    entered. Somebody who unsubscribes, gets suppressed by a hard bounce, or
    revokes marketing consent between the text and the email must not get the
    email — and the only way that is true is if the wall stands here, in the
    service that writes the row, where no interpreter and no activity can reach
    around it. A step the wall refuses writes its `suppressed` `Message`, says
    so on the spine, and the run escalates past it without waiting: there is
    nothing to wait for, because nothing went out.

    `message` is the **anchor** — step 1's row — and everything that identifies
    who this is for comes off it: the recipient, the acting organization, the
    rendered context, the policy's name and version, and the correlation chain.
    That is what keeps a three-step escalation one conversation in the log
    instead of three unrelated messages that happen to share a recipient.

    `delivery_workflow_id` is copied rather than rebuilt, and that is the column
    earning its keep: every message in this escalation points at the **one**
    interpreting run, so a provider status webhook for step 2 signals the run
    that is waiting on step 2 — which an id derived from a message's own primary
    key could not do.

    **It starts no workflow, and that is the rule this service exists to keep.**
    A step that started its own run would make every escalation a chain of runs
    nothing could stop, and "delivered, so do not send the rest" would have no
    single place to be true. The interpreter is the only orchestrator.
    """
    # House rule 26, judged. The anchor arrives from the `send_step`
    # activity, which resolved it through `get_message(... org=)` — a
    # `.visible_to(org)` read, so the row is already in this hat's subtree and
    # this call cannot refuse a legitimate escalation. That is the argument for
    # writing the check rather than a `# reach:` sentence: the sentence would
    # have said "our one caller resolves it safely", which is a property of the
    # caller and not of this service. The escalation's new row lands in
    # `message.organization`, so the reference being reachable is precisely the
    # question, and the run acting for the product is not an answer to it —
    # `may_be_named` has no system exemption on purpose.
    # REACHABILITY FIRST, then the capability — `require` is asked at the
    # node the ROW names since resolution landed, so asking it first turned
    # an anchor outside this hat's subtree into `forbidden`. Not-there
    # before not-yours, as `core.revoke_membership` orders it.
    if not may_be_named(actor, message):
        raise NotFound()
    require(actor, "message.send", message.recipient)
    slug = str(channel or "").strip().lower()
    if slug not in registered_channels():
        raise Invalid({"channel": [f"No transport is registered for the {slug!r} channel."]})

    row = get_template(tenant=tenant, name=template, actor=actor)
    at = timezone.now()
    reason = _refusal(
        preference=get_preference(
            tenant=tenant,
            recipient=message.recipient,
            channel=slug,
            org=message.organization,
            actor=actor,
        ),
        category=row.category,
        at=at,
    )
    # **The last piece of kill-vs-delay.** A temporal lever
    # delays; it does not kill (ADR comms-10) — true at the transport edge
    # since comms-10, true at queue time since the deferred-window mechanism,
    # and until this fix false here. So an escalation step landing in a quiet window wrote
    # `suppressed`, the interpreter read "nothing went out" and escalated
    # straight past it: the person's own quiet hours cost them the step, and the
    # chain moved on to a channel they had not asked to be reached on. That is
    # the wall being a weapon with extra steps.
    #
    # The step is now DEFERRED — the row is `queued`, which is what it is — and
    # `deferred_seconds` goes back to the interpreter, which sleeps and delivers
    # it. The event is `comms.message.queued`, which is also what it is: a
    # suppression event for a message about to be delivered is the ledger lying
    # in the noisiest possible way, and `mark_message_sending` has said so about
    # its own path since comms-10.
    #
    # A **permanent** lever is untouched and still writes `suppressed` here:
    # consent that was never given does not arrive by waiting.
    deferred = reason in TEMPORAL_REASONS
    wait = 0
    if deferred:
        wait = quiet_defer_seconds(
            preference=get_preference(
                tenant=tenant,
                recipient=message.recipient,
                channel=slug,
                org=message.organization,
                actor=actor,
            ),
            tenant=tenant,
            at=at,
        )
        reason = ""

    escalated = _message_row(
        tenant=tenant,
        organization=message.organization,
        recipient=message.recipient,
        template=row,
        channel=slug,
        context=message.context,
        reason=reason,
        at=at,
        policy_name=message.policy_name,
        policy_version=message.policy_version,
        policy_step=int(step),
        send_at=(at + timedelta(seconds=wait)) if wait else None,
        delivery_workflow_id=message.delivery_workflow_id,
        correlation_id=message.correlation_id,
        causation_id=message.causation_id,
    )
    with as_invalid():
        escalated.full_clean()
    escalated.save()
    emit(
        name=MESSAGE_SUPPRESSED if reason else MESSAGE_QUEUED,
        tenant=tenant,
        payload=_payload(escalated),
        actor=actor,
    )
    return StepOutcome(message=escalated, deferred_seconds=wait)


@service
def cancel_message(*, tenant: Tenant, actor: Actor, message: Message) -> Message:
    """Take a message back out of the queue. **Only one nobody has seen yet.**

    The second half of that visibility. `send_at` made a scheduled message visible; this is what
    a person does about it once they can see it — and without it the only way to
    stop a send somebody scheduled for Monday was the Temporal UI, which is not
    a product surface and is not available to whoever is on support.

    **`queued` and nothing else** (`CANCELLABLE`). `sending` means an activity
    is inside a transport at this moment, and a row marked cancelled while a
    gateway was accepting it would be a message the person receives and a log
    that says it was cancelled — a worse lie than the one this closes.
    Everything past that is already somebody's news: `sent`, `delivered`,
    `bounced` are the transport's, `suppressed` and `failed` are settled, and
    `cancelled` is terminal, so a second cancel is a `Conflict` naming the state
    rather than a silent no-op. That last choice is deliberate and is the
    opposite of `archive_recipient`'s: archiving twice is one intent expressed
    twice, where cancelling a message that already went is a caller who believes
    something false and should be told.

    **Its own status, not a `SuppressedReason`.** `suppressed` is the product
    refusing on the RECIPIENT's behalf; this is the SENDER changing their mind,
    and a campaign report that counted these among the opt-outs would be
    inventing consent news. `comms.message.cancelled` is likewise its own name.

    **The run is asked to stop, and the row does not wait to hear back.** The
    row is ours and is settled inside this transaction; the delivery run is
    Temporal's, and the cancel goes out on `transaction.on_commit(...,
    robust=True)` — the shape `apps.workflows.services.cancel_run` documents at
    length. A caller whose transaction rolled back has asked for nothing; an
    unreachable Temporal must not take the hooks queued behind it down with it.
    A cancel that could not be dispatched leaves a run that wakes, re-enters
    `deliver_message`, reads a status outside `SENDABLE` and hands nothing to
    any transport — which is the belt that makes the row, not the run, the thing
    that decides. That belt is why this is safe to do in this order, and it is
    driven rather than assumed (`tests/test_cancel.py`).
    """
    # House rule 26: `message` came off the wire as an id. `require` answered a
    # question about the verb; this one is about the reference.
    # REACHABILITY FIRST, then the capability — `require` is asked at the
    # node the ROW names since resolution landed, so asking it first turned
    # an anchor outside this hat's subtree into `forbidden`. Not-there
    # before not-yours, as `core.revoke_membership` orders it.
    if not may_be_named(actor, message):
        raise NotFound()
    require(actor, "message.cancel", message.recipient)
    if message.status not in CANCELLABLE:
        raise Conflict(
            f"That message is {message.status} and can no longer be cancelled. "
            f"Only a message that has not yet reached a transport can be."
        )

    message.status = Message.Status.CANCELLED
    message.save(update_fields=["status", "updated_at"])
    emit(name=MESSAGE_CANCELLED, tenant=tenant, payload=_payload(message), actor=actor)

    run_id = message.delivery_workflow_id
    if run_id:
        # A named nested `def`, never a `functools.partial`: Django's robust
        # branch formats its error with `func.__qualname__`, which a partial
        # does not have, so the handler whose whole job is to swallow a failing
        # hook raises itself and every hook queued behind it never runs (P3
        # SEC-R3, and `django-conventions` §7 names this exact shape).
        def cancel_the_delivery_run_on_commit() -> None:
            async def _go() -> None:
                from apps.workflows.client import get_client

                client = await get_client()
                await client.get_workflow_handle(run_id).cancel()

            run_async(_go)
            log.info("comms.message.cancel_requested", workflow_id=run_id)

        transaction.on_commit(cancel_the_delivery_run_on_commit, robust=True)
    return message


# --- the delivery workflow's writes ---------------------------------------------


@service
def mark_message_sending(*, tenant: Tenant, actor: Actor, message: Message) -> Message:
    """Take a sendable message to the edge — or refuse it there. **The wall, again.**

    The activity's first write, and since ADR comms-8 it is also the **last
    moment the consent wall gets to speak**. `send()` ran the wall when the row
    was written; the transport runs later — minutes later on a retry, hours
    later on an escalation — and a suppression or a marketing revocation landing
    in between used to be ignored at the one moment that decides whether a human
    is mailed. `send_step` has honoured that seam since ADR comms-7. This is the
    same recheck on the plain path, in the service the delivery activity already
    calls before it has anything to hand over, so no door and no activity can
    reach around it (house rule 10).

    **It runs on every attempt that can still reach a transport, not only the
    first** (SEC-R1b, closing SEC-1's H1). `SENDABLE` holds two statuses on
    purpose: `queued` is a first attempt and `sending` is a retry after a
    transport failed. This
    guard used to read `queued` alone and sat *above* the recheck, so a retried
    row — already `sending` — was returned untouched and the wall never spoke.
    The window that opened was the whole retry backoff, minutes to hours, which
    is precisely the interval a bounce or a revocation arrives in. Both statuses
    now consult `_refusal` against current state, and a `sending` row the wall
    refuses transitions exactly as a `queued` one does.

    **The wall widened; the idempotence narrowed nothing.** Every other status
    still returns early and untouched: `sent`, `delivered` and `bounced` are
    news from the transport, `failed` is a spent run and `suppressed` is already
    the refusal. Re-walling one of those would let a suppression arriving
    afterwards rewrite a settled row, which is the log lying in the other
    direction.

    **And refusal now forks by what kind of lever refused** (ADR comms-10). A
    permanent lever — suppression, consent withdrawn — is a fact about the
    person, and the message dies here as it always did. A temporal lever —
    quiet hours — is a fact about the clock: it stops being true at a knowable
    minute, and killing a message for it threw away sends nobody objected to.
    A temporal refusal writes the row back to `queued`, emits nothing,
    and returns; the caller reads that as "not yet", asks `quiet_hours_opens_in`
    how long, and the run — which is already alive — waits. The three statuses
    this can return are disjoint and that is the caller's whole branch:
    `sending` cleared, `suppressed` was refused for good, `queued` is deferred.

    Refused **for good** means the same thing here as it does everywhere else in
    this app:
    the row goes `suppressed` with its reason, `comms.message.suppressed` is
    emitted, and nothing reaches a provider. **Not a new word and not an
    exception** — a second refusal dialect at the transport would be the drift
    two walls exist to avoid. `suppressed` is in `REPORTED`, so the delivery's
    own bookkeeping cannot walk a refusal — first attempt or fifth — back into a
    `sent`.

    Idempotent, because Temporal guarantees an activity runs *at least* once: a
    second attempt on a message already in flight re-judges consent and
    otherwise changes nothing, one on a message already sent leaves the terminal
    state alone, and a replay after a refusal re-reads `suppressed` and refuses
    again without emitting twice.

    The status this returns is what the caller must branch on: the activity
    hands nothing to a transport unless it reads back as sendable.
    """
    # House rule 26, judged. Same argument as `send_step` above: the
    # `deliver_message` activity read this row through `get_message(... org=)`,
    # so the check is free today and is the whole fence tomorrow. The delivery
    # run always holds a hat — `send()` refuses `actor.org is None` before it
    # starts one — so the platform-acting-for-itself case this rule's `# reach:`
    # valve exists for does not arise in this app, and taking the valve would be
    # choosing the weaker of two available answers.
    # REACHABILITY FIRST, then the capability — `require` is asked at the
    # node the ROW names since resolution landed, so asking it first turned
    # an anchor outside this hat's subtree into `forbidden`. Not-there
    # before not-yours, as `core.revoke_membership` orders it.
    if not may_be_named(actor, message):
        raise NotFound()
    require(actor, "message.send", message.recipient)
    if message.status not in SENDABLE:
        return message

    at = timezone.now()
    reason = _refusal(
        preference=get_preference(
            tenant=tenant,
            recipient=message.recipient,
            channel=message.channel,
            org=message.organization,
            actor=actor,
        ),
        # The row's own category, not the template's: it was denormalised at
        # send time for exactly this kind of later read, and the template may
        # have been revised or retired since.
        category=message.category,
        at=at,
        # The tenant seam again, at the transport edge — the same binding point
        # `send()` used, so a window a product configures applies to a message
        # that has been asleep for a day as well as to one being written now.
        tenant=tenant,
    )
    if reason in TEMPORAL_REASONS:
        # **A temporal lever delays; it does not kill** (ADR comms-10).
        # Nothing is written but the status, and the status is written back to
        # `queued` — which is the true one: this message is still waiting to go
        # out, and a `sending` row would claim a transport had it. No refusal
        # row, no `comms.message.suppressed`, no `suppressed_reason`: none of
        # those are true, and a suppression event for a message that is about to
        # be delivered is the ledger lying in the noisiest possible way.
        #
        # The caller reads the fork off the status, and the three answers are
        # disjoint by construction: `sending` cleared, `suppressed` was refused
        # for good, `queued` is "not yet". The run is already alive and can
        # wait — which is the whole reason this is a delay and not a re-enqueue
        # (ADR comms-10's own rejected alternative).
        if message.status != Message.Status.QUEUED:
            message.status = Message.Status.QUEUED
            message.save(update_fields=["status", "updated_at"])
        return message

    if reason:
        message.status = Message.Status.SUPPRESSED
        message.suppressed_reason = reason
        message.suppressed_at = at
        message.save(update_fields=["status", "suppressed_reason", "suppressed_at", "updated_at"])
        emit(name=MESSAGE_SUPPRESSED, tenant=tenant, payload=_payload(message), actor=actor)
        return message

    message.status = Message.Status.SENDING
    message.save(update_fields=["status", "updated_at"])
    return message


@service
def record_message_sent(
    *,
    tenant: Tenant,
    actor: Actor,
    message: Message,
    provider: str,
    provider_message_id: str,
) -> Message:
    """A transport accepted this message. **Not the same as delivered.**

    `sent` is the furthest this app can see on its own; `delivered` and
    `bounced` are facts a provider tells us afterwards through a status webhook,
    which is C1-1c's door. Recording `delivered` here would be recording
    something nobody observed.

    Idempotent: a replayed activity rewrites the same terminal state and keeps
    the first `sent_at`, because the honest timestamp is the earlier one.

    A message the provider has already reported on is left entirely alone. The
    status webhook is later news from the same transport, and an activity replay
    landing after it must not turn "it arrived" back into "we handed it over".
    """
    # House rule 26, judged. `finish_message` resolved this row through
    # `get_message(... org=)` before calling; the check restates that guarantee
    # where a second caller would have to satisfy it too.
    # REACHABILITY FIRST, then the capability — `require` is asked at the
    # node the ROW names since resolution landed, so asking it first turned
    # an anchor outside this hat's subtree into `forbidden`. Not-there
    # before not-yours, as `core.revoke_membership` orders it.
    if not may_be_named(actor, message):
        raise NotFound()
    require(actor, "message.send", message.recipient)
    if message.status in REPORTED:
        return message
    message.status = Message.Status.SENT
    message.provider = provider
    message.provider_message_id = provider_message_id
    message.error = ""
    message.sent_at = message.sent_at or timezone.now()
    message.save(
        update_fields=[
            "status",
            "provider",
            "provider_message_id",
            "error",
            "sent_at",
            "updated_at",
        ]
    )
    emit(name=MESSAGE_SENT, tenant=tenant, payload=_payload(message), actor=actor)
    return message


@service
def record_message_failed(*, tenant: Tenant, actor: Actor, message: Message, error: str) -> Message:
    """The attempts are spent and it did not go out.

    A message the transport has already accepted, delivered or bounced is left
    alone: a late failure arriving after a success is a replay, and downgrading
    a delivered message would make the log say something that did not happen.
    """
    # House rule 26, judged. The `record_message_sent` argument, on the
    # other branch of the same activity.
    # REACHABILITY FIRST, then the capability — `require` is asked at the
    # node the ROW names since resolution landed, so asking it first turned
    # an anchor outside this hat's subtree into `forbidden`. Not-there
    # before not-yours, as `core.revoke_membership` orders it.
    if not may_be_named(actor, message):
        raise NotFound()
    require(actor, "message.send", message.recipient)
    if message.status in REPORTED:
        return message
    message.status = Message.Status.FAILED
    message.error = str(error)[:ERROR_LIMIT]
    message.failed_at = message.failed_at or timezone.now()
    message.save(update_fields=["status", "error", "failed_at", "updated_at"])
    emit(name=MESSAGE_FAILED, tenant=tenant, payload=_payload(message), actor=actor)
    return message


# --- what the transport said afterwards ------------------------------------------


def _signal_delivery(*, tenant: Tenant, actor: Actor, message: Message, status: str) -> None:
    """Tell the waiting delivery run that its answer arrived. **Best effort.**

    Best effort by design, not by neglect. The row is the record and the event
    is the announcement — both are already written, inside this transaction, by
    the time this is called. The signal only shortens a wait: a run that has
    already finished (its seventy-two hours ran out, the worker was replaced,
    the message never had a run at all) has nothing left to be told, and turning
    that into a 500 on a webhook door would make a *late* status indistinguishable
    from a *lost* one.

    So `Conflict` and `NotFound` from `signal_workflow` are swallowed and
    logged, and nothing else is: an unexpected exception is a real fault and
    belongs where the caller can see it.
    """
    if not message.delivery_workflow_id:
        return
    try:
        signal_workflow(
            tenant=tenant,
            actor=actor,
            workflow_id=message.delivery_workflow_id,
            signal=DELIVERY_SIGNAL,
            arg=DeliveryStatus(message_id=str(message.pk), status=status),
        )
    except (Conflict, NotFound) as refusal:
        log.info(
            "comms.delivery_status.signal_skipped",
            message_id=str(message.pk),
            workflow_id=message.delivery_workflow_id,
            status=status,
            code=refusal.code,
        )


def _record_complaint(
    *, tenant: Tenant, actor: Actor, message: Message, connection: Connection | None
) -> Message:
    """Somebody pressed "report spam". **Consent news, not delivery news.**

    ADR comms-9 as amended, and the whole of the split. A complaint is a fact
    about **consent**, a bounce a fact about the **address**, a delivery a fact
    about the **message** — three populations comms-8 collapsed into one status
    so that one suppression rule could read one column. The collapse stays for
    bounces; the complaint leaves it, because a complaint **by definition
    follows a delivery** and the collapsed set could only say it by writing
    `bounced` onto a row that had arrived. E1′'s live drive found the
    consequence: `complained@resend.dev` came back
    `Conflict("That message is delivered and can no longer be bounced.")`,
    loudly, and nobody was suppressed — zero preference rows for a person who
    had just reported us as spam.

    So: **the status is never touched** — `delivered` stays `delivered`, `sent`
    stays `sent` (the provider never said otherwise, and a message that was in
    fact delivered but never reported reads `sent` for ever, which is honest to
    what the transport told us). Nothing is stamped, no `bounce_kind` is
    written, no `error` prose lands. What happens is what a complaint *is*: the
    recipient is suppressed through `suppress_recipient` — the existing door, a
    spam complaint already in its docstring — and the fact is announced under
    its own name.

    **Above the guards, deliberately.** The same-status no-op and the
    settled-row `Conflict` are both guards on *transitions*, and this makes
    none, so neither is about it. Reading them anyway would put the complaint
    back inside the collapse it is leaving: a complaint after a hard bounce
    would return silently on the first (the recipient is already suppressed —
    but the complaint is still a fact and still deserves its name), and a
    complaint after a delivery would be refused by the second, which is the
    defect.

    **Idempotence is the door's, and it is the provider's own event id** (C4):
    `apps/connections`' receiver dedupes a redelivery on `svix-id` /
    `webhook-id` / `x-delivery-id` against
    `inboundwebhook_unique_delivery_per_connection`, so the second copy of one
    complaint never reaches this function. Underneath that,
    `suppress_recipient` keeps the first timestamp. The residue is stated
    rather than papered over: **two complaints with two different provider
    event ids are two facts and are announced twice** — which is what they are,
    and the alternative (reading "already suppressed" as "already complained")
    would silence a second, genuine report and would swallow a complaint about
    a person a *bounce* had suppressed.

    **No signal to the delivery run.** `_signal_delivery` tells a waiting
    workflow what became of the message, and a complaint does not know: the run
    keeps waiting for its own news exactly as it does when no status ever
    arrives. Signalling `bounced` would be the lie this whole fork exists to
    stop writing down.

    **A blind spot created here, and it is the rung's STOP clause firing on one
    clause** (F1m-6; the rung's report says so, and the criteria's negatives ask
    for the opposite). The tripwire is *called* on this path exactly as it is on
    a hard bounce's — same `connection`, same window, `_note_suppression` below
    — but the count it reads, `_suppressed_addresses_since`, is a population of
    `Message` rows (`status=bounced`, `bounce_kind=hard`, `bounced_at` inside
    the trailing hour), and a complaint deliberately writes none of those three.
    So a flood made **only** of complaints silences every address and opens no
    surge; a flood mixing bounces and complaints still trips on its bounces, so
    this narrows the alarm rather than removing it.

    It cannot be closed inside the "no column" bound here, which is what the
    STOP clause was written for. The counter is a **trailing-window read over a
    timestamped population**, and after the split a complaint has no timestamp
    of its own to be counted by — that is a `complained_at` on `Message`, on
    comms-9's named trigger. The audit trail is the other candidate and is
    not one today: the `@service` decorator stamps `object_id` with the row a
    service returned, which for `suppress_recipient` is the `ChannelPreference`
    and not the address, so "how many distinct addresses" is not a question that
    table can answer; and its two supported reads are tenant-leading pages, not
    a per-suppression aggregate on a webhook's hot write path.
    `test_suppression_wall.py`'s two F1m tests pin both halves, so closing this
    starts as a red test and not as a guess.
    """
    suppress_recipient(
        tenant=tenant, actor=actor, recipient=message.recipient, channel=message.channel
    )
    # After the write it describes, in the same transaction, and carrying the
    # row exactly as it stands — a `delivered` message reads `delivered` in the
    # payload, which is the point. The provider's own handle for the message
    # rides along as `provider_message_id`: the join back to the report.
    emit(name=MESSAGE_COMPLAINED, tenant=tenant, payload=_payload(message), actor=actor)
    _note_suppression(tenant=tenant, actor=actor, connection=connection)
    return message


@service
def record_delivery_status(
    *,
    tenant: Tenant,
    actor: Actor,
    provider_message_id: str,
    status: str,
    detail: str = "",
    bounce_kind: str = "",
    is_complaint: bool = False,
    connection: Connection | None = None,
) -> Message:
    """What the transport said became of a message. **The only writer of `delivered`.**

    Called from one place — the status handler in `providers.py`, behind
    `apps/connections`' signature-verified receiver (ADR comms-3) — and reached
    by nobody else: `policies.can_record_status` refuses every membership, so a
    person cannot assert a delivery, and only the system actor a verified
    webhook acts as gets through.

    Seven decisions, in this order, and the order is the contract:

    1. **the vocabulary is closed.** Anything outside `providers.STATUS_VALUES`
       is `Invalid` with the field named, before any row is read. A provider
       inventing a fourth word must not become a `Message.status` the rest of
       the product cannot read;
    2. **the message is found through the tenant and the hat.** The selector is
       the cross-tenant wall — see `get_message_by_provider_id`;
    2a. **a complaint leaves here** (ADR comms-9, amended): it transitions
       nothing, so none of the guards below are about it — they are guards on
       *transitions*. `_record_complaint` is why the fork sits above them;
    3. **the same status twice is a no-op, not a refusal.** Every ESP worth
       integrating with redelivers, so an identical webhook arriving twice must
       transition once and emit once. Returning the row unchanged is what makes
       the second delivery a `202` with nothing behind it;
    4. **anything else off a settled row is a `Conflict`.** `delivered` →
       `bounced` is a log contradicting itself, and a status on a `suppressed`
       message is a status on a message that was never sent;
    5. **a HARD bounce suppresses the address it came from** (ADR comms-8, as
       amended by comms-9). It goes through `suppress_recipient` **inside this
       transaction**, under the system actor the webhook already is, and lifts
       through `unsuppress_recipient` like a hand-written one: a data-quality
       fact, not a punishment. Before comms-8 the record was kept faithfully and
       consulted by nobody, and the next send to a provably dead address sailed
       through the consent wall. **A SOFT bounce records and
       does not act** (comms-9) — `SUPPRESSING_KINDS` is the fork
       and `UNCLASSIFIED_BOUNCE` is what an unclassified one becomes;
    6. **a suppression is counted, and a flood is announced** (comms-9 (c)):
       `_note_suppression`, which says so once on the way up and once on the way
       down, and never halts the wall.

    `connection` is the door the report came through, from the receiver's own
    row, and is what the tripwire counts against; a call without one records and
    suppresses as before. The stamp, the event, the suppression, the tripwire
    and the signal are all in this transaction: all of them land, or none do.

    `is_complaint` is the adapter's judgement and never this function's — what
    makes a report a complaint is one ESP's word for one event type, knowledge
    that lives in `providers.normalize_status` — and it defaults `False`, so
    every existing caller keeps the behaviour it had.
    """
    require(actor, "message.record_status")
    slug = str(status or "").strip().lower()
    if slug not in STATUS_VALUES:
        raise Invalid({"status": [f"{status!r} is not a delivery status this product records."]})

    message = get_message_by_provider_id(
        tenant=tenant, provider_message_id=provider_message_id, org=actor.org
    )
    if is_complaint:
        return _record_complaint(tenant=tenant, actor=actor, message=message, connection=connection)
    if message.status == slug:
        # The provider said it again. Already recorded, already announced.
        return message
    if message.status not in OPEN_TO_STATUS:
        raise Conflict(f"That message is {message.status} and can no longer be {slug}.")

    stamp = STATUS_STAMPS[slug]
    fields = ["status", stamp, "updated_at"]
    message.status = slug
    setattr(message, stamp, timezone.now())
    if slug in SUPPRESSING:
        # Every bounce recorded from here on carries a kind, and a kind nobody
        # gave is `UNCLASSIFIED_BOUNCE` — see there for why that is hard. A
        # value outside the choices takes the same branch rather than landing a
        # word the rest of the product cannot read: a product's own adapter
        # inventing a third kind must not be able to invent a bounce that
        # suppresses nobody by spelling it wrong.
        kind = str(bounce_kind or "").strip().lower()
        message.bounce_kind = kind if kind in BounceKind.values else UNCLASSIFIED_BOUNCE
        fields.append("bounce_kind")
    if detail and slug != Message.Status.DELIVERED:
        # The provider's own words about why it did not arrive, on the column a
        # support agent already reads. A `delivered` event's prose is never kept:
        # there is nothing to explain, and overwriting `error` on a success would
        # put text in the field a client reads to find out what went wrong.
        message.error = str(detail)[:ERROR_LIMIT]
        fields.append("error")
    message.save(update_fields=fields)

    emit(name=STATUS_EVENTS[slug], tenant=tenant, payload=_payload(message), actor=actor)
    if message.bounce_kind in SUPPRESSING_KINDS:
        # The feedback loop, closed (ADR comms-8). No new service and no new
        # flag: the transport just told us this address is not reachable, which
        # is the same fact a support agent records by hand, so it goes through
        # the same door and lifts through the same one.
        #
        # Read off the ROW rather than off the argument, so the branch is taken
        # on exactly what was written: a status outside `SUPPRESSING` never sets
        # the column, so `delivered` and `failed` cannot reach here however the
        # caller spelled `bounce_kind`, and a soft bounce is on the row and out
        # of this set (ADR comms-9).
        #
        # `actor` is provably a `system` actor — `policies.can_record_status`
        # refuses every membership, and only `authz.allows`' system branch
        # reaches this function at all — so the audit row reads `system` without
        # this line minting a second principal to say so.
        #
        # No call to `_signal_delivery` and no second emit: the suppression is a
        # fact about the *person*, not about this message, and the message's own
        # announcement is the one above.
        suppress_recipient(
            tenant=tenant, actor=actor, recipient=message.recipient, channel=message.channel
        )
        _note_suppression(tenant=tenant, actor=actor, connection=connection)
    _signal_delivery(tenant=tenant, actor=actor, message=message, status=slug)
    return message


#: The engagement kinds, hoisted beside the status vocabulary for the reason
#: `STATUS_VALUES` is hoisted: a closed set the service checks BEFORE a row is
#: read, so a provider's adapter inventing a third word is refused rather than
#: landing a `kind` the rest of the product cannot read. Derived from the model's
#: own choices, never retyped — a second list is a second thing to keep in step.
ENGAGEMENT_KINDS: frozenset[str] = frozenset(MessageEngagement.Kind.values)

#: Which event each kind announces. A dict rather than a formatted name for
#: `STATUS_EVENTS`' reason (house rule 16): an event name is a published
#: contract, so it is a declared constant and never a string a call site builds.
ENGAGEMENT_EVENTS: dict[str, str] = {
    MessageEngagement.Kind.OPENED.value: MESSAGE_OPENED,
    MessageEngagement.Kind.CLICKED.value: MESSAGE_CLICKED,
}


# door: recording an engagement is deliberately unreachable from any door a
# client can call (ADR comms-9, section Doors: "deliberately door-less:
# engagement writes"). A REST or MCP write here would let a client MINT
# "OPENED" FACTS about a person into a table whose entire value is that it is
# witnessed — and the same client could then read them back as evidence. Its one
# caller is the status-webhook handler in `providers.py`, behind the
# signature-verified receiver in `apps/connections`, acting as the system. The
# READ door is the message log's and lands with the engagement list on
# `Message`.
@service
def record_engagement(
    *,
    tenant: Tenant,
    actor: Actor,
    provider_message_id: str,
    kind: str,
    occurred_at: datetime | None = None,
    url: str = "",
    provider_event_id: str = "",
) -> MessageEngagement:
    """What a provider says a person did with a message. **And nothing else.**

    ADR comms-9's engagement half, and the sibling of `record_delivery_status`
    in every respect but the one that matters: **this writes no `Message` field
    at all.** An open is an inference from a request for a tracking image — on
    Apple Mail Privacy Protection, one made for every message a user receives —
    and a delivery is something a transport witnessed. Two populations, and this
    one never reaches into the other. There is no branch below that touches
    `message.status`, `delivered_at`, or any other column on the row, and that
    absence is the contract.

    Five decisions, in this order:

    1. **the vocabulary is closed.** Anything outside `ENGAGEMENT_KINDS` is
       `Invalid` with the field named, before any row is read;
    2. **the message is found through the tenant and the hat**, by the same
       selector and therefore behind the same cross-tenant wall the status
       webhook is — see `get_message_by_provider_id`;
    3. **a redelivery returns the first row** (architect C4). The key is
       `(message, provider_event_id, kind)`, held by a unique constraint, and an
       ESP worth integrating with redelivers. Returning the row unchanged is
       what makes the second delivery a `202` with nothing behind it — and it
       means no second event is announced either;
    4. **the row lands in the MESSAGE's branch**, never in the acting hat's. The
       hat here is the tenant's ROOT (a provider has no idea a branch exists), so
       a row stamped from the actor would be invisible to the branch whose
       message it is about. `derive_org_from = "message"` declares it and
       `full_clean()` enforces it;
    5. **it announces itself and stops.** `comms.message.opened` or
       `.clicked`, carrying `MessageEngagementOut`, inside this transaction.

    **Witnessing, not consent.** This never suppresses, never sends, and records
    an engagement for a recipient who has since been suppressed — a fact about
    the past is not permission for the future, and it is not a punishment
    either. Nothing here reads or writes a `ChannelPreference`.

    **The row-effect of the mapping next door, restated because this is where a
    reader will look for it** (the F1-comms note, `queue.md` 2026-08-23): an
    inbound SMS opt-out is not an engagement. It maps to `complained` in
    `record_delivery_status`, which after ADR comms-9's split **suppresses the
    recipient and leaves the message row's status exactly where it was** — no
    transition, no `bounced_at`, no `bounce_kind` — and writes no row in this
    table, because `opened` and `clicked` are the whole of this vocabulary.
    `tests/test_engagement.py` pins all three halves.

    `occurred_at` is when the PROVIDER says it happened and defaults to now when
    it named no time; `created_at` already answers "when did we hear". `url` is
    a click's destination and is refused on an open by the check constraint —
    the database holds it because "which link" is a question every engagement
    report asks and an `opened` row with a URL would answer it wrongly.

    `provider_event_id` is the transport's own handle for the event, and blank
    is legal: the class docstring on `MessageEngagement` carries the residue
    that creates and the trigger that closes it.
    """
    require(actor, "message_engagement.create")
    slug = str(kind or "").strip().lower()
    if slug not in ENGAGEMENT_KINDS:
        raise Invalid({"kind": [f"{kind!r} is not an engagement this product records."]})
    message = get_message_by_provider_id(
        tenant=tenant, provider_message_id=provider_message_id, org=actor.org
    )
    handle = str(provider_event_id or "").strip()[:255]
    existing = (
        MessageEngagement.objects.for_tenant(tenant)
        .visible_to(actor)
        .filter(message=message, provider_event_id=handle, kind=slug)
        .first()
    )
    if existing is not None:
        # The provider said it again. Already recorded, already announced.
        return existing

    engagement = MessageEngagement(
        tenant=tenant,
        # From the MESSAGE, not from `actor.org`. Decision 4 above; the landing
        # gate in `OrgScopedModel.clean()` refuses any other answer, so this line
        # and that gate say the same thing twice on purpose.
        organization=message.organization,
        message=message,
        kind=slug,
        # A click's link only. An open's URL is refused by
        # `comms_engagement_url_is_a_clicks_own`, so this is the service saying
        # the same thing early rather than letting an adapter's stray field turn
        # into an IntegrityError at the door.
        url=str(url or "") if slug == MessageEngagement.Kind.CLICKED.value else "",
        occurred_at=occurred_at or timezone.now(),
        provider_event_id=handle,
    )
    with as_invalid():
        engagement.full_clean()
    engagement.save()
    emit(
        name=ENGAGEMENT_EVENTS[slug],
        tenant=tenant,
        payload=MessageEngagementOut.from_orm(engagement).model_dump(mode="json"),
        actor=actor,
    )
    return engagement


# --- the push address book --------------------------------------------------------


def hash_push_token(token: str) -> str:
    """The identity of a push token: SHA-256 over its bytes, hex.

    A module-level function rather than a method on the model, because it is
    what `register_device` computes *before* there is a row and what a test
    plants a duplicate with. `hash` is house rule 16's declared verb for exactly
    this, and the column it fills is `push_token_hash`, so rule 15 reads that
    field for what it is — a digest, not a recoverable secret — while the
    ciphertext beside it holds the token.

    Not salted, and that is the deliberate half. A salt would make the column
    useless for the one job it has: finding the row a re-registration belongs
    to, in one indexed lookup, without decrypting every device in the tenant. A
    registration token is high-entropy vendor-minted material, not a password,
    so the dictionary attack a salt defends against does not exist here.
    """
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


@service
def register_device(
    *,
    tenant: Tenant,
    actor: Actor,
    recipient: Recipient,
    platform: str,
    push_token: str,
    label: str = "",
) -> Device:
    """Remember a handset this contact will accept notifications on.

    **Idempotent by the token, because a mobile client re-registers constantly**
    (architect C4). A phone hands its registration token back on every launch,
    after every reinstall and whenever the platform rotates it, and a door that
    answered `409` to the second call would make the normal case an error every
    client had to special-case. So the second registration of one token updates
    the row it finds — the contact, the platform, the label — and brings it back
    from `retired` if it was there, which is exactly what re-registering
    means.

    **It is not a consent decision.** Registering a device says the product
    *can* reach this handset; whether it *may* is the `push` channel's
    `ChannelPreference`, checked inside `send()` where no caller can reach
    around it. A product that treated a registration as an opt-in would have a
    consent wall in two places, disagreeing.

    There is deliberately no `organization=` parameter, for `create_recipient`'s
    reason and one stronger: `Device.derive_org_from = "recipient"`, so the row
    lands where the contact lives and `OrgScopedModel.clean()` refuses anything
    else — the acting hat decides *whether* this caller may register, never
    *where* the row goes.
    """
    # House rule 26. `recipient` came off the wire as an id, and `require`
    # answers a question about the verb; this one is about the reference. A
    # contact in a branch this hat holds no membership over is `not_found`.
    # REACHABILITY FIRST, then the capability. `require` is asked AT THE
    # NODE THE ROW NAMES since resolution landed, so asking it first turned a
    # row in a branch this hat holds no membership over into `forbidden` —
    # which tells the caller the row exists. Not-there before not-yours, the
    # order `core.revoke_membership` has always used.
    if not may_be_named(actor, recipient):
        raise NotFound()
    require(actor, "device.create", recipient)
    slug = str(platform or "").strip().lower()
    if slug not in {choice.value for choice in Device.Platform}:
        raise Invalid({"platform": [f"{platform!r} is not a platform this product pushes to."]})
    token = str(push_token or "").strip()
    if not token:
        raise Invalid({"push_token": ["A device registration needs the platform's token."]})

    digest = hash_push_token(token)
    device = get_device_by_token_hash(tenant=tenant, push_token_hash=digest, org=actor.org)
    if device is None:
        device = Device(
            tenant=tenant,
            organization=recipient.organization,
            recipient=recipient,
            platform=slug,
            push_token=token,
            push_token_hash=digest,
            label=str(label).strip(),
        )
    else:
        # The re-registration path. `organization` moves with the recipient
        # because the row's branch is derived from it: a contact whose device
        # was registered under one contact row and re-registered under another
        # in a different branch follows the contact, and the landing gate in
        # `clean()` refuses the pair if they ever disagree.
        device.recipient = recipient
        device.organization = recipient.organization
        device.platform = slug
        device.push_token = token
        device.label = str(label).strip()
        device.retired_at = None
    with as_invalid():
        device.full_clean()
    device.save()
    emit(
        name=DEVICE_REGISTERED,
        tenant=tenant,
        payload=DeviceOut.from_orm(device).model_dump(mode="json"),
        actor=actor,
    )
    return device


@service
def retire_device(*, tenant: Tenant, actor: Actor, device: Device) -> Device:
    """Stop pushing to one install. The row stays; it leaves the address book.

    Not a delete, and it could not be: a `Message` that went to this handset
    records the provider's handle for it, and "which device did that
    notification land on" is unanswerable from a deleted row.

    **It is not a consent decision either**, exactly as `archive_recipient` is
    not: "stop pushing to this person" is `suppress_recipient` on the `push`
    channel, enforced inside `send()`. This is "that install is gone" — the
    person signed out, the handset was sold, the platform retired the token.
    Two walls that could disagree would be one wall too many.

    Idempotent: retiring a retired device keeps the first timestamp,
    because the honest answer to "when did we stop being able to reach it" is
    the earlier one — and it emits nothing the second time, so a client
    retrying does not announce a state change that did not happen.
    """
    # REACHABILITY FIRST, then the capability. `require` is asked AT THE
    # NODE THE ROW NAMES since resolution landed, so asking it first turned a
    # row in a branch this hat holds no membership over into `forbidden` —
    # which tells the caller the row exists. Not-there before not-yours, the
    # order `core.revoke_membership` has always used.
    if not may_be_named(actor, device):
        raise NotFound()
    require(actor, "device.retire", device)
    if device.retired_at is not None:
        return device
    device.retired_at = timezone.now()
    device.save(update_fields=["retired_at", "updated_at"])
    emit(
        name=DEVICE_RETIRED,
        tenant=tenant,
        payload=DeviceOut.from_orm(device).model_dump(mode="json"),
        actor=actor,
    )
    return device


# --- the mass-suppression tripwire ------------------------------------------------


def _suppressed_addresses_since(*, tenant: Tenant, org: Organization, since: datetime) -> int:
    """How many distinct addresses a reported hard bounce has silenced since `since`.

    **Distinct recipients and not rows**, because the question the tripwire asks
    is "how many people has the wall silenced", and one address whose four
    in-flight messages all bounce is one person. Counting rows would let an
    ordinary fan-out trip an alarm about an attack.

    Counted off `Message` rather than off `ChannelPreference` on purpose: a
    suppression a human wrote through the management surface is an audited act
    by a named person with its own review path, and folding it in here would
    make a support agent working through a bounce list look like an attack.
    This counts the population the vector actually runs through — addresses
    silenced by a *reported* hard bounce.

    `org` is the hat the suppressions were made under — the tenant root, for
    the only caller there is, because a verified webhook's system actor is
    resolved there. `Message` is org-scoped, so the read chains `.visible_to`
    like every other one (house rule 24): the count is what *this* hat can see,
    which for the root is the whole tenant and for a narrower hat would be a
    narrower count, honestly. There is no widened read here and there is no
    exemption asking for one.

    Two declared blind spots, stated where they are created. The window is
    channel-agnostic and per tenant, and the surge row names the connection the
    crossing report arrived on — so a tenant running two ESP connections shares
    one counter, which over-counts rather than under-counts and is the safe
    direction for an alarm; narrowing it wants a connection on the `Message`
    row, a column no criterion here asks for. And a slow drip below the
    threshold is invisible, which `SURGE_THRESHOLD` says out loud.
    """
    return (
        Message.objects.for_tenant(tenant)
        .visible_to(org)
        .filter(
            status=Message.Status.BOUNCED,
            bounce_kind=BounceKind.HARD,
            bounced_at__gte=since,
        )
        .values("recipient_id")
        .distinct()
        .count()
    )


def _note_suppression(*, tenant: Tenant, actor: Actor, connection: Connection | None) -> None:
    """Count the trailing hour and announce a crossing — in either direction.

    Called once per hard-bounce suppression, inside `record_delivery_status`'s
    transaction, and it announces **transitions only** (the announce-on-transition
    ruling of 2026-08-22, this cycle's first application). The open
    `SuppressionSurge` row is the memory that makes that true: while one is
    open, another twenty crossings say nothing, so an attacker re-probing the
    wall cannot turn the alarm into a flood a human learns to ignore.

    A call with no connection counts nothing and announces nothing. That is not
    a gap being tolerated: the tripwire is about a *transport* reporting a flood
    of bounces, and there is no such transport in a call that did not come
    through one. A call with no acting hat is the same shape and is
    unreachable today for a reason worth stating rather than assuming — the
    suppression that precedes this one goes through `may_be_named`, which
    refuses `NotFound` on an unresolved hat, so this branch is a fence and not a
    path. It logs, because an alarm that stopped counting must never do it
    quietly.

    A private helper rather than a service, because it has no authorization of
    its own to do — it is bookkeeping inside a write `require(actor,
    "message.record_status")` has already cleared, and the two writes it may
    reach for are services with their own `require`.
    """
    if connection is None:
        return
    if actor.org is None:
        log.warning("comms.suppression.uncounted", connection_id=str(connection.pk))
        return
    count = _suppressed_addresses_since(
        tenant=tenant, org=actor.org, since=timezone.now() - SURGE_WINDOW
    )
    surge = (
        SuppressionSurge.objects.for_tenant(tenant)
        .filter(connection=connection, ended_at__isnull=True)
        .first()
    )
    if surge is None:
        if count >= SURGE_THRESHOLD:
            start_suppression_surge(tenant=tenant, actor=actor, connection=connection, count=count)
        return
    if count < SURGE_THRESHOLD:
        close_suppression_surge(tenant=tenant, actor=actor, surge=surge, count=count)
    elif count > surge.suppression_count:
        # Still surging, and worse than it has been. The row carries the worst
        # trailing hour seen while it was open, which is what a human triaging
        # it wants and is the only thing that moves on an open row besides
        # `ended_at`. No event: the state has not changed, and saying so again
        # is the noise the ruling exists to refuse.
        surge.suppression_count = count
        surge.save(update_fields=["suppression_count", "updated_at"])


def _surge_payload(surge: SuppressionSurge) -> dict[str, Any]:
    """What a subscriber is told about a surge. **The state, not a message.**

    Hand-built rather than an `Out` schema because there is no door that
    publishes a surge — no route, no tool, no list — and a schema nothing
    serves would be a contract with no reader. What travels is the connection
    the flood came through, the window it was counted over, the threshold it
    crossed and the worst count seen: enough for an alert rule to fire on and
    for a human to know where to look, and nothing about any person.
    """
    return {
        "v": V,
        "id": str(surge.pk),
        "connection_id": str(surge.connection_id),
        "started_at": surge.started_at.isoformat(),
        "ended_at": surge.ended_at.isoformat() if surge.ended_at else None,
        "suppression_count": surge.suppression_count,
        "window_seconds": int(SURGE_WINDOW.total_seconds()),
        "threshold": SURGE_THRESHOLD,
    }


@service
def start_suppression_surge(
    *, tenant: Tenant, actor: Actor, connection: Connection, count: int
) -> SuppressionSurge:
    """Open the episode and say so once. **The wall has started firing.**

    The row is written before the event and both are in this transaction, so a
    subscriber can never be told about a surge whose row is not there to close.
    The partial uniqueness on the model is what makes "once" survive two
    webhooks landing on one connection in the same instant: the second
    transaction loses on the constraint rather than opening a second episode.

    `require` against a policy that refuses every membership: a surge is
    observed, never declared, exactly as a delivery status is. Only the system
    actor a verified webhook acts as reaches it.

    **And the node it asks at is the ROOT**, although the predicate already
    refuses every person: the tripwire's memory is the tenant's, the node is
    what a reader of this line has to be able to see, and a question asked at
    the hat is one predicate edit away from being a branch administrator's. A
    `system` actor is answered before any node is read, so this costs the
    webhook path one query at a crossing and nothing per message.
    """
    require(actor, "suppression_surge.create", root_organization(tenant=tenant))
    # Built and validated rather than `.objects.create(...)` — the house shape
    # every other write in this module uses, and the one that keeps a scoped
    # model's bare manager out of a service (house rule 8).
    surge = SuppressionSurge(
        tenant=tenant,
        connection=connection,
        started_at=timezone.now(),
        suppression_count=count,
    )
    with as_invalid():
        surge.full_clean()
    surge.save()
    log.warning(
        "comms.suppression.surged",
        connection_id=str(connection.pk),
        count=count,
        threshold=SURGE_THRESHOLD,
    )
    emit(name=SUPPRESSION_SURGED, tenant=tenant, payload=_surge_payload(surge), actor=actor)
    return surge


@service
def close_suppression_surge(
    *, tenant: Tenant, actor: Actor, surge: SuppressionSurge, count: int
) -> SuppressionSurge:
    """Close the episode and say so once. **The trailing hour is back under.**

    An alert that can be raised and never lowered is an alert somebody silences,
    so the recovery is as declared as the crossing. Once `ended_at` is set the
    row is history and nothing writes it again — a second flood on the same
    connection is a second row, which is why the model's uniqueness is
    conditional on being open.

    The honest limit, and it is the model's too: the close happens at the next
    *recording*, not on a clock. A surge that simply stops arriving leaves the
    row open until the connection reports again — which is exactly when the
    recovery announcement matters, and is a poller nobody has to build (rule 30's
    class, avoided rather than paid for).
    """
    # At the root, for `start_suppression_surge`'s reason — the same key, the
    # same tenant-wide row, the same height.
    require(actor, "suppression_surge.create", root_organization(tenant=tenant))
    surge.ended_at = timezone.now()
    surge.suppression_count = max(surge.suppression_count, count)
    surge.save(update_fields=["ended_at", "suppression_count", "updated_at"])
    log.info(
        "comms.suppression.recovered",
        connection_id=str(surge.connection_id),
        count=count,
        threshold=SURGE_THRESHOLD,
    )
    emit(name=SUPPRESSION_RECOVERED, tenant=tenant, payload=_surge_payload(surge), actor=actor)
    return surge


# --- the management surface: templates, recipients, preferences ------------------
#
# The asymmetry `policies.py` states, in code: **anybody in the tenant may send
# and may keep the contact book; only an owner or an admin changes what the
# product is allowed to say.** Templates and consent are the second kind, and
# every one of these is a verb — `grant_consent`, not a PATCH that sets
# `marketing_consented_at`. That is not style. A column a door can set is a
# column a door can set *back*, and "this person's consent was revoked" is a
# fact with a timestamp, not a field somebody flipped.
#
# **And every verb below that takes a `recipient` asks two questions, not one.**
# `require(...)` answers "may you do this kind of thing here" — it is about the
# verb and the role. `may_be_named(actor, recipient)` answers the one nothing
# used to ask: **could this hat have got hold of this row?** The two are not
# redundant and the second is the one the hierarchy needs. A branch admin is
# privileged, so `channel_preference.update` says yes to them everywhere in the
# tenant; the row they were handed may belong to a sibling branch they hold no
# membership over, and until house rule 26 was adopted here nothing
# between the wire and the write asked about it. The doors happen to resolve
# their ids through `get_recipient`, which scopes — but "our one caller is
# careful" is a property of the caller, and the second caller inherits none of
# it. That is the whole argument for the check standing in the service.
#
# It refuses `NotFound`, never `Forbidden`, everywhere: not-there and not-yours
# are one answer, or the refusal itself tells you somebody else's customer
# exists. Written out once here rather than eight times below, because eight
# copies of a paragraph is eight chances for one of them to drift.


@service
def create_template(
    *,
    tenant: Tenant,
    actor: Actor,
    name: str,
    body: str,
    subject: str = "",
    channel: str = Channel.EMAIL,
    category: str = Category.TRANSACTIONAL,
    context_schema: dict[str, Any] | None = None,
) -> MessageTemplate:
    """Write version 1 of a template. **A name is claimed once.**

    A second `create_template` under a name the tenant already has is a
    `Conflict` rather than a silent second version: the caller either meant
    `revise_template` (and gets told so) or meant a different template (and
    gets to pick a name that is free). Guessing between those two is how a
    product ends up with two templates called `receipt`.
    """
    # **AT THE ROOT, not at the acting hat.** A `MessageTemplate` carries no
    # `organization` column: it is the TENANT's words, resolved by NAME at every
    # door and at every node. Asked at the hat, an administrator of one branch
    # held it — and wrote what the whole tenant says. The shape is
    # `update_tenant_settings`' (`core/services.py`), for the same reason.
    require(actor, "message_template.create", root_organization(tenant=tenant))
    slug = str(name).strip()
    if list_templates(tenant=tenant, actor=actor).filter(name=slug).exists():
        raise Conflict(
            f"This tenant already has a template named {slug!r}. "
            "A change to it is a new version, not a second template."
        )
    template = MessageTemplate(
        tenant=tenant,
        name=slug,
        version=1,
        channel=str(channel).strip().lower(),
        category=str(category).strip().lower(),
        subject=subject,
        body=body,
        context_schema=dict(context_schema or {}),
        is_active=True,
    )
    with as_invalid():
        template.full_clean()
    template.save()
    return template


@service
def revise_template(
    *,
    tenant: Tenant,
    actor: Actor,
    name: str,
    body: str,
    subject: str = "",
    category: str | None = None,
    context_schema: dict[str, Any] | None = None,
) -> MessageTemplate:
    """Publish the next version of a template. **Never an edit in place.**

    A new row at `version + 1`, and the old row is left exactly as it was. That
    is the whole reason `Message` carries `template_name` and `template_version`
    as well as the foreign key: a message sent in March can be read back in
    November as the words that actually went out, which an edited-in-place
    template makes impossible and no amount of careful reviewing gets back.

    The version is computed from the highest row this tenant holds under the
    name — including retired ones — so a number is never reused, and it is read
    inside `@service`'s transaction, which is what stops two concurrent
    revisions both claiming `v3` (the unique constraint is the second wall).

    **The channel does not change across versions.** A template's channel is
    part of what it *is*; an email template that became an SMS template at v2
    would silently re-target every `send()` that names it. Sending on a new
    channel is a new template with a new name.
    """
    # At the root: a revision is the same act as `create` one version on (see it).
    require(actor, "message_template.create", root_organization(tenant=tenant))
    slug = str(name).strip()
    latest = (
        list_templates(tenant=tenant, actor=actor).filter(name=slug).order_by("-version").first()
    )
    if latest is None:
        raise NotFound(f"No template named {slug!r} to revise.")
    revision = MessageTemplate(
        tenant=tenant,
        name=slug,
        version=int(latest.version) + 1,
        channel=latest.channel,
        category=latest.category if category is None else str(category).strip().lower(),
        subject=subject,
        body=body,
        context_schema=dict(latest.context_schema if context_schema is None else context_schema),
        is_active=True,
    )
    with as_invalid():
        revision.full_clean()
    revision.save()
    return revision


@service
def retire_template(*, tenant: Tenant, actor: Actor, template: MessageTemplate) -> MessageTemplate:
    """Take one version out of service. **It stays readable for ever.**

    `is_active` is the only column on a template that ever moves after it is
    written, and this verb is the only thing that moves it — which is why there
    is no `PATCH /templates/{name}/` with an `is_active` field: a flag a door can
    set is a flag a door can set back, and "we stopped sending v2 on the 9th" is
    a decision with an actor and an audit row, not a checkbox.

    What it changes is what a **name** resolves to: `selectors.get_template`
    answers with the highest *active* version, so retiring v2 puts v1 back in
    service. What it does not change is history — every `Message` that used v2
    still points at it, and `GET /templates/?name=<name>` still returns it:
    a template answers to its NAME at every door, and the list is where the
    versions a name is no longer resolving to stay readable).

    Idempotent: retiring a retired version is a no-op rather than a conflict, so
    a client that retried a request it never saw the answer to is not told it
    collided with itself.
    """
    # At the root, and the row is no longer the question: a template names no
    # branch, so passing it asked at the acting hat exactly as passing nothing
    # did — the most careful-looking line on the page, and the same hole.
    require(actor, "message_template.retire", root_organization(tenant=tenant))
    if not template.is_active:
        return template
    template.is_active = False
    template.save(update_fields=["is_active", "updated_at"])
    return template


# --- delivery policies: versioned exactly like the templates they name -------------


@service
def create_policy(
    *,
    tenant: Tenant,
    actor: Actor,
    name: str,
    steps: list[dict[str, Any]],
) -> DeliveryPolicy:
    """Write version 1 of a policy. **A name is claimed once**, like a template's.

    A second `create_policy` under a name the tenant already has is a `Conflict`
    rather than a silent second version: the caller either meant `revise_policy`
    (and gets told so) or meant a different policy (and gets to pick a free
    name). Guessing between those two is how a product ends up with two
    escalations called `oncall`, one of which nobody is using and nobody can
    tell.
    """
    # At the root: a `DeliveryPolicy` carries no `organization` column either,
    # and it decides how hard the whole tenant chases people. See
    # `create_template` for the argument in full.
    require(actor, "delivery_policy.create", root_organization(tenant=tenant))
    slug = str(name).strip()
    if list_policies(tenant=tenant, actor=actor).filter(name=slug).exists():
        raise Conflict(
            f"This tenant already has a policy named {slug!r}. "
            "A change to it is a new version, not a second policy."
        )
    checked = _policy_steps(tenant=tenant, steps=steps, actor=actor)
    policy = DeliveryPolicy(
        tenant=tenant,
        name=slug,
        version=1,
        is_active=True,
        steps=[asdict(step) for step in checked],
    )
    with as_invalid():
        policy.full_clean()
    policy.save()
    return policy


@service
def revise_policy(
    *,
    tenant: Tenant,
    actor: Actor,
    name: str,
    steps: list[dict[str, Any]],
) -> DeliveryPolicy:
    """Publish the next version of a policy. **Never an edit in place.**

    The same shape `revise_template` has, for the same reason and one more. A
    policy is read at the moment a send starts and then **snapshotted into the
    run**, so a revision cannot reach into an escalation already in flight —
    the run finishes the plan it was given. An edit in place would make that
    guarantee unprovable: the row a message says it ran under would no longer
    be the row it ran under, and there would be nothing left to compare against.

    The version is computed from the highest row this tenant holds under the
    name — retired ones included, so a number is never reused — and it is read
    inside `@service`'s transaction, which is what stops two concurrent
    revisions both claiming v3 (the unique constraint is the second wall).
    """
    # At the root: a revision is the same act as `create` one version on.
    require(actor, "delivery_policy.create", root_organization(tenant=tenant))
    slug = str(name).strip()
    latest = (
        list_policies(tenant=tenant, actor=actor).filter(name=slug).order_by("-version").first()
    )
    if latest is None:
        raise NotFound(f"No policy named {slug!r} to revise.")
    checked = _policy_steps(tenant=tenant, steps=steps, actor=actor)
    revision = DeliveryPolicy(
        tenant=tenant,
        name=slug,
        version=int(latest.version) + 1,
        is_active=True,
        steps=[asdict(step) for step in checked],
    )
    with as_invalid():
        revision.full_clean()
    revision.save()
    return revision


@service
def retire_policy(*, tenant: Tenant, actor: Actor, policy: DeliveryPolicy) -> DeliveryPolicy:
    """Take one version out of service. **It stays readable for ever.**

    `is_active` is the only column on a policy that moves after it is written,
    and this verb is the only thing that moves it. What it changes is what a
    **name** resolves to: `selectors.get_policy` answers with the highest active
    version, so retiring v2 puts v1 back in service. What it does not change is
    any run already interpreting v2's snapshot, or any `Message` that recorded
    it — those are history and history does not move.

    Idempotent: retiring a retired version is a no-op rather than a conflict, so
    a client that retried a request it never saw the answer to is not told it
    collided with itself.
    """
    # At the root, and the row is no longer the question — `retire_template`'s
    # sentence, one table over.
    require(actor, "delivery_policy.retire", root_organization(tenant=tenant))
    if not policy.is_active:
        return policy
    policy.is_active = False
    policy.save(update_fields=["is_active", "updated_at"])
    return policy


@service
def create_recipient(
    *,
    tenant: Tenant,
    actor: Actor,
    email: str,
    display_name: str = "",
    phone: str = "",
    chat_handle: str = "",
    user: User | None = None,
) -> Recipient:
    """Add somebody this product can address, in the actor's own branch.

    There is deliberately no `organization=` parameter: the hat the door
    resolved decides where the contact lands, so no caller can write a row into
    a branch it holds no membership over. The unique constraint is per
    organization for the same reason — two branches of a group may each hold
    the same person, and neither can see the other's row.
    """
    require(actor, "recipient.create")
    if actor.org is None:
        raise Invalid({"organization": ["This request resolved no acting organization."]})
    recipient = Recipient(
        tenant=tenant,
        organization=actor.org,
        email=str(email).strip().lower(),
        display_name=str(display_name).strip(),
        phone=str(phone).strip(),
        chat_handle=str(chat_handle).strip(),
        user=user,
    )
    with as_invalid():
        recipient.full_clean()
    recipient.save()
    return recipient


@service
def update_recipient(
    *,
    tenant: Tenant,
    actor: Actor,
    recipient: Recipient,
    email: str | None = None,
    display_name: str | None = None,
    phone: str | None = None,
    chat_handle: str | None = None,
) -> Recipient:
    """Correct a contact's own details. **Four fields, and nothing else.**

    Not on the list, and not by omission: `archived_at` (that is
    `archive_recipient` / `restore_recipient`, verbs, so the audit row says what
    happened rather than which column moved), `organization` (a contact does not
    change branch — that
    is a different operation with different rules) and everything on the
    person's `ChannelPreference` rows, which is the consent surface and is only
    ever reached through the five verbs below.
    """
    # REACHABILITY FIRST, then the capability. `require` is asked AT THE
    # NODE THE ROW NAMES since resolution landed, so asking it first turned a
    # row in a branch this hat holds no membership over into `forbidden` —
    # which tells the caller the row exists. Not-there before not-yours, the
    # order `core.revoke_membership` has always used.
    if not may_be_named(actor, recipient):
        raise NotFound()
    require(actor, "recipient.update", recipient)
    # A closed contact is read-only until it is restored: `archived` (409),
    # naming the restore. Consent is NOT gated here — suppressing an archived
    # contact is still the one way to stop what a send would do.
    require_live(recipient, noun="recipient")
    updated: list[str] = []
    if email is not None:
        recipient.email = str(email).strip().lower()
        updated.append("email")
    if display_name is not None:
        recipient.display_name = str(display_name).strip()
        updated.append("display_name")
    if phone is not None:
        recipient.phone = str(phone).strip()
        updated.append("phone")
    if chat_handle is not None:
        recipient.chat_handle = str(chat_handle).strip()
        updated.append("chat_handle")
    if not updated:
        return recipient
    with as_invalid():
        recipient.full_clean()
    recipient.save(update_fields=[*updated, "updated_at"])
    return recipient


@service
def archive_recipient(*, tenant: Tenant, actor: Actor, recipient: Recipient) -> Recipient:
    """Close a contact. The row stays; it leaves the contact book.

    Not a delete, and it could not be: `Message.recipient` is `PROTECT`, because
    the log of what was said to somebody outlives the decision to stop saying
    it. `selectors.list_recipients` drops archived rows by default and
    `get_recipient` still resolves them, which is what lets a message detail
    name who it went to.

    **It is not a consent decision** and it does not stop `send()`. "Do not
    contact this person" is `suppress_recipient` below — per channel, checked
    inside `send()` where no caller can reach around it. Two walls that could
    disagree would be one wall too many.

    Idempotent: archiving an archived contact keeps the first timestamp and the
    first archiver, and emits nothing, because the honest answer to "when did we
    close this contact" is the earlier one. The row half — the lock, the early
    return, the two columns — is `core.verbs.archive_row`.
    """
    # REACHABILITY FIRST, then the capability. `require` is asked AT THE
    # NODE THE ROW NAMES since resolution landed, so asking it first turned a
    # row in a branch this hat holds no membership over into `forbidden` —
    # which tells the caller the row exists. Not-there before not-yours, the
    # order `core.revoke_membership` has always used.
    if not may_be_named(actor, recipient):
        raise NotFound()
    require(actor, "recipient.archive", recipient)
    recipient, changed = archive_row(tenant=tenant, actor=actor, row=recipient, noun="recipient")
    if changed:
        emit(
            name=RECIPIENT_ARCHIVED,
            tenant=tenant,
            # Excluded by hand until core's `event_payload()` helper lands; an
            # event payload never carries a per-viewer field — `allowed_acts` is
            # what one caller may press, and a subscriber is somebody else.
            payload=RecipientOut.from_orm(recipient).model_dump(
                mode="json", exclude={"allowed_acts"}
            ),
            actor=actor,
        )
    return recipient


@service
def restore_recipient(*, tenant: Tenant, actor: Actor, recipient: Recipient) -> Recipient:
    """Reopen a closed contact. It comes back into the contact book.

    The mirror of `archive_recipient`, and the same press: whoever may close a
    contact may reopen it (`core.policies.may_archive`, asked at the contact's
    node). Idempotent — restoring a live contact answers it unchanged and
    emits nothing — and both archive columns are cleared, because a live
    contact carries neither.

    Consent is untouched either way: a suppression recorded while the contact
    was closed still stands after it is reopened.
    """
    if not may_be_named(actor, recipient):
        raise NotFound()
    require(actor, "recipient.restore", recipient)
    recipient, changed = restore_row(tenant=tenant, actor=actor, row=recipient, noun="recipient")
    if changed:
        emit(
            name=RECIPIENT_RESTORED,
            tenant=tenant,
            # Excluded by hand until core's `event_payload()` helper lands; an
            # event payload never carries a per-viewer field — `allowed_acts` is
            # what one caller may press, and a subscriber is somebody else.
            payload=RecipientOut.from_orm(recipient).model_dump(
                mode="json", exclude={"allowed_acts"}
            ),
            actor=actor,
        )
    return recipient


def _preference_row(
    *, tenant: Tenant, actor: Actor, recipient: Recipient, channel: str
) -> ChannelPreference:
    """This person's preference row for this channel, unsaved if it is new.

    Private, and the five verbs below are its only callers: a preference row is
    never created except by somebody saying something about it, so there is no
    public "create a preference" — a row existing means a decision was recorded,
    and its **absence** is the answer `send()` reads as "transactional yes,
    marketing no".

    A channel this product does not know is refused here: a preference row on a
    channel `Channel` has no member for would be a consent record `send()` can
    never match and therefore never honour.
    """
    slug = str(channel or "").strip().lower()
    if slug not in Channel.values:
        raise Invalid({"channel": [f"{channel!r} is not a channel this product knows."]})
    if actor.org is None:
        raise Invalid({"organization": ["This request resolved no acting organization."]})
    existing = get_preference(
        tenant=tenant, recipient=recipient, channel=slug, org=actor.org, actor=actor
    )
    if existing is not None:
        return existing
    # The row lands in the recipient's own branch rather than the actor's: a
    # group admin recording a dealer's customer's consent must not put that
    # consent somewhere the dealer cannot read it, or `send()` — which reads
    # with the sender's hat — would never see it again.
    return ChannelPreference(
        tenant=tenant,
        organization=recipient.organization,
        recipient=recipient,
        channel=slug,
    )


@service
def grant_consent(
    *, tenant: Tenant, actor: Actor, recipient: Recipient, channel: str = Channel.EMAIL
) -> ChannelPreference:
    """Record that this person said yes to marketing on this channel.

    A timestamp, not a flag: "when did they agree" is what a regulator asks and
    a boolean cannot answer it. Consenting again after a revocation moves
    `marketing_consented_at` forward past the revocation, which is exactly what
    `has_marketing_consent` compares — the later of the two wins, so somebody
    who opts back in is opted back in without any row being erased.
    """
    # REACHABILITY FIRST, then the capability. `require` is asked AT THE
    # NODE THE ROW NAMES since resolution landed, so asking it first turned a
    # row in a branch this hat holds no membership over into `forbidden` —
    # which tells the caller the row exists. Not-there before not-yours, the
    # order `core.revoke_membership` has always used.
    if not may_be_named(actor, recipient):
        raise NotFound()
    require(actor, "channel_preference.update", recipient)
    preference = _preference_row(tenant=tenant, actor=actor, recipient=recipient, channel=channel)
    preference.marketing_consented_at = timezone.now()
    with as_invalid():
        preference.full_clean()
    preference.save()
    return preference


@service
def revoke_consent(
    *, tenant: Tenant, actor: Actor, recipient: Recipient, channel: str = Channel.EMAIL
) -> ChannelPreference:
    """Record that this person has taken marketing consent back.

    The consent timestamp is **not cleared**. Both stay, and
    `has_marketing_consent` reads the later one, because "they agreed in March
    and withdrew in June" is the history a regulator asks for and clearing the
    first would leave the row saying they never agreed at all.

    Revoking where nothing was ever granted writes the row anyway: "we asked and
    they said no" is a fact worth having, and it makes the marketing refusal in
    `send()` an explicit record rather than the default that applies to
    everybody nobody has asked.
    """
    # REACHABILITY FIRST, then the capability. `require` is asked AT THE
    # NODE THE ROW NAMES since resolution landed, so asking it first turned a
    # row in a branch this hat holds no membership over into `forbidden` —
    # which tells the caller the row exists. Not-there before not-yours, the
    # order `core.revoke_membership` has always used.
    if not may_be_named(actor, recipient):
        raise NotFound()
    require(actor, "channel_preference.update", recipient)
    preference = _preference_row(tenant=tenant, actor=actor, recipient=recipient, channel=channel)
    preference.marketing_revoked_at = timezone.now()
    with as_invalid():
        preference.full_clean()
    preference.save()
    return preference


@service
def set_quiet_hours(
    *,
    tenant: Tenant,
    actor: Actor,
    recipient: Recipient,
    channel: str = Channel.EMAIL,
    start: time | None = None,
    end: time | None = None,
    timezone_name: str = "UTC",
) -> ChannelPreference:
    """Set — or clear — the window in which only transactional traffic goes out.

    Both ends or neither: the table holds that as a check constraint, and a
    half-open window is a quiet-hours rule nobody can evaluate. Passing neither
    clears the window, which is how a person turns quiet hours off.

    The timezone belongs to the **person**, not to the server, and it is stored
    beside the window because 22:00 means nothing without one. An unknown name
    is refused here rather than silently falling back: the UTC fallback in
    `ChannelPreference.is_quiet_at` tolerates a bad name for rows already in
    the table; it is not a way to
    write more of them.
    """
    # REACHABILITY FIRST, then the capability. `require` is asked AT THE
    # NODE THE ROW NAMES since resolution landed, so asking it first turned a
    # row in a branch this hat holds no membership over into `forbidden` —
    # which tells the caller the row exists. Not-there before not-yours, the
    # order `core.revoke_membership` has always used.
    if not may_be_named(actor, recipient):
        raise NotFound()
    require(actor, "channel_preference.update", recipient)
    if (start is None) != (end is None):
        raise Invalid(
            {"quiet_hours": ["Quiet hours are a window: give both a start and an end, or neither."]}
        )
    zone = str(timezone_name or "UTC").strip() or "UTC"
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise Invalid({"timezone_name": [f"{zone!r} is not a timezone name."]}) from exc
    preference = _preference_row(tenant=tenant, actor=actor, recipient=recipient, channel=channel)
    preference.quiet_hours_start = start
    preference.quiet_hours_end = end
    preference.quiet_hours_timezone = zone
    with as_invalid():
        preference.full_clean()
    preference.save()
    return preference


@service
# rule-82: writes the consent ledger, never the contact
def suppress_recipient(
    *, tenant: Tenant, actor: Actor, recipient: Recipient, channel: str = Channel.EMAIL
) -> ChannelPreference:
    """Stop everything on this channel — transactional included.

    A hard bounce, a spam complaint, or the person asking to be left alone. It
    is the strongest thing this app can be told and it outranks every other
    answer in `_refusal`, which is why it is a verb of its own rather than a
    stronger flavour of revoking consent: revoking consent is about marketing,
    and this is about the address.

    **Two callers, one door** (ADR comms-8): a human, through the management
    surface, and `record_delivery_status` when the transport reports a bounce —
    inside that status write's own transaction, as the system. There is
    deliberately no separate auto-suppression service and no flag distinguishing
    the two, because it is one fact about one address; `unsuppress_recipient`
    lifts either of them.

    Idempotent: suppressing an already-suppressed channel keeps the first
    timestamp. "When did we stop writing to this address" has one honest answer.
    """
    # REACHABILITY FIRST, then the capability. `require` is asked AT THE
    # NODE THE ROW NAMES since resolution landed, so asking it first turned a
    # row in a branch this hat holds no membership over into `forbidden` —
    # which tells the caller the row exists. Not-there before not-yours, the
    # order `core.revoke_membership` has always used.
    if not may_be_named(actor, recipient):
        raise NotFound()
    require(actor, "channel_preference.update", recipient)
    preference = _preference_row(tenant=tenant, actor=actor, recipient=recipient, channel=channel)
    if preference.suppressed_at is None:
        preference.suppressed_at = timezone.now()
    with as_invalid():
        preference.full_clean()
    preference.save()
    return preference


@service
# rule-82: writes the consent ledger, never the contact
def unsuppress_recipient(
    *, tenant: Tenant, actor: Actor, recipient: Recipient, channel: str = Channel.EMAIL
) -> ChannelPreference:
    """Lift a suppression. **It does not restore marketing consent.**

    The two are separate facts and this touches only one of them: somebody whose
    address was suppressed by a bounce and who never consented to marketing is,
    afterwards, exactly where they started — transactional yes, marketing no.
    A lift that also re-granted consent would be a product opting somebody in on
    their behalf, from a support tool, with a timestamp that says they agreed.
    """
    # REACHABILITY FIRST, then the capability. `require` is asked AT THE
    # NODE THE ROW NAMES since resolution landed, so asking it first turned a
    # row in a branch this hat holds no membership over into `forbidden` —
    # which tells the caller the row exists. Not-there before not-yours, the
    # order `core.revoke_membership` has always used.
    if not may_be_named(actor, recipient):
        raise NotFound()
    require(actor, "channel_preference.update", recipient)
    preference = _preference_row(tenant=tenant, actor=actor, recipient=recipient, channel=channel)
    preference.suppressed_at = None
    with as_invalid():
        preference.full_clean()
    preference.save()
    return preference
