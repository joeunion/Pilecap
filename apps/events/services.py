"""Writes for the event spine. `emit` is the one every other app calls.

The contract from `architecture.md`, in order:

* a service calls `emit(...)` **inside its own transaction**, after the write the
  event describes;
* `emit` writes the `Event` and its `Outbox` row in that same transaction, so a
  rolled-back write leaves no event and promises nobody anything;
* on commit — and only on commit — the dispatch workflow starts, fans out to the
  tenant's `WebhookEndpoint` rows and to the realtime bridge, retries with
  backoff, and dead-letters what it cannot deliver.

**Nothing imports this app except to `emit`**, and nothing subscribes in code:
subscribers are rows (`WebhookEndpoint`) and the socket bridge.

### Two things worth stating out loud

**`emit` is keyword-only, including the name.** House rule 13 — every function
in a `services.py` is `@service`, and `@service` refuses a positional parameter
*at import time* — buys the span, the audit row and the transaction boundary
that make an emit reviewable, and the event's name is not exempt from it:
`emit(name=ORDER_PLACED, tenant=..., payload=...)`. A call written the other way
fails loudly, at import, with a message that says what to do.

`build-contract.md` and `.claude/skills/django-conventions/SKILL.md` are the
places that state this for the rest of the repository. They are **pointed at
here and not quoted**: this paragraph used to carry a copy of what they said,
the copy was wrong for a cycle after they were corrected, and a docstring that
reproduces another file's sentence is a second thing to keep true.

**The workflow is started through `core.bridge`, not through an import.**
`import-linter` holds the platform apps independent of each other, so
`apps.events` may not import `apps.workflows` even though emitting is exactly
what starts a workflow. The workflows app registers what this one needs from its
`AppConfig.ready()`; this app looks it up by name. Same ruling, same mechanism as
`core.mail` (`architecture.md`, "the bridge").
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from typing import Any
from uuid import UUID

from django.core.exceptions import ImproperlyConfigured
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from opentelemetry import trace

from apps.core import bridge, context
from apps.core.actor import Actor, system_actor
from apps.core.authz import is_org_scoped_kind, kind_of_event, require
from apps.core.exceptions import Invalid, as_invalid
from apps.core.log import get_logger
from apps.core.models import Organization, Tenant
from apps.core.service import service
from apps.core.services import root_organization
from apps.core.time import now
from apps.core.types import Swept
from apps.events import selectors
from apps.events.events import ENDPOINT_REGISTERED, check_name, declared_names
from apps.events.models import Delivery, Event, Outbox, WebhookEndpoint
from apps.events.types import DispatchEvent

log = get_logger(__name__)

# What may appear un-redacted in this app's log lines and audit `input`. An
# event's *name* is structural and is the thing you search on; its **payload is
# not** — it is whatever the emitting service put there, which is the customer's
# data. `secret` is nowhere near this list and never will be.
LOG_KEYS: frozenset[str] = frozenset(
    {"name", "status", "url", "code", "attempts", "v", "is_active", "error"}
)

# The workflows, by the name in their `@workflow.defn`. Strings, because the
# worker resolves them by name and because the bridge hands us a starter rather
# than a class.
DISPATCH_WORKFLOW = "DispatchEventWorkflow"
PURGE_WORKFLOW = "PurgeExpiredWorkflow"
RECONCILE_WORKFLOW = "ReconcileOutboxWorkflow"

# How much of a failure message is worth keeping. Enough to see the upstream's
# refusal; not so much that one endpoint's HTML error page becomes the table.
ERROR_LIMIT = 2000

# How much entropy a webhook signing key carries. 32 bytes through
# `secrets.token_urlsafe` is 43 URL-safe characters — the same size
# `apps.accounts` mints an API token at, and comfortably inside the 255
# characters of plaintext the encrypted column validates.
ENDPOINT_SECRET_BYTES = 32

# The encoder the REST door renders every response body with, as far as this
# module is allowed to name it.
#
# The door renders through ninja's `JSONRenderer`, whose `encoder_class` is
# `NinjaJSONEncoder`, which **is** a `DjangoJSONEncoder` plus four `default()`
# cases for objects a ninja response can hold and an event payload cannot: a
# `BaseModel`, a pydantic `Url`, an `IPv4Address`, an `Enum`. Every rule that
# renders a *value* — and the millisecond truncation of an ECMA-262 timestamp is
# the whole of ADR core-8 — is inherited from this class, unchanged.
#
# Naming the subclass here is not available: `apps/core/tests/test_exceptions.py`
# refuses any `ninja` import under a `services.py` — house rule 14's stricter
# in-tree sibling — and a service that imported the door's package would be
# callable from one door of five. So the base is named, and
# `test_the_encoder_renders_exactly_as_the_mounted_api_does` in this app's tests
# holds the two to identical output over every shape a payload carries. The pin
# is in a test module, where importing the door's stack is legal, and it fails
# the day the two diverge rather than the day a subscriber notices.
DOOR_ENCODER: type[json.JSONEncoder] = DjangoJSONEncoder

# An ISO-8601 instant carrying **more precision than the door keeps**.
# `DjangoJSONEncoder` truncates an ECMA-262 timestamp to milliseconds; pydantic's
# `model_dump(mode="json")` — which is what almost every caller of `emit` builds
# its payload with — writes microseconds. Three fractional digits or fewer is
# already exactly what the door writes, so nothing matches and nothing is
# touched; four or more is the divergence and only the divergence.
_SUB_MILLISECOND = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\.\d{4,}(?:[Zz]|[+-]\d{2}:\d{2})?$"
)


def _trace_id() -> str:
    """The current trace, as the 32 hex characters every other table stores.

    Not a service: a two-line pure function, and the same two lines
    `core.service` uses to stamp an `AuditEntry`.
    """
    span_context = trace.get_current_span().get_span_context()
    return format(span_context.trace_id, "032x") if span_context.is_valid else ""


def _handed_back_to_the_encoder(value: Any) -> Any:
    """The payload with over-precise timestamp *strings* turned back into datetimes.

    Not a service: a pure walk over a dict, and half of `_as_the_door_renders`.

    The encoder only gets to render what it is handed, and by the time a payload
    reaches `emit` its datetimes have usually stopped being datetimes: the house
    form is `SomeOut.from_orm(row).model_dump(mode="json")`, and pydantic has
    already written `2026-08-20T12:34:56.123456Z` where the door would write
    `2026-08-20T12:34:56.123Z`. Handing that string to `json.dumps` would leave
    it alone. So the string is parsed back into the instant it names and handed
    to the encoder, which renders it — the truncation rule is never reimplemented
    here, and the day Django changes it this app changes with it.

    Only `_SUB_MILLISECOND` matches, so a string the door would have written
    unchanged is left byte-identical, and an opaque string that merely looks
    date-ish (`"2026-08-20"`, `"2026-08-20T12:34:56Z"`) is never rewritten.
    """
    if isinstance(value, str):
        if _SUB_MILLISECOND.match(value):
            try:
                return datetime.fromisoformat(value)
            except ValueError:  # pragma: no cover - the regex has already agreed
                return value
        return value
    if isinstance(value, dict):
        return {key: _handed_back_to_the_encoder(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_handed_back_to_the_encoder(item) for item in value]
    return value


def _as_the_door_renders(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload as the REST door would have put it on the wire.

    Not a service: one chokepoint, called from `emit` and from nowhere else.

    `architecture.md` promises that a webhook subscriber and a client reading the
    same row are looking at one shape; before this the two agreed about every
    field except the length of a timestamp, template-wide (ADR core-8).
    Round-tripping the payload through `DOOR_ENCODER` is what makes the promise
    literally true rather than nearly true, and it is done **here** rather than at
    every emitting service because the next emitter would forget.

    Inbound events do not come through here. `receivers.verify_and_store` writes
    through `record_event`, and somebody else's webhook body is their bytes, not
    ours to re-render.
    """
    rendered = json.dumps(_handed_back_to_the_encoder(payload), cls=DOOR_ENCODER)
    restored: dict[str, Any] = json.loads(rendered)
    return restored


