"""Where the spine touches the world: the database, and somebody else's server.

Everything non-deterministic is here and nowhere else, and every activity calls
a service rather than a model. `ACTIVITIES` is what the worker discovers.

**Plain `def`, like every other activity in this repository** (see
`apps/workflows/activities.py`): the ORM is synchronous and the worker runs
activities in a thread pool, so a sync activity is a sync query on a thread
where one belongs rather than an `async def` that wraps one to hand it back to a
thread anyway. Each closes stale connections at both ends, because out here
there is no request cycle to do it.

**Idempotency** is the property Temporal demands, and every activity here has
it: the delivery row is claimed by `get_or_create` on (endpoint, event), so the
same attempt twice updates one row; closing an outbox row writes the same
terminal state; the purge is a filter on age. The periodic machinery this module
**declares** has the property too, in both directions: creating a schedule twice
updates rather than duplicates, and the legacy id it deletes is deleted again
without complaint when it is already gone. It only declares — whether those
declarations become durable Temporal Schedules or runs a live worker starts on a
timer is `apps.workflows.client`'s decision, taken from the deployment's
lifetime class (ADR platform-lifecycle-1).

**The schedule ids are per task queue** (`purge_schedule_id`,
`purge_workflow_id`; ADR events-2). A schedule id is global to the Temporal
namespace, so a constant one made every worker's startup a silent fight over
where the purge runs.

**Who the work is for** arrives on the workflow's Temporal headers and is
restored through `core.bridge` — `apps.events` may not import `apps.workflows`
(`import-linter` holds the platform apps independent), and the tenant must not
be an activity argument, because an argument is something a caller could get
wrong and name somebody else's tenant with.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any, Protocol
from uuid import UUID

import httpx
from django.conf import settings
from django.db import close_old_connections
from opentelemetry import trace
from temporalio import activity
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)
from temporalio.exceptions import ApplicationError

from apps.core import bridge
from apps.core.actor import system_actor
from apps.core.exceptions import DomainError, NotFound
from apps.core.idempotency import purge_expired
from apps.core.log import get_logger
from apps.core.models import Tenant
from apps.core.schedules import ScheduleDeclaration
from apps.core.time import now
from apps.events import schemas, selectors, services
from apps.events.models import Delivery, Outbox
from apps.events.types import (
    CloseOutbox,
    DeadLetter,
    DeliverWebhook,
    DeliveryOutcome,
    DeliveryTarget,
    DispatchEvent,
    IndexSearch,
    LoadedTargets,
    PurgeExpired,
    PurgeOutcome,
    PushRealtime,
    ReconcileOutbox,
    ReconcileOutcome,
)

log = get_logger("apps.events.activities")

# How long one POST to a subscriber may take. Short, and deliberately shorter
# than the activity's own `start_to_close` timeout, so a hung socket is this
# module's refusal rather than Temporal's — the difference is a delivery row
# that says what happened.
DELIVERY_TIMEOUT_SECONDS = 10.0

# The signature header's shape. Prefixed with the algorithm, so the day this
# repository adds a second one there is somewhere for it to go and old
# subscribers keep working.
SIGNATURE_PREFIX = "sha256="

# The second scheme's header, sent alongside `X-Signature` and never instead of
# it. v1 signs the body; v2 signs a timestamp *and* the body, which is what lets
# a subscriber refuse a delivery that was captured and sent again later. Both
# go out on every delivery.
#
# **This module does not perform the contraction.** `X-Signature` is dropped — and this
# becomes the only header — when the first product's subscribers have all
# migrated to v2. That is a fact about somebody else's integrations, learned by
# asking them, not something this repository can observe; a template that
# dropped v1 on a date would break strangers on a schedule. Whoever takes the
# contraction removes the v1 header here, the v1 half of the contract prose in
# `api.py`, and the v1 half of the receiver in `tests/test_signed_delivery.py`.
SIGNATURE_V2_HEADER = "X-Signature-V2"

# The housekeeping schedule: daily, never overlapping, and skipping rather than
# queueing a missed run — an hour late is fine and two purges at once is not.
#
# **Both ids are namespaced by task queue**, and that is not cosmetic. A
# schedule id is global to the Temporal namespace, so while these were the two
# constants `events-purge-expired` and `system:events:purge:expired` every
# worker that started re-pointed the *one* schedule at its own queue — and on a
# laptop running five worktrees against one dev server, the last worker to start
# silently hijacked everybody else's purge onto a queue that was about to go
# away, as observed live. Suffixed, each
# deployment — and each worktree — owns its own schedule and leaves the others
# alone. ADR events-2.
PURGE_SCHEDULE_PREFIX = "events-purge-expired"
PURGE_WORKFLOW_PREFIX = "system:events:purge"

#: The un-suffixed schedule id this app created before ADR events-2. Any server
#: that has run an older worker still holds one, pointed at whichever queue
#: started last; the engine deletes it, in either lifetime class. Not a migration — a
#: schedule lives in Temporal, not in the database, so the code that creates it
#: is the only thing that can clean it up.
LEGACY_PURGE_SCHEDULE_ID = PURGE_SCHEDULE_PREFIX

PURGE_EVERY = timedelta(hours=24)

# The relay's two numbers (ADR events-3).
#
# **`OUTBOX_GRACE`** is how far past its `next_attempt_at` a `pending` row must
# be before the relay treats it as stranded rather than as in flight. It is
# tuned for *recovery latency* and not for the dispatch's own deadline, and it
# can be, because a resume against a run that is genuinely alive is a no-op:
# `enqueue_dispatch(resume=True)` asks again under the id the first start
# claimed, and Temporal answers `WorkflowAlreadyStartedError`, which
# `_start_recorded` swallows. So the grace only has to clear the ordinary
# commit-to-dial latency, which is milliseconds.
#
# **`RECONCILE_EVERY`** is the sweep cadence. Together they bound the staleness
# a strand can reach — one interval plus the grace — and they do not eliminate
# it; the trigger for a Temporal-native per-row timer is in ADR events-3.
#
# Module constants rather than settings, like `PURGE_EVERY` and
# `DELIVERY_TIMEOUT_SECONDS` beside them: a deployment does not tune the shape
# of its own recovery, and `EVENTS_OUTBOX_RETENTION_DAYS` is a setting because
# retention is a data-policy decision that a customer contract can move.
OUTBOX_GRACE = timedelta(minutes=5)
RECONCILE_EVERY = timedelta(minutes=5)

# **`RECONCILE_BATCH`** is the drain's ceiling: how many stranded rows one
# execution of the activity resumes before it hands the decision back to the
# workflow (measured, `quality/perf-ledgers-measurement.md`). Until this
# constant existed the activity walked the whole pending population at nine
# statements a row — 180,000 statements in one execution at the declared 20,000
# pending — and the failure mode was not a runaway but a starvation: the
# activity's `start_to_close_timeout` fires, Temporal retries from the top, and
# a sweep that always re-drains the head never reaches the oldest promises,
# which are exactly the ones the oldest-first order was chosen to serve.
#
# 500 is picked from the measured per-row cost and nothing else: 500 x 9 is
# ~4,500 statements and 500 Temporal starts, which is minutes of headroom under
# `RECONCILE_TIMEOUT` and small enough that a timeout costs one batch rather
# than a sweep. The rows a batch does resume are durably resumed — the workflow
# holds the count in its history — so a retry re-does one batch, not the world.
RECONCILE_BATCH = 500

# **`RECONCILE_MAX_FAULTS`** is where per-row isolation stops and Temporal's
# retry starts. A row that the relay cannot
# resume falls into one of two populations, and they want opposite handling:
#
# * a **domain refusal** (`core.exceptions.DomainError` — `Conflict` from a run
#   that has already finished, `NotFound` from an event the purge took) is the
#   service's own decision about that row. No retry will change it, so the batch
#   counts it, names it in the log and steps past it;
# * anything **else** is a fault whose cause the relay does not know — a lock
#   timeout on `select_for_update`, a broken connection, an error out of the
#   on-commit Temporal start. One of those is a poison row and the sweep must
#   get past it; a hundred of them in one batch is not a row problem at all, it
#   is the platform, and the right instrument for that is the activity failing
#   so Temporal retries the whole batch in seconds rather than the next
#   scheduled sweep discovering it in five minutes.
#
# So faults are isolated up to this ceiling and escalate past it. The number is
# small on purpose: a genuine poison row is rare and arrives one at a time,
# while a systemic fault arrives on every row in the batch.
RECONCILE_MAX_FAULTS = 5

# The relay's schedule, namespaced by task queue for the reason ADR events-2
# gives above: a schedule id is global to the Temporal namespace, so a constant
# one would make every worker's startup a fight over where the sweep runs. There
# is no legacy un-suffixed id to drop here — this schedule has never existed
# under one.
RECONCILE_OUTBOX_SCHEDULE_PREFIX = "events-reconcile-outbox"
RECONCILE_OUTBOX_WORKFLOW_PREFIX = "system:events:reconcile"


def purge_schedule_id(task_queue: str) -> str:
    """The schedule id for one deployment's purge. One per task queue."""
    return f"{PURGE_SCHEDULE_PREFIX}:{task_queue}"


