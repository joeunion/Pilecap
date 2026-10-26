"""Where the spine touches the world: the database, and somebody else's server (rules 9, 10).

Who the work is for is `current_actor()`, off the run's headers — never an argument.
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
from temporalio.exceptions import ApplicationError

from apps.core import bridge
from apps.core.context import current_actor
from apps.core.exceptions import DomainError, NotFound
from apps.core.idempotency import purge_expired
from apps.core.log import get_logger
from apps.core.schedules import ScheduleDeclaration, daily_purge, platform_schedule
from apps.core.time import now
from apps.events import schemas, selectors, services, targets
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

#: One POST to a subscriber; shorter than the activity's own timeout, so a hung socket is recorded.
DELIVERY_TIMEOUT_SECONDS = 10.0

#: The prefix of a delivery's error when its target is refused (ADR events-5).
PRIVATE_TARGET = "private_target"

#: The signature header's algorithm prefix.
SIGNATURE_PREFIX = "sha256="

#: The second scheme's header, sent beside `X-Signature` and never instead of it.
#: why-not drop `X-Signature`: that waits on the subscribers' migration, which this code cannot see.
SIGNATURE_V2_HEADER = "X-Signature-V2"

#: The un-suffixed schedule id older workers created (ADR events-2); the engine deletes it.
LEGACY_PURGE_SCHEDULE_ID = "events-purge-expired"

#: How far past `next_attempt_at` a pending row is stranded rather than in flight (ADR events-3).
OUTBOX_GRACE = timedelta(minutes=5)
RECONCILE_EVERY = timedelta(minutes=5)

#: The most stranded rows one relay activity resumes before handing back to the workflow.
RECONCILE_BATCH = 500

#: Faults (not refusals) isolated per row up to this many in one batch; past it the activity fails.
RECONCILE_MAX_FAULTS = 5

#: How long a delivery that reached a final state is kept — `Delivery.lifecycle`'s window.
DELIVERY_RETENTION_DAYS = 90


def outbox_retention_days() -> int:
    """How many days a dispatched outbox row is kept: `settings.EVENTS_OUTBOX_RETENTION_DAYS`."""
    return int(settings.EVENTS_OUTBOX_RETENTION_DAYS)


def delivery_retention_days() -> int:
    """`DELIVERY_RETENTION_DAYS`, as the schedule's action carries it."""
    return DELIVERY_RETENTION_DAYS


def outbox_grace_seconds() -> int:
    """`OUTBOX_GRACE` as the integer that crosses a Temporal history."""
    return int(OUTBOX_GRACE.total_seconds())


def reconcile_batch_size() -> int:
    """`RECONCILE_BATCH`, as the schedule's action carries it."""
    return RECONCILE_BATCH


def http_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """This app's one HTTP client: a timeout, and a redirect is an answer, never a second request.

    why-not `apps.connections`' factory: the platform apps may not import each other.
    """
    return httpx.Client(
        timeout=DELIVERY_TIMEOUT_SECONDS, transport=transport, follow_redirects=False
    )


def sign(*, secret: str, body: bytes) -> str:
    """The `X-Signature` value: HMAC-SHA256 over the raw body, hex, algorithm-prefixed."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def signed_payload_v2(*, timestamp: int, body: bytes) -> bytes:
    """What the v2 signature is computed over: `<unix seconds>.<the raw body>`."""
    return f"{timestamp}.".encode() + body


def sign_v2(*, secret: str, body: bytes, timestamp: int) -> str:
    """The `X-Signature-V2` value: `t=<unix>,sha256=<hex over timestamp.body>`."""
    digest = hmac.new(
        secret.encode("utf-8"), signed_payload_v2(timestamp=timestamp, body=body), hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},{SIGNATURE_PREFIX}{digest}"


def traceparent() -> str:
    """The W3C trace context for the current span, or empty when there is none."""
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return ""
    flags = "01" if span_context.trace_flags.sampled else "00"
    return (
        f"00-{format(span_context.trace_id, '032x')}-{format(span_context.span_id, '016x')}-{flags}"
    )


class DeliveryFailed(RuntimeError):
    """A subscriber refused in a way that might work next time. Temporal retries."""


#: The 4xx codes about this attempt rather than the request.
RETRYABLE_CLIENT_ERRORS = frozenset({408, 425, 429})


def is_worth_retrying(code: int | None) -> bool:
    """Whether a subscriber's answer might differ: a 4xx does not, bar `RETRYABLE_CLIENT_ERRORS`."""
    if code is None:
        return True
    if 400 <= code < 500:
        return code in RETRYABLE_CLIENT_ERRORS
    return True