#: The narrowing key. The one field on a payload that decides which sockets a
#: row reaches, and therefore the one field on a payload that is a *security*
#: field rather than a data field. Named once, here, so that the writer
#: (`_subject_organization`), the invariant that guarantees it is on the shape
#: (house rule 38) and the reader (`apps.realtime.bridge.group_for`) are talking
#: about the same string.
ORG_KEY = "organization_id"


# ADR — THE NARROWING DECISION FAILS CLOSED
#
# `_subject_organization` used to answer `None` three different ways and mean
# three different things by it: "the subject has no organization", "the id names
# somebody else's tree", and "the id is not a UUID". The first is a fact. The
# other two are an UNRESOLVED NARROWING — and `bridge.group_for` reads NULL as
# *tenant-wide*, so an unresolved narrowing broadcast the subject's own payload
# to every socket in the tenant. That is precisely the leak this guards against,
# reached through a bad value rather than through a bad push, and it was
# the one seam in the hierarchy that failed OPEN: `for_tenant(None)`,
# `visible_to(None)` and `list_subtree_org_ids(org=None)` all return empty.
#
# So the branch is taken on the PRESENCE OF THE KEY, never on the success of the
# lookup, and an unresolved narrowing is refused. NULL can therefore only ever
# mean "the subject has no organization"; the reader's semantics are untouched,
# and what changed is that the writer can no longer produce a NULL it did not
# mean. Failing closed at the decision rather than at the reader is deliberate —
# `group_for` is one function reached by one push, and a second sentinel state on
# the wire would be a second thing for every future reader to get right.
#
# The alternatives, and why not:
#
# * STAMP A SENTINEL that `group_for` treats as nobody. Rejected:
#   `Event.organization` is a FK, so the sentinel is a new column and a spine
#   migration, and it puts a third meaning on the wire (`EventOut`,
#   `EventMessage`) that every subscriber and every future door has to learn. It
#   also moves the decision away from the place that has the tenant in hand.
# * RESOLVE THE ORG OFF THE SUBJECT ROW instead of the payload — take a
#   `subject=` on `emit` and read `subject.organization_id` when it is an
#   `OrgScopedModel`. Rejected as the PRIMARY mechanism: right where it applies,
#   but it only fails closed for callers that pass the row, and `emit` is the one
#   signature every app in a product calls. Worth revisiting the day a product
#   wants the payload and the stamp to be allowed to disagree; they cannot today,
#   and that is the stronger property.
# * LOG LOUDLY AND KEEP STAMPING NULL. Rejected: that is the shape house rule 30
#   exists to catch from the other side — a signal with no enforcement. The
#   broadcast still happens, and the log line arrives after the frames do.
# * FALL BACK TO THE ACTOR'S HAT. Rejected outright by ADR realtime-2a: the hat
#   and the row differ exactly when somebody writes downward, which is the
#   ordinary case, and a hat-stamped event is a WRONG branch rather than a wide
#   one — worse, because it survives the fix wearing the fix's clothes.
#
# AMENDED 2026-09-21, SIGNED by the owner: this ADR governs the two
# PROVEN disagreements only. An UNDECIDED noun — one no app's `EVENT_KINDS`
# decides — is no longer refused here at all; the gate refuses it once per noun
# and the socket drops its frames. The paragraph on the function below carries
# the amendment and `architecture.md`'s rule-59 section carries its signature.
#
# The price, stated. `emit` runs inside the emitting service's transaction, so an
# `Invalid` here rolls that write back. The test this replaces
# (`test_a_malformed_organization_id_is_null_rather_than_an_error`) argued the
# opposite — "an emit does not get to raise here" — and that reasoning is what
# produced the fail-open: the alternative to raising is not "nothing happens", it
# is "the subject's row goes to the whole tenant". `Invalid` rather than a bare
# `RuntimeError` because house rule 14 keeps untranslated exceptions below the
# doors. House rule 38 is the static half: it keeps `organization_id` on every
# `Out` schema of an `OrgScopedModel`, so the key is there to be read.
def _kind_if_anybody_decided(name: str) -> tuple[str | None, bool]:
    """`(the kind this event is about, whether anybody decided the noun)`.

    Two answers and not one, because `None` is a DECIDED answer here — "no row
    is behind this event" — and an undecided noun is the absence of a decision.
    Collapsing them is exactly F5's defect from the other side: a `None` kind is
    delivered to every connection in the tenant.

    Separate from its one caller so that the caller stays inside its length
    budget and so the ERROR line has one home. The line is at ERROR and not at
    WARNING deliberately: since the amendment (see the caller) this is the only
    runtime signal that an event is being recorded which nobody will ever be
    told about, and `remedy` names the command that prints the line to paste.
    """
    try:
        return kind_of_event(name), True
    except ImproperlyConfigured as undecided:
        log.error(
            "events.emit.kind_undecided",
            event_name=str(name),
            detail=str(undecided),
            remedy="--explain 59",
        )
        return None, False