def purge_workflow_id(task_queue: str) -> str:
    """The id of the run the schedule starts. Deterministic, and per queue too.

    Two schedules starting runs under one workflow id would be two deployments
    fighting over one execution — the schedule id alone is not enough.

    This is the **prefix** Temporal is given: the server appends the scheduled
    time to it, so an actual run is
    `system:events:purge:<queue>-2026-08-20T14:13:48Z`. That is the server's
    doing and not a random id — the part this repository chooses is
    deterministic, which is what house rule 18 is about.
    """
    return f"{PURGE_WORKFLOW_PREFIX}:{task_queue}"


def reconcile_outbox_schedule_id(task_queue: str) -> str:
    """The schedule id for one deployment's outbox relay. One per task queue."""
    return f"{RECONCILE_OUTBOX_SCHEDULE_PREFIX}:{task_queue}"


def reconcile_outbox_workflow_id(task_queue: str) -> str:
    """The id of the run the relay's schedule starts. Per queue, like the purge.

    The **prefix** Temporal is given; the server appends the scheduled time, so
    a run is `system:events:reconcile:<queue>-2026-08-22T14:13:48Z`. The part
    this repository chooses is deterministic, which is house rule 18's subject.
    """
    return f"{RECONCILE_OUTBOX_WORKFLOW_PREFIX}:{task_queue}"