@activity.defn(name="load_delivery_targets", no_thread_cancel_exception=True)
def load_delivery_targets(payload: DispatchEvent) -> LoadedTargets:
    """Which endpoints have asked for this event; a missing event is non-retryable."""
    close_old_connections()
    try:
        actor = current_actor()
        tenant = actor.tenant
        try:
            event = selectors.get_event(tenant=tenant, event_id=UUID(payload.event_id), actor=actor)
        except NotFound as missing:
            log.warning("events.dispatch.event_gone", event_id=payload.event_id)
            raise ApplicationError(str(missing), non_retryable=True) from missing
        endpoints = selectors.list_endpoints_for(tenant=tenant, name=event.name)
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


@activity.defn(name="deliver_webhook", no_thread_cancel_exception=True)
def deliver_webhook(payload: DeliverWebhook) -> DeliveryOutcome:
    """One signed POST to one subscriber, recorded before it raises so that Temporal retries."""
    close_old_connections()
    try:
        actor = current_actor()
        tenant = actor.tenant
        event = selectors.get_event(tenant=tenant, event_id=UUID(payload.event_id), actor=actor)
        endpoint = selectors.get_endpoint(
            tenant=tenant, endpoint_id=UUID(payload.endpoint_id), actor=actor
        )

        body = json.dumps(schemas.envelope(event), separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        # One clock read: the timestamp in the digest is the one in the header.
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

        refused = targets.target_class(endpoint.url)
        if refused is not None:
            failure = f"{PRIVATE_TARGET}: {refused}"
            services.record_delivery_attempt(
                tenant=event.tenant,
                endpoint_id=endpoint.pk,
                event_id=event.pk,
                status=Delivery.Status.FAILED,
                code=None,
                error=failure,
            )
            log.warning(
                "events.delivery.refused_target",
                event_id=str(event.pk),
                endpoint_id=str(endpoint.pk),
                target_class=refused,
            )
            raise ApplicationError(failure, non_retryable=True)

        code: int | None = None
        try:
            with http_client() as client:
                response = client.post(endpoint.url, content=body, headers=headers)
            code = response.status_code
            failure = "" if response.is_success else f"HTTP {code}"
        except httpx.HTTPError as exc:
            # The message, never the repr: a repr can carry the URL's query string.
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


@activity.defn(name="dead_letter_delivery", no_thread_cancel_exception=True)
def dead_letter_delivery(payload: DeadLetter) -> None:
    """Park a delivery whose retries are spent."""
    close_old_connections()
    try:
        actor = current_actor()
        tenant = actor.tenant
        event = selectors.get_event(tenant=tenant, event_id=UUID(payload.event_id), actor=actor)
        endpoint = selectors.get_endpoint(
            tenant=tenant, endpoint_id=UUID(payload.endpoint_id), actor=actor
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


@activity.defn(name="close_outbox", no_thread_cancel_exception=True)
def close_outbox(payload: CloseOutbox) -> None:
    """Move the outbox row to its terminal state."""
    close_old_connections()
    try:
        actor = current_actor()
        tenant = actor.tenant
        event = selectors.get_event(tenant=tenant, event_id=UUID(payload.event_id), actor=actor)
        services.close_outbox(
            tenant=event.tenant,
            event_id=event.pk,
            status=payload.status or Outbox.Status.DISPATCHED,
            error=payload.error,
        )
    finally:
        close_old_connections()


@activity.defn(name="push_realtime", no_thread_cancel_exception=True)
def push_realtime(payload: PushRealtime) -> bool:
    """Hand the envelope to the socket bridge; `False` where `apps.realtime` is not installed."""
    close_old_connections()
    try:
        push = bridge.find(bridge.REALTIME_PUSH)
        if push is None:
            log.info("events.realtime.absent", event_id=payload.event_id)
            return False
        actor = current_actor()
        tenant = actor.tenant
        event = selectors.get_event(tenant=tenant, event_id=UUID(payload.event_id), actor=actor)
        push(tenant_id=event.tenant_id, event=schemas.envelope(event))
        log.info("events.realtime.pushed", event_id=str(event.pk), name=event.name)
        return True
    finally:
        close_old_connections()


#: The bridge name `apps.search` registers its indexer under (ADR search-2: not in `core`).
SEARCH_INDEX_EVENT = "search.index_event"


class IndexesSearchDocuments(Protocol):
    """The shape whatever fills `SEARCH_INDEX_EVENT` must have; it raises on an unconfirmed write.

    why-not `core.bridge.SHAPES`: no ingredient touches `apps/core` (ADR search-2).
    """

    def __call__(self, *, tenant_id: Any, event: dict[str, Any]) -> bool: ...


@activity.defn(name="index_search", no_thread_cancel_exception=True)
def index_search(payload: IndexSearch) -> bool:
    """Hand the envelope to the search indexer; `False` where `apps.search` is not installed.

    It decides nothing: the indexer raises on an unconfirmed write and the call site's
    `workflows.index_retry` is the catch-up queue (ADR search-2).
    """
    close_old_connections()
    try:
        index = bridge.find(SEARCH_INDEX_EVENT)
        if index is None:
            log.info("events.search.absent", event_id=payload.event_id)
            return False
        actor = current_actor()
        tenant = actor.tenant
        event = selectors.get_event(tenant=tenant, event_id=UUID(payload.event_id), actor=actor)
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


@activity.defn(name="purge_expired_records", no_thread_cancel_exception=True)
def purge_expired_records(window: PurgeExpired) -> PurgeOutcome:
    """Housekeeping: expired idempotency keys, old outbox rows, finished deliveries.

    A zero delivery window is the module's own (an action written before the field replays as zero).
    """
    close_old_connections()
    try:
        records = purge_expired()
        rows = services.purge_dispatched_outbox(
            before=now() - timedelta(days=window.outbox_retention_days), tenant=None
        ).count
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


@activity.defn(name="reconcile_outbox", no_thread_cancel_exception=True)
def reconcile_outbox(window: ReconcileOutbox) -> ReconcileOutcome:
    """The relay: hand one batch of stranded outbox rows back to the dispatch (ADR events-3).

    A domain refusal is `unresolved` and stepped past; any other fault is counted, logged and
    escalated at `RECONCILE_MAX_FAULTS`. Both advance `already_seen`, so neither holds the head.
    does-not-cover: a row a concurrent replay moves mid-sweep over-counts the cursor for one sweep.
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
                outcome.unresolved += 1
                log.warning(
                    "events.reconcile.unresolved",
                    event_id=str(outbox.event_id),
                    attempts=outbox.attempts,
                    error=type(refusal).__name__,
                )
                continue
            except Exception as fault:
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


# --- The schedules -----------------------------------------------------------

#: `platform:events:purge:<queue>`, daily — the far end of `Outbox` and `Delivery`'s lifecycles.
PURGE = daily_purge(
    app="events",
    noun="purge",
    workflow=services.PURGE_WORKFLOW,
    arg=PurgeExpired(
        outbox_retention_days=outbox_retention_days(),
        delivery_retention_days=delivery_retention_days(),
    ),
    name="events.purge-expired",
    log_prefix="events",
    legacy_ids=(LEGACY_PURGE_SCHEDULE_ID,),
)

#: `platform:events:reconcile:<queue>`, every `RECONCILE_EVERY` — the outbox relay (ADR events-3).
RECONCILE_OUTBOX = platform_schedule(
    app="events",
    noun="reconcile",
    workflow=services.RECONCILE_WORKFLOW,
    every=RECONCILE_EVERY,
    arg=ReconcileOutbox(grace_seconds=outbox_grace_seconds(), batch_size=reconcile_batch_size()),
    name="events.reconcile-outbox",
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

SCHEDULES: list[ScheduleDeclaration] = [PURGE, RECONCILE_OUTBOX]