def _refuse_a_branch_that_disagrees_with_the_name(*, name: str, payload: dict[str, Any]) -> None:
    """The payload and the event NAME must agree about whether a branch owns this.

    R4's F4 and F5, as the runtime belt house rule 59 ships with. The static
    rule reads emit SITES; this reads the payload that actually arrived, which
    is what catches a body assembled where the scan cannot follow.

    Separate from `_subject_organization` because it answers a different
    question: that one RESOLVES a branch from a key, and this one decides
    whether the key belongs on this event at all.

    **AN UNDECIDED NOUN IS NOT A REFUSAL — the rule-59 amendment, SIGNED by the
    owner 2026-09-21.** `kind_of_event` raises `ImproperlyConfigured` for
    a noun no app decided about, and that raise used to be left to escape. It
    escaped INTO THE EMITTING SERVICE'S TRANSACTION: a product that added an
    event name and forgot the `EVENT_KINDS` line lost the WRITE the event was
    about, and its doors answered 500 — availability, from a missing
    declaration. The consumer measured it on `usage` (six service tests red,
    the write rolled back).

    So the two PROVEN disagreements above stay exactly as they are — they are
    the two things `kind_of_event` can prove — and the undecided case is caught
    here: the write COMMITS, the row is written with the noun undecided (the
    branch stamped from the payload's top-level key exactly as any other event's
    is, NULL when the key is absent, `Invalid` when it is present and does not
    resolve), the dispatch is enqueued, and an ERROR line says so. The tree
    still refuses the noun — in the two places that can refuse it without
    costing a write: the GATE, where rule 59's third class prints one finding per
    undecided noun WITH the `EVENT_KINDS` line to paste (`--explain 59`), and the
    SOCKET, where `consumers._may_read` catches the same refusal per frame and
    DROPS it, so an undecided noun is delivered to nobody. Closed at the reader,
    loud at the gate, and no longer paid for by the writer.
    """
    kind, decided = _kind_if_anybody_decided(name)
    if not decided:
        return
    named = ORG_KEY in payload
    if is_org_scoped_kind(kind) and not named:
        raise Invalid(
            {
                ORG_KEY: [
                    f"{name!r} is about {kind!r}, which is a row one BRANCH of this "
                    f"tenant owns, and this payload does not carry {ORG_KEY!r} at its "
                    "top level. An absent key is stamped NULL, and the fan-out reads "
                    "NULL as 'no branch owns this' — so the subject's own row would "
                    "be pushed to every socket in the tenant while the REST list under "
                    "a sibling hat never shows it. Pass the row's own `Out` dump, "
                    "which carries the key by house rule 38."
                ]
            }
        )
    if kind is None and named:
        raise Invalid(
            {
                ORG_KEY: [
                    "an org-less event cannot name a branch. "
                    f"{name!r} is about nothing a membership could hold a read on — "
                    "its noun is mapped to None in the declaring app's events.py — and "
                    "the socket door delivers a None-kind frame to every connection in "
                    "the tenant WITHOUT consulting the read set, so a branch on this "
                    "body would be the widest delivery this product has, aimed at rows "
                    "nobody may read. Omit the key."
                ]
            }
        )