def outbox_retention_days() -> int:
    """How many days a dispatched outbox row is kept.

    **Settings, and nothing else.** This used to fall back to
    `os.environ` because `config/settings/base.py` was not the events rung's to
    edit; it is declared there now, with its default and its line in
    `.env.example`, so a second reader of the same variable would only be a way
    for the two to disagree. Every other tunable in this repository is one
    `settings.X`, and this is no different.
    """
    return int(settings.EVENTS_OUTBOX_RETENTION_DAYS)


#: How long a delivery that reached a FINAL state is kept — ninety days, from
#: `Delivery.lifecycle` and the ratified retention table.
#:
#: A module constant and deliberately **not** a setting, unlike its outbox
#: neighbour. This repository settled that no build adds an environment variable;
#: and beyond that, the number is written into the declaration a reviewer reads
#: on the model, so a deployment that could quietly halve it would make that
#: declaration a sentence about nothing. The window is not measured — no
#: deployment has real deliveries yet — which is exactly why it is a decision
#: with a name rather than a tuning knob.
DELIVERY_RETENTION_DAYS = 90


def delivery_retention_days() -> int:
    """`DELIVERY_RETENTION_DAYS`, as the schedule's action carries it.

    An accessor rather than the constant inlined at the schedule, for the same
    reason `reconcile_batch_size` is one: what crosses the history is a number,
    and the one place that turns the module's declaration into that number is
    the place a test reads to prove the two agree.
    """
    return DELIVERY_RETENTION_DAYS


def outbox_grace_seconds() -> int:
    """`OUTBOX_GRACE` as the integer that crosses a Temporal history."""
    return int(OUTBOX_GRACE.total_seconds())


def reconcile_batch_size() -> int:
    """`RECONCILE_BATCH`, as the schedule's action carries it.

    An accessor rather than the constant inlined at the schedule, for the same
    reason `outbox_grace_seconds` is one: what crosses the history is a number,
    and the one place that turns the module's declaration into that number is
    the place a test reads to prove the two agree.
    """
    return RECONCILE_BATCH


def acting_tenant() -> Tenant | None:
    """The tenant this workflow is running for, restored from its headers.

    Through the bridge, never through an import, and never from the activity's
    argument — see the module docstring.
    """
    restored = bridge.get(bridge.WORKFLOW_CONTEXT)()
    if not isinstance(restored, tuple) or not restored:
        return None
    tenant = restored[0]
    return tenant if isinstance(tenant, Tenant) else None


def http_client() -> httpx.Client:
    """This app's one HTTP client, with a timeout on it.

    `apps.connections` owns the shared client factory (`architecture.md`), and
    this app cannot use it: they are sibling platform apps and `import-linter`
    holds them independent of each other. So the factory is here, once, with the
    timeout that matters — a subscriber that accepts the connection and never
    answers must not hold a worker thread until the socket gives up on its own.
    Nothing else in this app constructs a client, and a test replaces this
    function to hand back an `httpx.MockTransport`.
    """
    return httpx.Client(timeout=DELIVERY_TIMEOUT_SECONDS)


def sign(*, secret: str, body: bytes) -> str:
    """The `X-Signature` value for a body: HMAC-SHA256, hex, algorithm-prefixed.

    The subscriber recomputes this over the **raw bytes it received** and
    compares with `hmac.compare_digest`. That is why the body is serialised once
    and both signed and sent — re-serialising would risk a byte differing and a
    signature that never verifies.

    **This is the older of two schemes and it is sent beside `sign_v2`, not
    instead of it.** It covers the body and nothing else, so it says who signed
    and never when; anything that needs to know a delivery is *recent* wants
    `sign_v2`. Changing this function changes what every subscriber written
    before v2 existed is checking, which is the reason it has not changed.
    """
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def signed_payload_v2(*, timestamp: int, body: bytes) -> bytes:
    """What the v2 signature is computed over: `<unix seconds>.<the raw body>`.

    One function so that the signer and any verifier cannot drift on the two
    details that decide whether a first integration works: the separator is a
    single `.` and the timestamp is the decimal seconds, unpadded, with no `t=`
    on it — the `t=` lives in the header, not in the bytes that are hashed.
    """
    return f"{timestamp}.".encode() + body


def sign_v2(*, secret: str, body: bytes, timestamp: int) -> str:
    """The `X-Signature-V2` value: `t=<unix>,sha256=<hex over timestamp.body>`.

    The same key and the same algorithm as `sign`; the difference is that the
    timestamp is inside the digest as well as beside it, so a subscriber can
    tell how old a delivery is *and* know that nobody edited that answer. That
    is the whole of what v1 could not do: an HMAC over the body
    alone verifies for as long as the key lives, so a delivery captured once
    replays forever and the subscriber has nothing to refuse it with.

    Two headers go out during the expansion window and this is the new one.
    **The contraction — dropping `X-Signature` and signing only this — is
    deliberately not performed here**, because it is not ours to take: v1 comes
    out when the first product's subscribers have migrated to v2, which is a
    fact about somebody's integrations and not about this code. Until then a
    subscriber written before this code shipped keeps working, byte for byte.
    """
    digest = hmac.new(
        secret.encode("utf-8"), signed_payload_v2(timestamp=timestamp, body=body), hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},{SIGNATURE_PREFIX}{digest}"


def traceparent() -> str:
    """The W3C trace context for the current span, or empty when there is none.

    Propagated into the outbound webhook headers so that a subscriber's own
    tracing joins this product's (`architecture.md`, "Traceability": one trace
    from door to webhook).
    """
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return ""
    flags = "01" if span_context.trace_flags.sampled else "00"
    return (
        f"00-{format(span_context.trace_id, '032x')}-{format(span_context.span_id, '016x')}-{flags}"
    )


class DeliveryFailed(RuntimeError):
    """A subscriber refused in a way that might work next time. Temporal retries."""


# The 4xx codes that are worth retrying anyway: "slow down" and "you took too
# long", both of which are about *this* attempt rather than about the request.
RETRYABLE_CLIENT_ERRORS = frozenset({408, 425, 429})


def is_worth_retrying(code: int | None) -> bool:
    """Whether a subscriber's answer might be different in thirty seconds.

    A 5xx, a timeout or a refused connection is the subscriber having a moment;
    a 4xx is the subscriber telling us the request is wrong, and sending the
    identical bytes five more times is how a dead endpoint becomes six hours of
    someone else's error log. So a 4xx dead-letters immediately (with the two
    exceptions above), and a human sees a row rather than a retry storm.
    """
    if code is None:
        return True
    if 400 <= code < 500:
        return code in RETRYABLE_CLIENT_ERRORS
    return True


@activity.defn(name="load_delivery_targets")
def load_delivery_targets(payload: DispatchEvent) -> LoadedTargets:
    """Which endpoints have asked for this event.

    Idempotent: it is a read.

    **A missing event is terminal, not a retry** (queue V5). The dispatch
    workflow is started on the commit that wrote the event, so by the time this
    runs the row exists — unless it has been deleted, or the transaction that
    wrote it was rolled back after the hook was registered. Either way the row
    is not coming back, and retrying a read of it is a worker burning attempts
    forever against a tenant that no longer has the row. `NotFound` is
    re-raised as a **non-retryable** `ApplicationError`, so the run fails at
    once and says which event it was, exactly as `deliver_webhook` does for a
    subscriber that answered 4xx.
    """
    close_old_connections()
    try:
        tenant = acting_tenant()
        try:
            event = selectors.get_event(
                tenant=tenant, event_id=UUID(payload.event_id), actor=system_actor(tenant)
            )
        except NotFound as missing:
            log.warning("events.dispatch.event_gone", event_id=payload.event_id)
            raise ApplicationError(str(missing), non_retryable=True) from missing
        endpoints = selectors.endpoints_for(tenant=tenant, name=event.name)
        log.info(
            "events.dispatch.targets_loaded",
            event_id=str(event.pk),
            name=event.name,
            endpoints=len(endpoints),
        )
        return LoadedTargets(
            event_name=event.name,
            targets=[
                DeliveryTarget(endpoint_id=str(endpoint.pk), url=endpoint.url)
                for endpoint in endpoints
            ],
        )
    finally:
        close_old_connections()