def _subject_organization(
    *, tenant: Tenant, name: str, payload: dict[str, Any]
) -> Organization | None:
    """Which part of the tenant the row this event is about belongs to.

    Not a service: one scoped read, called from `emit` and from nowhere else.

    **The row's organization, never the actor's hat** (ADR realtime-2a). The
    payload is the subject's own `Out` schema and every org-scoped model's `Out`
    carries `organization_id` (house rule 38), so the branch a write landed in is
    already on the wire and a manager writing into a child branch stamps the
    branch. `OrgScopedModel.organization` is a non-nullable FK, so:

    * key absent → the subject is not org-scoped. NULL, tenant-wide, exactly
      what those events did before this column existed.
    * key present and resolving inside this tenant → that branch.
    * key present and **not** resolving — empty, malformed, or a row in another
      tenant's tree — → **`Invalid`, and the emit does not happen.**

    The comment above this function carries why, and the alternatives rejected.

    Inbound events never reach here: `receivers.verify_and_store` writes through
    `record_event`, which takes `organization` and derives nothing, because an
    `organization_id` in somebody else's webhook body names their idea of a row.
    """
    _refuse_a_branch_that_disagrees_with_the_name(name=name, payload=payload)
    if ORG_KEY not in payload:
        return None
    raw = payload[ORG_KEY]
    organization = None
    if raw:
        try:
            organization_id = UUID(str(raw))
        except (AttributeError, TypeError, ValueError):
            organization = None
        else:
            organization = (
                Organization.objects.for_tenant(tenant).filter(pk=organization_id).first()
            )
    if organization is None:
        raise Invalid(
            {
                ORG_KEY: [
                    f"{raw!r} does not name an organization in this tenant, so the branch "
                    "this event belongs to cannot be resolved. The event is refused rather "
                    "than stamped tenant-wide: a NULL organization means 'no branch owns "
                    "this', and the fan-out would read it as 'send it to every socket in "
                    "the tenant'. Omit the key for a genuinely org-less subject."
                ]
            }
        )
    return organization


# --- Emitting ----------------------------------------------------------------


@service
def record_event(
    *,
    tenant: Tenant,
    name: str,
    payload: dict[str, Any],
    v: int = 1,
    organization: Organization | None = None,
    actor: Actor,
    correlation_id: str = "",
    causation_id: str = "",
    trace_id: str = "",
    occurred_at: datetime | None = None,
) -> Event:
    """Write the event and its outbox row. **No name validation, no dispatch.**

    The raw writer, and it is separate from `emit` for one reason: an *inbound*
    webhook (`receivers.verify_and_store`) is an event too, and its name belongs
    to whoever sent it — `stripe.invoice.paid` is declared in no app here and
    must not be refused for that. `emit` is the outbound half and validates;
    this is the half both share.

    `organization` is taken and never derived, for that same reason: the
    subject of an inbound event is somebody else's row, and reading an
    `organization_id` out of their body would stamp our tree from their data.
    `emit` derives it; this writes what it is handed, and NULL means tenant-wide.

    # authz: recording an event is not a separate permission. The service that
    # called `emit` already authorised the write this event describes, and an
    # inbound event is authorised by its signature rather than by a role.
    """
    event = Event(
        tenant=tenant,
        name=name,
        v=v,
        payload=payload,
        organization=organization,
        # Required since ADR core-22's L1 ruling, so the three columns are
        # always answered: a `system` event says `system` rather than leaving
        # the kind blank and letting a reader guess whether anybody was asked.
        actor_user_id=actor.user_id,
        actor_token_id=actor.token_id,
        actor_kind=actor.kind,
        correlation_id=correlation_id,
        causation_id=causation_id,
        trace_id=trace_id,
        occurred_at=occurred_at or now(),
    )
    with as_invalid():
        event.full_clean()
    event.save()
    Outbox(event=event).save()
    return event