@activity.defn(name="deliver_webhook")
def deliver_webhook(payload: DeliverWebhook) -> DeliveryOutcome:
    """One signed POST to one subscriber. Raises so that Temporal retries.

    The attempt is recorded **before** the exception leaves, so a delivery that
    is still failing on its fifth attempt is visible in the table rather than
    only in the worker's logs.
    """
    close_old_connections()
    try:
        tenant = acting_tenant()
        event = selectors.get_event(
            tenant=tenant, event_id=UUID(payload.event_id), actor=system_actor(tenant)
        )
        endpoint = selectors.get_endpoint(
            tenant=tenant, endpoint_id=UUID(payload.endpoint_id), actor=system_actor(tenant)
        )

        body = json.dumps(schemas.envelope(event), separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        # One timestamp, read once: the value inside the digest is the value in
        # the header, so a second read of the clock cannot put a delivery a
        # millisecond outside its own signature.
        signed_at = int(now().timestamp())
        headers = {
            "Content-Type": "application/json",
            "X-Signature": sign(secret=endpoint.secret, body=body),
            SIGNATURE_V2_HEADER: sign_v2(secret=endpoint.secret, body=body, timestamp=signed_at),
            "X-Event-Name": event.name,
            "X-Event-Id": str(event.pk),
            "X-Correlation-Id": event.correlation_id,
        }
        parent = traceparent()
        if parent:
            headers["traceparent"] = parent

        code: int | None = None
        try:
            with http_client() as client:
                response = client.post(endpoint.url, content=body, headers=headers)
            code = response.status_code
            failure = "" if response.is_success else f"HTTP {code}"
        except httpx.HTTPError as exc:
            # The message, never the exception's repr: a repr can carry the URL
            # with whatever a subscriber put in its query string.
            failure = f"{type(exc).__name__}: {exc}"

        status = Delivery.Status.FAILED if failure else Delivery.Status.DELIVERED
        delivery = services.record_delivery_attempt(
            tenant=event.tenant,
            endpoint_id=endpoint.pk,
            event_id=event.pk,
            status=status,
            code=code,
            error=failure,
        )
        if failure:
            log.warning(
                "events.delivery.failed",
                event_id=str(event.pk),
                endpoint_id=str(endpoint.pk),
                code=code,
                attempts=delivery.attempts,
            )
            if not is_worth_retrying(code):
                # Non-retryable: Temporal fails the activity now, and the
                # workflow dead-letters it on the first answer rather than on
                # the sixth identical one.
                raise ApplicationError(failure, non_retryable=True)
            raise DeliveryFailed(failure)
        log.info(
            "events.delivery.succeeded",
            event_id=str(event.pk),
            endpoint_id=str(endpoint.pk),
            code=code,
            attempts=delivery.attempts,
        )
        return DeliveryOutcome(delivery_id=str(delivery.pk), status=str(status), code=code)
    finally:
        close_old_connections()


@activity.defn(name="dead_letter_delivery")
def dead_letter_delivery(payload: DeadLetter) -> None:
    """Park a delivery whose retries are spent, and say so as an event."""
    close_old_connections()
    try:
        tenant = acting_tenant()
        event = selectors.get_event(
            tenant=tenant, event_id=UUID(payload.event_id), actor=system_actor(tenant)
        )
        endpoint = selectors.get_endpoint(
            tenant=tenant, endpoint_id=UUID(payload.endpoint_id), actor=system_actor(tenant)
        )
        services.dead_letter_delivery(
            tenant=event.tenant,
            endpoint_id=endpoint.pk,
            event_id=event.pk,
            error=payload.error,
        )
        log.warning(
            "events.delivery.dead_lettered",
            event_id=str(event.pk),
            endpoint_id=str(endpoint.pk),
        )
    finally:
        close_old_connections()


@activity.defn(name="close_outbox")
def close_outbox(payload: CloseOutbox) -> None:
    """Move the outbox row to its terminal state."""
    close_old_connections()
    try:
        tenant = acting_tenant()
        event = selectors.get_event(
            tenant=tenant, event_id=UUID(payload.event_id), actor=system_actor(tenant)
        )
        services.close_outbox(
            tenant=event.tenant,
            event_id=event.pk,
            status=payload.status or Outbox.Status.DISPATCHED,
            error=payload.error,
        )
    finally:
        close_old_connections()


@activity.defn(name="push_realtime")
def push_realtime(payload: PushRealtime) -> bool:
    """Hand the event to the socket bridge, if this deployment has one.

    `apps.realtime` registers `bridge.REALTIME_PUSH` from its
    `AppConfig.ready()`; where it is not installed there is nothing to push to
    and this returns False rather than failing the dispatch — a template
    without the socket app still has to deliver its webhooks. `find()` rather
    than `get()` is the whole difference: this caller genuinely does not mind,
    and says so.

    The lookup is by name, never by importing `apps.realtime` — the two apps are
    siblings and neither may import the other. That is also why what crosses is
    the **envelope**: the same JSON body a webhook subscriber is signed and
    sent, because this side cannot build the other side's `EventMessage` and
    should not be inventing a second serialisation of the same fact.
    """
    close_old_connections()
    try:
        push = bridge.find(bridge.REALTIME_PUSH)
        if push is None:
            log.info("events.realtime.absent", event_id=payload.event_id)
            return False
        tenant = acting_tenant()
        event = selectors.get_event(
            tenant=tenant, event_id=UUID(payload.event_id), actor=system_actor(tenant)
        )
        push(tenant_id=event.tenant_id, event=schemas.envelope(event))
        log.info("events.realtime.pushed", event_id=str(event.pk), name=event.name)
        return True
    finally:
        close_old_connections()


#: The bridge name `apps.search` registers its indexer under.
#:
#: It lives HERE rather than in `core.bridge`'s constants for the reason ADR
#: search-2 gives in as many words: **no ingredient touches `apps/core`**, so
#: the name lives beside the activity that calls it. A constant rather than a
#: literal, for the reason every other bridge name is one — a typo would be a
#: silent no-op on a laptop and a search index that quietly stopped moving in
#: production. `apps/search/apps.py` imports THIS constant to register with, so
#: there is one spelling and not two.
SEARCH_INDEX_EVENT = "search.index_event"


class IndexesSearchDocuments(Protocol):
    """The shape whatever fills `SEARCH_INDEX_EVENT` must have.

    **Why the protocol is here and not in `core.bridge.SHAPES` beside the other
    six.** ADR search-2 keeps this name out of `apps/core` — no ingredient
    touches that app — so the shape lives beside the activity that calls it, and
    `apps/search/apps.py::ready()` declares it INTO `SHAPES` in the same breath
    as it registers the callable. That is what keeps
    `apps/core/tests/test_bridge_shape.py` honest in both directions at once: a
    checkout with `apps.search` has a declared shape AND a registrant, and a
    checkout without it has neither, where a shape written into `core` by hand
    would have been a declaration nobody filled.

    Synchronous and keyword-only, like `PushesToSockets` above it and for the
    same reasons: the caller is a plain `def` activity on the worker's thread
    pool with no loop to await on, and a cross-app call has no positional order
    to remember. `event` is the **envelope** — the same JSON body a webhook
    subscriber is signed and sent — because `apps.events` cannot build the other
    app's document and should not invent a second serialisation of one fact.

    It answers whether anything was indexed, which is a fact worth having on
    `DispatchOutcome`; it RAISES when the index did not confirm the write, which
    is what the retry policy at the call site is for.
    """

    def __call__(self, *, tenant_id: Any, event: dict[str, Any]) -> bool: ...


@activity.defn(name="index_search")
def index_search(payload: IndexSearch) -> bool:
    """Hand the event to the search indexer, if this deployment has one.

    **The `push_realtime` posture, verbatim** (ADR search-2 asks for exactly
    that): `apps.search` registers `SEARCH_INDEX_EVENT` from its
    `AppConfig.ready()`, and where the app is not installed there is nothing to
    index into, so this returns `False` rather than failing the dispatch. A
    template without the search app still has to deliver its webhooks — the
    events suite runs green in a checkout that has never heard of Meilisearch,
    which is a property `test_workflows.py` drives from an empty registry rather
    than one this comment asserts.

    The lookup is by name and never by importing `apps.search`: the two apps are
    siblings under `import-linter`, and the search app sits above the spine
    precisely because it *consumes* what the spine fans out. What crosses is the
    **envelope** — the same JSON body a webhook subscriber is signed and sent —
    for the same reason the realtime push hands that body across: this side
    cannot build the other side's document, and inventing a second
    serialisation of one fact is how two doors start disagreeing.

    **What it does NOT do is decide anything.** Which kinds subscribe to this
    name, which row to re-read, and whether the document is written or deleted
    are all the other side's, because all three are answers only the registry
    has. This activity's whole job is to be the place a Temporal retry can
    happen: the handler raises when the index did not confirm the write, and
    the retry policy at the call site (`workflows.INDEX_RETRY`) is the catch-up
    queue ADR search-2 names.
    """
    close_old_connections()
    try:
        index = bridge.find(SEARCH_INDEX_EVENT)
        if index is None:
            log.info("events.search.absent", event_id=payload.event_id)
            return False
        tenant = acting_tenant()
        event = selectors.get_event(
            tenant=tenant, event_id=UUID(payload.event_id), actor=system_actor(tenant)
        )
        indexed = bool(index(tenant_id=event.tenant_id, event=schemas.envelope(event)))
        log.info(
            "events.search.indexed",
            event_id=str(event.pk),
            name=event.name,
            indexed=indexed,
        )
        return indexed
    finally:
        close_old_connections()


@activity.defn(name="purge_expired_records")
def purge_expired_records(window: PurgeExpired) -> PurgeOutcome:
    """Housekeeping: expired idempotency keys, old outbox rows, finished deliveries.

    **One activity for three populations, and not three activities.** They are
    the same act — the deployment's daily sweep — they share a schedule, a
    workflow and a timeout, and splitting them would buy three schedules whose
    only difference is which table they name. Each population is declared on its
    own model (`core.IdempotencyRecord`, `Outbox`, `Delivery`), and rule 31's
    walk reaches all three through this one body.

    Idempotent by construction — every one of the three deletes by age, so
    running it twice removes nothing the second time.

    The delivery window falls back to the module's own constant when the payload
    carries zero, which is what a schedule action written before that field
    existed replays as. Without the fallback that replay would sweep with a
    window of nothing and take every finished delivery in the deployment; the
    same guard, for the same reason, as `ReconcileOutbox.batch_size`.
    """
    close_old_connections()
    try:
        records = purge_expired()
        rows = services.purge_dispatched_outbox(
            before=now() - timedelta(days=window.outbox_retention_days)
        )
        deliveries = services.purge_deliveries(
            before=now()
            - timedelta(days=window.delivery_retention_days or DELIVERY_RETENTION_DAYS),
            tenant=None,
        )
        log.info(
            "events.purge.done",
            idempotency_records=records,
            outbox_rows=rows,
            deliveries=deliveries.count,
        )
        return PurgeOutcome(
            idempotency_records=records, outbox_rows=rows, deliveries=deliveries.count
        )
    finally:
        close_old_connections()


@activity.defn(name="reconcile_outbox")
def reconcile_outbox(window: ReconcileOutbox) -> ReconcileOutcome:
    """The relay: hand one **batch** of stranded outbox rows back to the dispatch.

    The reader `next_attempt_at` never had (ADR events-3). `emit()` writes the
    event, the outbox row and the retry clock in the caller's transaction and
    registers the dispatch on commit; a process that dies in the gap between
    that commit and the client call leaves a promise nobody is keeping and no
    scheduled work that would ever notice.

    **Through the service, never around it.** Each row goes back through
    `services.enqueue_dispatch(resume=True)` — the same write path a live
    dispatch takes, under the workflow id the crashed start already claimed, so
    a row the hook *did* reach late is answered by Temporal's
    `WorkflowAlreadyStartedError` and is a no-op rather than a second webhook.
    The clock is rewritten on the way through, which is also what keeps the next
    sweep off a row this one has just resumed.

    **Idempotent**, which Temporal demands: a re-run finds the rows it already
    resumed sitting outside the grace with a fresh clock, and does nothing.

    Each row is its own service call and its own transaction, so one row that
    cannot be resumed does not strand the rest of a sweep — and now
    that sentence is true of **every** way a row can fail, not only of the one
    the relay expects. Two populations, handled differently on purpose:

    * a **domain refusal** (`DomainError`) is the service deciding about that
      row. The ordinary one is a dispatch run that has already *finished* —
      `record_run` refuses to re-run a completed id, correctly, because that
      decision is a human's — and `NotFound` joins it when the purge has taken
      the event out from under the sweep. Counted as `unresolved`, named in the
      log; `manage.py replay_events` is the override that can make that call.
    * anything **else** is a `fault`: counted, logged at error with the
      exception's class, stepped past, and escalated at `RECONCILE_MAX_FAULTS`
      by letting the exception out, because that many faults in one batch is the
      platform rather than a row.

    Both counts ride the `already_seen` cursor, so neither kind can hold the
    head of the next batch.

    **Bounded, and the ceiling is the point.** At most
    `window.batch_size` rows — `RECONCILE_BATCH` when the history carries no
    number — and `more_remaining` says whether there is a candidate past them,
    which is how `ReconcileOutboxWorkflow` knows to ask again. The LIMIT is here
    and the loop is there because a workflow may not touch the ORM (house rule
    9); `+ 1` row is read rather than a second `COUNT` issued, so the candidate
    selection stays the one indexed query it was measured as.

    **No starvation, by construction, in both directions.** Oldest clock first,
    so the oldest promise is in the *first* batch and a ceiling can never be the
    reason it waits. And a batch that resumes nothing still advances: a resumed
    row leaves the candidate set (its clock is rewritten to `now()`) while a row
    the batch could not move stays at the head, so the workflow carries the
    count of them forward as `already_seen` and the next batch starts past them.
    Without that cursor a batch of nothing but immovable rows would be re-read
    for ever, which is the bug a ceiling *introduces* if it is added on its own.

    **"By construction" used to cover one exception class; now it covers the
    set.** The cursor only ever stepped past
    `Conflict`. Every other exception out of `enqueue_dispatch` — a `NotFound`
    from a purged event, a lock timeout on `select_for_update`, an error from
    the on-commit Temporal start — aborted the batch; Temporal retried it with
    the **same** `already_seen`, so one poison row pinned the sweep at a fixed
    offset and everything behind it starved. That is the exact failure the
    cursor exists to prevent, reached through a different door. The cursor now
    steps past both populations. What it deliberately does **not** do is step
    past a fault silently: every one is an `events.reconcile.fault` line naming
    the row and the exception class, and `RECONCILE_MAX_FAULTS` faults in one
    batch fail the activity outright. A skipped row nobody can see is the shape
    house rule 30 exists to catch.

    What this does not fix, and does not pretend to. `OFFSET` is
    discard-after-fetch, so a batch at `already_seen = N` makes `N + batch`
    index lookups to return `batch` (measured: 1,001 for `LIMIT 501 OFFSET
    500`), and the *next* scheduled sweep starts at zero again and pays one
    refused `enqueue_dispatch` for each unresolved row at the head before it
    reaches new work. Both costs are proportional to the **immovable**
    population and not to the pending one, which is the population
    `replay_events` exists for and is expected to be small; a deployment where
    it is not has a backlog to clear, and `events.reconcile.unresolved` /
    `events.reconcile.fault` are how it says so. A keyset cursor over
    `(next_attempt_at, pk)` is the answer if that day comes — it is not taken
    now because the clock is not unique, so the key is composite and the plan
    grows a sort the ceiling does not need.

    **A second residual, declared rather than fixed.** `already_seen`
    is a count and the candidate set is live, so if a row this sweep stepped past
    leaves the head mid-sweep — a concurrent `manage.py replay_events` resuming
    it, or the purge taking it — the cursor over-counts by that many and the next
    batch skips that many *legitimate* rows. It is self-healing: a skipped row
    keeps its clock, so it is still a candidate, and the next scheduled sweep
    starts at zero and reaches it. The fix is the keyset cursor named above, and
    it is not worth its extra sort for a residual that costs one sweep's delay on
    a population expected to be empty.

    The tenant comes off each row's own event rather than off the workflow
    headers: the sweep is platform housekeeping across every tenant, the posture
    `purge_expired_records` already has.
    """
    close_old_connections()
    try:
        batch_size = window.batch_size or RECONCILE_BATCH
        before = now() - timedelta(seconds=window.grace_seconds)
        candidates = list(
            selectors.list_stranded_outbox(
                before=before, limit=batch_size + 1, already_seen=window.already_seen
            )
        )
        outcome = ReconcileOutcome(more_remaining=len(candidates) > batch_size)
        for outbox in candidates[:batch_size]:
            try:
                services.enqueue_dispatch(
                    tenant=outbox.event.tenant, event_id=outbox.event_id, resume=True
                )
            except DomainError as refusal:
                # The service decided about this row. Deterministic — a retry
                # asks the same question and gets the same answer — so the batch
                # steps past it and a human owns the call.
                outcome.unresolved += 1
                log.warning(
                    "events.reconcile.unresolved",
                    event_id=str(outbox.event_id),
                    attempts=outbox.attempts,
                    error=type(refusal).__name__,
                )
                continue
            except Exception as fault:
                # Not a decision: a fault whose cause the relay does not know.
                # Isolated so it cannot starve the rows behind it, LOUD so it
                # cannot be a silent skip, and escalated once there are enough
                # of them that "poison row" stops being the likely story —
                # `raise` hands the batch back to Temporal's retry, which is the
                # right instrument for a transient platform fault and the wrong
                # one for a row that will refuse for ever.
                outcome.faults += 1
                log.error(
                    "events.reconcile.fault",
                    event_id=str(outbox.event_id),
                    attempts=outbox.attempts,
                    error=type(fault).__name__,
                )
                if outcome.faults >= RECONCILE_MAX_FAULTS:
                    raise
                continue
            outcome.reconciled += 1
            log.info(
                "events.reconcile.resumed",
                event_id=str(outbox.event_id),
                attempts=outbox.attempts,
            )
        log.info(
            "events.reconcile.done",
            reconciled=outcome.reconciled,
            unresolved=outcome.unresolved,
            faults=outcome.faults,
            more_remaining=outcome.more_remaining,
        )
        return outcome
    finally:
        close_old_connections()


# --- The schedule ------------------------------------------------------------


def purge_schedule(task_queue: str) -> Schedule:
    """The daily housekeeping schedule, as a value so a test can read it.

    A Temporal Schedule and not a cron entry (`architecture.md`): the schedule
    is deployed with the code, its last run is visible in the Temporal UI, and a
    missed one is a fact rather than a silence.
    """
    return Schedule(
        action=ScheduleActionStartWorkflow(
            services.PURGE_WORKFLOW,
            PurgeExpired(
                outbox_retention_days=outbox_retention_days(),
                delivery_retention_days=delivery_retention_days(),
            ),
            id=purge_workflow_id(task_queue=task_queue),
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=PURGE_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


def reconcile_outbox_schedule(task_queue: str) -> Schedule:
    """The relay's sweep, as a value so a test can read it.

    `SKIP` on overlap for the same reason the purge has it: two sweeps at once
    would both read the same stranded rows, and while a resume is idempotent
    there is no reason to pay for the race. Every sweep carries the same grace,
    which is why the number is a module constant rather than a schedule the
    server holds a stale copy of — the engine rewrites this action on every
    worker startup in `deployment` mode, and reads it fresh on every tick in
    `process` mode.
    """
    return Schedule(
        action=ScheduleActionStartWorkflow(
            services.RECONCILE_WORKFLOW,
            ReconcileOutbox(
                grace_seconds=outbox_grace_seconds(), batch_size=reconcile_batch_size()
            ),
            id=reconcile_outbox_workflow_id(task_queue=task_queue),
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=RECONCILE_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


#: The two periodic machines this app owns, declared as data (ADR
#: platform-lifecycle-1).
#:
#: An id builder and a `Schedule` value each, and nothing about how either
#: becomes real. Whether a declaration becomes a durable Temporal Schedule the
#: server owns, or a run the live worker starts on a timer, is decided once by
#: the deployment's lifetime class in `apps.workflows.client` — so that the two
#: classes cannot come to disagree about what the machine *is*, and so that this
#: app never has to know which one it is running under.
#:
#: The purge carries the one legacy id in the tree: the un-suffixed
#: `events-purge-expired` that older workers created before ADR events-2 made
#: schedule ids per queue. The engine drops it wherever it finds it, in either
#: lifetime class, and it is a constant rather than a builder because that is
#: exactly what a legacy id is — a name from before the id was derived.
PURGE = ScheduleDeclaration(
    name="events.purge-expired",
    schedule_id=purge_schedule_id,
    schedule=purge_schedule,
    log_prefix="events",
    legacy_ids=(LEGACY_PURGE_SCHEDULE_ID,),
)

RECONCILE_OUTBOX = ScheduleDeclaration(
    name="events.reconcile-outbox",
    schedule_id=reconcile_outbox_schedule_id,
    schedule=reconcile_outbox_schedule,
    log_prefix="events",
)


ACTIVITIES: list[Callable[..., Any]] = [
    load_delivery_targets,
    deliver_webhook,
    dead_letter_delivery,
    close_outbox,
    push_realtime,
    index_search,
    purge_expired_records,
    reconcile_outbox,
]

#: Discovered by `apps.workflows.client.discovered_schedules`, which the worker
#: consults at startup. One declaration per periodic machine this app owns.
SCHEDULES: list[ScheduleDeclaration] = [PURGE, RECONCILE_OUTBOX]