# door: the spine primitive every other app's service calls INSIDE its own
# transaction, after the write the event describes. A door onto `emit` would be
# a door onto somebody else's write — a caller who could name a name and a
# payload could publish a `billing.invoice.paid` nobody billed, signed with the
# tenant's own key, to every subscriber it has. The doors onto this app are the
# subscription surface (`api.py`) and the replay of what was already emitted;
# what may be emitted stays where the write is (house rule 42).
@service
def emit(
    *,
    name: str,
    tenant: Tenant,
    payload: dict[str, Any],
    actor: Actor,
    causation_id: str | None = None,
    v: int = 1,
) -> Event:
    """Say that something happened. Called from inside a service's transaction.

    The name must be declared in the emitting app's `events.py` (`check_name`).
    The correlation pair comes from the bound context and is never minted here —
    house rule 20: an id minted below a door restarts the chain it exists to
    join. A caller that knows the immediate parent (an activity handing on work)
    passes `causation_id` and that wins.

    The payload lands as the REST door would render it — `_as_the_door_renders`.

    The event is stamped with the **subject row's** organization when the
    subject has one (`_subject_organization`), so the fan-out can reach the
    branch the write landed in rather than the whole tenant. Nothing is asked of
    the caller: the branch is already on the payload. What *is* asked is that a
    narrowing key on the payload be a real branch of this tenant — a payload
    carrying an `organization_id` that does not resolve is **refused**, because
    the alternative is a tenant-wide broadcast of the subject's own row
    (`_subject_organization` carries the reasoning and the rejected
    alternatives).

    The dispatch workflow is registered on `transaction.on_commit` by
    `enqueue_dispatch`, so a service that rolls back has emitted nothing and
    started nothing.

    # authz: an event is the product's own record of a write that has already
    # been authorised by the service making it; there is no separate permission
    # to say that something happened.
    """
    check_name(name)
    chain = context.child_of_current()
    event = record_event(
        tenant=tenant,
        name=name,
        payload=_as_the_door_renders(payload if "v" in payload else {"v": v, **payload}),
        v=v,
        organization=_subject_organization(tenant=tenant, name=name, payload=payload),
        actor=actor,
        correlation_id=str(chain["correlation_id"] or ""),
        causation_id=str(causation_id or chain["causation_id"] or ""),
        trace_id=_trace_id(),
    )
    enqueue_dispatch(tenant=tenant, event_id=event.pk)
    return event


@service
def enqueue_dispatch(*, tenant: Tenant, event_id: UUID, resume: bool = False) -> Outbox:
    """Put an event's outbox row in the queue and start its dispatch on commit.

    The first dispatch, every replay and every relay sweep come through here,
    which is what makes `replay_events` and `ReconcileOutboxWorkflow`
    re-enqueues rather than two more code paths to the same fan-out.

    The event is read through the scoped selector rather than taken as an
    object, so an id from a payload or a command line cannot reach into another
    tenant's events (it is a `NotFound` either way, which tells the caller
    nothing about whether the row exists).

    The workflow id is deterministic (house rule 18) and carries the attempt:
    `<tenant>:events:event:<event id>` for the first dispatch and
    `…:<event id>.<attempt>` for each replay — deterministic enough that a
    retried service starts one run, distinct enough that a deliberate replay is
    not refused by the `WorkflowRun` row the first one left.

    **`resume=True` is the relay's ask, and it is a different question** (ADR
    events-3). A replay is a human saying "send it again" — a new attempt, and
    it must not be refused by the run the last one left. A resume is the relay
    saying "that start may never have reached Temporal at all", and the honest
    answer is to ask for the *same* run rather than to invent a second one. So
    it counts no attempt and the id is unchanged, which hands the idempotency to
    the two places that already own it: `record_run` returns the visibility row
    that id has, and `_start_recorded` swallows `WorkflowAlreadyStartedError`.
    A resume is therefore a **heal** when the execution is missing and a
    **no-op** when it is alive — never a second delivery. A run that has already
    *finished* is neither, and `record_run` raises `Conflict`: that row is
    `replay_events`' business, and the relay counts it rather than deciding for
    a human.

    # authz: dispatch is machine work. It is reached from `emit` (authorised
    # above), from the relay's activity and from the shell command, whose actor
    # is the system.
    """
    event = selectors.get_event(tenant=tenant, event_id=event_id, actor=system_actor(tenant))
    outbox = Outbox.objects.select_for_update().get(event=event)
    if not resume:
        outbox.attempts += 1
    outbox.status = Outbox.Status.PENDING
    outbox.next_attempt_at = now()
    outbox.save(update_fields=["attempts", "status", "next_attempt_at", "updated_at"])

    key = str(event.pk) if outbox.attempts <= 1 else f"{event.pk}.{outbox.attempts}"
    start = bridge.get(bridge.START_WORKFLOW_ON_COMMIT)
    build_id = bridge.get(bridge.WORKFLOW_ID)
    start(
        workflow=DISPATCH_WORKFLOW,
        arg=DispatchEvent(event_id=str(event.pk)),
        tenant=tenant,
        id=build_id(tenant=tenant, app="events", noun="event", key=key),
    )
    return outbox


@service
def close_outbox(*, tenant: Tenant, event_id: UUID, status: str, error: str = "") -> Outbox:
    """Move an outbox row to its terminal state. Idempotent by construction.

    # authz: called only by the dispatch workflow's activity, as the system.
    """
    event = selectors.get_event(tenant=tenant, event_id=event_id, actor=system_actor(tenant))
    outbox = Outbox.objects.get(event=event)
    outbox.status = status
    outbox.last_error = error[:ERROR_LIMIT]
    if status == Outbox.Status.DISPATCHED:
        outbox.dispatched_at = now()
    outbox.next_attempt_at = None
    outbox.save(
        update_fields=["status", "last_error", "dispatched_at", "next_attempt_at", "updated_at"]
    )
    return outbox


# --- Subscribers -------------------------------------------------------------


def _new_endpoint_secret() -> str:
    """A fresh signing key. Not a service: one call to the standard library.

    `token_urlsafe(32)` is 32 bytes of `secrets`' CSPRNG rendered as 43
    URL-safe characters — well inside the 255-character plaintext bound the
    encrypted column validates, and long enough that guessing it is not a
    strategy. The same shape `apps.accounts` mints an API token with, for the
    same reason.
    """
    return secrets.token_urlsafe(ENDPOINT_SECRET_BYTES)


def _declared(event_names: list[str] | None) -> list[str]:
    """The subscription list, refused unless every name is one an app declares.

    Not a service: the shared first line of registering and updating an
    endpoint. Empty stays empty, and empty means **every** event.

    The population is `events.declared_names()` — the same registry `emit`
    validates an outbound name against and the same one the catalogue door
    serves. So a subscriber cannot ask for `orders.order.creted` and then spend
    a fortnight wondering why nothing arrives: the typo is refused at the
    moment it is written, naming the field, and the catalogue is where the real
    names are.
    """
    names = list(event_names or [])
    if not names:
        return []
    declared = {name for app_names in declared_names().values() for name in app_names}
    unknown = [name for name in names if name not in declared]
    if unknown:
        raise Invalid(
            {
                "event_names": [
                    f"No installed app declares {name!r} — see GET /api/v1/event-types/."
                    for name in unknown
                ]
            }
        )
    return names


@service
def register_endpoint(
    *,
    tenant: Tenant,
    actor: Actor,
    url: str,
    secret: str = "",
    event_names: list[str] | None = None,
    description: str = "",
) -> WebhookEndpoint:
    """Add a place a tenant's events are delivered to.

    `event_names` empty means every event — the honest default for "tell me what
    happens here". A name no installed app declares is refused: a subscription
    to an event that does not exist is a subscription that silently never fires,
    and the catalogue the door serves is the same population this checks
    against.

    **The secret is minted here when the caller does not bring one**, and the
    returned row is the one moment its plaintext exists outside the encrypted
    column. The door reads `endpoint.secret` off what this returns and answers
    it exactly once; every read shape in `schemas.py` has no field for it, so
    there is nowhere for it to appear again. `secret=` stays in the signature
    for the callers who genuinely have one already — the admin form, an import
    from a system that issued the key — and those are the only two.
    """
    require(actor, "endpoint.create", root_organization(tenant=tenant))
    endpoint = WebhookEndpoint(
        tenant=tenant,
        url=url.strip(),
        secret=secret or _new_endpoint_secret(),
        event_names=_declared(event_names),
        description=description,
    )
    with as_invalid():
        endpoint.full_clean()
    endpoint.save()
    emit(
        name=ENDPOINT_REGISTERED,
        tenant=tenant,
        payload={"endpoint_id": str(endpoint.pk), "url": endpoint.url},
        actor=actor,
    )
    return endpoint


@service
def update_endpoint(
    *,
    tenant: Tenant,
    actor: Actor,
    endpoint: WebhookEndpoint,
    url: str | None = None,
    event_names: list[str] | None = None,
    description: str | None = None,
) -> WebhookEndpoint:
    """Change an endpoint's address, subscription or label. Omitted fields stay.

    Three fields and no fourth. `is_active` is moved by `deactivate_endpoint`
    and `resume_endpoint`, which are verbs a reader can find in the audit trail;
    the signing key is moved by `issue_endpoint_secret`, which is the only thing
    that ever writes it. A settable column would be a way to do either by
    accident, and neither belongs in a PATCH body.
    """
    require(actor, "endpoint.update", root_organization(tenant=tenant))
    if url is not None:
        endpoint.url = url.strip()
    if event_names is not None:
        endpoint.event_names = _declared(event_names)
    if description is not None:
        endpoint.description = description
    with as_invalid():
        endpoint.full_clean()
    endpoint.save(update_fields=["url", "event_names", "description", "updated_at"])
    return endpoint


@service
def issue_endpoint_secret(
    *, tenant: Tenant, actor: Actor, endpoint: WebhookEndpoint
) -> WebhookEndpoint:
    """Mint a new signing key for an endpoint. The old one stops verifying at once.

    Rotation is a **replacement, not an addition**: there is no overlap window
    and no second live key, because the endpoint row holds one `secret` and the
    delivery activity signs with whatever that row carries. So the next delivery
    after this call is signed with the new key and the old key's signatures stop
    verifying — which is what a rotation is *for* when the reason for rotating is
    that the old key is somewhere it should not be. A subscriber that needs a
    seam registers a second endpoint, cuts over, and pauses the first.

    The plaintext is on the row this returns and nowhere else. There is no
    service, selector, schema or door that reads it back afterwards.
    """
    require(actor, "endpoint.issue_secret", root_organization(tenant=tenant))
    endpoint.secret = _new_endpoint_secret()
    endpoint.save(update_fields=["secret", "updated_at"])
    return endpoint


@service
def deactivate_endpoint(
    *, tenant: Tenant, actor: Actor, endpoint: WebhookEndpoint
) -> WebhookEndpoint:
    """Stop delivering to an endpoint, without losing the record of what was."""
    require(actor, "endpoint.deactivate", root_organization(tenant=tenant))
    endpoint.is_active = False
    endpoint.save(update_fields=["is_active", "updated_at"])
    return endpoint


@service
def resume_endpoint(*, tenant: Tenant, actor: Actor, endpoint: WebhookEndpoint) -> WebhookEndpoint:
    """Start delivering to a paused endpoint again — from now on, not from then.

    A pause is not a queue. Events that happened while the endpoint was inactive
    were fanned out to the endpoints that *were* active, and the paused one is
    simply not among the targets that dispatch loaded (`selectors.endpoints_for`
    reads the active ones). Resuming does not replay them; `POST
    /dead-letters/{id}/replay/` is where a specific missed delivery is sent
    again, and it is a deliberate act with a row to point at.
    """
    require(actor, "endpoint.resume", root_organization(tenant=tenant))
    endpoint.is_active = True
    endpoint.save(update_fields=["is_active", "updated_at"])
    return endpoint


# --- Deliveries --------------------------------------------------------------


@service
def record_delivery_attempt(
    *,
    tenant: Tenant,
    endpoint_id: UUID,
    event_id: UUID,
    status: str,
    code: int | None = None,
    error: str = "",
) -> Delivery:
    """Write what one attempt at one delivery did.

    `get_or_create` on (endpoint, event) is what makes the delivery activity
    idempotent: Temporal runs an activity *at least* once, so a retry has to
    find the row it wrote last time rather than write a second one. Both ids are
    resolved through the scoped selectors, so an activity payload cannot name
    another tenant's endpoint.

    # authz: called only by the dispatch workflow's activities, as the system.
    """
    endpoint = selectors.get_endpoint(
        tenant=tenant, endpoint_id=endpoint_id, actor=system_actor(tenant)
    )
    event = selectors.get_event(tenant=tenant, event_id=event_id, actor=system_actor(tenant))
    delivery = _delivery_for(endpoint=endpoint, event=event)
    delivery.attempts += 1
    delivery.status = status
    delivery.last_code = code
    delivery.last_error = error[:ERROR_LIMIT]
    if status == Delivery.Status.DELIVERED:
        delivery.delivered_at = now()
    delivery.save(
        update_fields=[
            "attempts",
            "status",
            "last_code",
            "last_error",
            "delivered_at",
            "updated_at",
        ]
    )
    return delivery


@service
def dead_letter_delivery(
    *,
    tenant: Tenant,
    endpoint_id: UUID,
    event_id: UUID,
    error: str = "",
) -> Delivery:
    """Park a delivery that spent every retry.

    Dead-lettering is a fact an operator has to find without reading logs, so it
    is a column (`dead_lettered_at`) and an index.

    **It does not overwrite what the subscriber's server said** (N193a). Giving
    up is our decision, not their answer, and `last_code`/`last_error` are one
    pair describing one attempt — the final one — which is exactly what `GET
    /dead-letters/` promises them to be. Writing the give-up reason over
    `last_error` left the row saying `last_code 500` beside `last_error
    "Activity task failed"`: two fields about the same attempt, disagreeing,
    and only one of them true. So the recorded answer stays, and the reason is
    written only when the row has none of its own — a delivery that was parked
    before any attempt was ever recorded (the activity died before it reached
    `record_delivery_attempt`) would otherwise say nothing at all.

    # authz: called only by the dispatch workflow, as the system.
    """
    endpoint = selectors.get_endpoint(
        tenant=tenant, endpoint_id=endpoint_id, actor=system_actor(tenant)
    )
    event = selectors.get_event(tenant=tenant, event_id=event_id, actor=system_actor(tenant))
    delivery = _delivery_for(endpoint=endpoint, event=event)
    delivery.status = Delivery.Status.DEAD
    delivery.dead_lettered_at = now()
    written = ["status", "dead_lettered_at", "updated_at"]
    if error and not delivery.last_error:
        delivery.last_error = error[:ERROR_LIMIT]
        written.append("last_error")
    delivery.save(update_fields=written)
    return delivery


def _delivery_for(*, endpoint: WebhookEndpoint, event: Event) -> Delivery:
    """The delivery row for this pair, claimed if it is not there yet.

    Not a service: the shared first line of the two above, which are.
    """
    delivery, _created = Delivery.objects.get_or_create(
        endpoint=endpoint,
        event=event,
        defaults={
            "correlation_id": event.correlation_id,
            "causation_id": event.causation_id,
            "trace_id": event.trace_id,
        },
    )
    return delivery


@service
def enqueue_replay(*, tenant: Tenant, actor: Actor, delivery: Delivery) -> Delivery:
    """Send a dead-lettered delivery's event again. The one door onto a replay.

    A dead letter is a delivery that spent every retry the dispatch policy
    allowed, and there is nothing automatic left to try — so somebody has to
    decide, and this is where they decide it. `enqueue_dispatch` does the work
    (ADR events-3's machinery, the same path `manage.py replay_events` walks):
    the outbox row's attempt counter moves, which makes the replay's workflow id
    a new one, so the run the first attempt left behind does not refuse this one.

    **A replay re-runs the whole event's fan-out, not one delivery.** Every
    active endpoint that asked for this event's name is delivered to again,
    including any that succeeded the first time — which is why a subscriber is
    asked to be idempotent on `X-Event-Id`, and why the delivery row is unique
    on (endpoint, event) so a second attempt updates one row rather than writing
    a second. Narrowing a replay to one endpoint would be a second dispatch
    workflow, and the ADR rejected it: the resume path already exists.

    The lineage is on the row. `attempts` counts every HTTP attempt this pair
    has had across every dispatch, and `dead_lettered_at` stays where it was, so
    "this one gave up and was then sent again" is two columns rather than a log
    search.
    """
    require(actor, "delivery.replay", root_organization(tenant=tenant))
    if delivery.dead_lettered_at is None:
        raise Invalid(
            {
                "delivery": [
                    "This delivery has not been dead-lettered; there is nothing to replay. "
                    "A delivery that is still pending is still being retried."
                ]
            }
        )
    enqueue_dispatch(tenant=tenant, event_id=delivery.event_id)
    return delivery


# --- Housekeeping ------------------------------------------------------------


@service
def purge_dispatched_outbox(*, before: datetime) -> int:
    """Drop outbox rows dispatched before `before`. Returns how many went.

    Only `dispatched` rows: a `failed` one is the record of something that never
    reached its subscriber, and deleting it would be deleting the finding.

    # authz: deployment housekeeping, run by a schedule as the system. It is
    # scoped by age rather than by tenant and touches no tenant-owned row.
    """
    deleted, _ = Outbox.objects.filter(
        status=Outbox.Status.DISPATCHED, dispatched_at__lt=before
    ).delete()
    return int(deleted)


@service
def purge_deliveries(*, before: datetime, tenant: Tenant | None) -> Swept:
    """Drop deliveries that reached a **final state** before `before`. How many went.

    **What it returns is a `Swept`, not a bare count** (ADR core-22, L6). The
    number is unchanged; what the typed result adds is the POPULATION — the
    swept model's label, which `core.service._object_of` reads off
    `audit_object` and files as `object_type` with a NULL `object_id`. A sweep
    acts on a population and not on an object, and a row that named one
    arbitrary victim out of nine hundred would read as a single deletion
    somebody could go and look up.

    `Delivery.lifecycle` is the declaration this closes (ADR core-13): a table
    shaped for a sweeper with no sweeper is the poller that was never built, and
    the declaration and this function land in the same commit on purpose.

    **Final means finished, and only two of the four statuses are.** A
    `delivered` row says the subscriber took it; a `dead` row says we gave up
    saying so. Both answer "what became of this webhook", and ninety days later
    (ratified) nobody asks. A `pending` row is a promise the dispatch is
    still keeping and a `failed` row is one it is still retrying — deleting
    either would be deleting work the relay still owes, which is the failure
    this filter exists to *not* commit. That is why the window is measured from
    `delivered_at` / `dead_lettered_at` and never from `created_at`: an attempt
    that has been failing for a hundred days is old and is not finished.

    **No `select_for_update`, deliberately.** These rows are terminal — nothing
    in the tree writes a `delivered` or `dead` delivery again — so there is no
    writer to race, and a lock here would only queue the sweep behind live
    dispatches. One statement rather than a batched loop for the same reason
    `purge_dispatched_outbox` is one: `@service` opens a single
    `transaction.atomic()`, so a loop inside it holds exactly the same locks for
    exactly as long while looking like it does not.

    `tenant` is an **audit-population selector, never a filter** — the same
    shape and the same reasoning as `core.services.redact_invitations`. The
    sweep is deployment-wide by construction (`Delivery` is a `BaseModel`; the
    tenant is a join away on the event), so it is called with nothing and the
    row lands in the platform's ledger, readable through
    `AuditEntry.objects.for_platform()` and `manage.py audit_tail --platform`.

    # authz: deployment housekeeping, run by a schedule as the system. It is
    # scoped by age and by terminal status rather than by tenant, and no actor
    # asked for it — there is nobody whose reach could bound it.
    """
    deleted, _ = Delivery.objects.filter(
        Q(status=Delivery.Status.DELIVERED, delivered_at__lt=before)
        | Q(status=Delivery.Status.DEAD, dead_lettered_at__lt=before)
    ).delete()
    return Swept(label=Delivery._meta.label, count=int(deleted))
