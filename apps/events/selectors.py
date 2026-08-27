"""Reads for the event spine. Nothing here writes (house rule 12).

Two audiences, and the split matters:

* **A tenant's own reads** go through `for_tenant(...)` like every other read in
  the product — its events, its endpoints, its deliveries, and nothing else.
* **The deployment's reads** — the replay command, the housekeeping schedule —
  cross tenants deliberately, because "which events never dispatched" is a
  question about the deployment and not about a customer. Each one says so in
  its docstring and each is reachable only from the shell door or a schedule.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db.models import Q, QuerySet

from apps.core.exceptions import NotFound
from apps.core.models import ScopedQuerySet, Tenant
from apps.events.models import Delivery, Event, Outbox, WebhookEndpoint


def list_events(*, tenant: Tenant | None) -> ScopedQuerySet[Event]:
    """The tenant's events, newest first."""
    return Event.objects.for_tenant(tenant).order_by("-occurred_at")


def get_event(*, tenant: Tenant | None, event_id: UUID) -> Event:
    """One event in this tenant, or `NotFound` — the same answer either way."""
    event = Event.objects.for_tenant(tenant).select_related("tenant").filter(pk=event_id).first()
    if event is None:
        raise NotFound()
    return event


def list_endpoints(
    *, tenant: Tenant | None, active_only: bool = True
) -> ScopedQuerySet[WebhookEndpoint]:
    """The tenant's webhook endpoints."""
    endpoints = WebhookEndpoint.objects.for_tenant(tenant)
    if active_only:
        endpoints = endpoints.filter(is_active=True)
    return endpoints


def get_endpoint(*, tenant: Tenant | None, endpoint_id: UUID) -> WebhookEndpoint:
    """One endpoint in this tenant, or `NotFound`.

    Deliberately not filtered to the active ones: the delivery activity looks a
    row up by the id the workflow was handed, and an endpoint deactivated
    halfway through a fan-out should have its delivery recorded rather than
    disappear mid-flight.
    """
    endpoint = WebhookEndpoint.objects.for_tenant(tenant).filter(pk=endpoint_id).first()
    if endpoint is None:
        raise NotFound()
    return endpoint


def endpoints_for(*, tenant: Tenant | None, name: str) -> list[WebhookEndpoint]:
    """The active endpoints that have asked for this event name.

    The name filter is applied in Python rather than in SQL: `event_names` is a
    JSON allow-list where **empty means everything**, and expressing "empty OR
    contains" as a portable query buys nothing at the number of endpoints a
    tenant has. `WebhookEndpoint.wants` is the one definition of the rule.
    """
    return [
        endpoint
        for endpoint in list_endpoints(tenant=tenant, active_only=True)
        if endpoint.wants(name)
    ]


def list_deliveries(*, tenant: Tenant | None) -> QuerySet[Delivery]:
    """The tenant's deliveries, read through the events they belong to.

    `Delivery` is not tenant-scoped — it is dispatch machinery, not the tenant's
    data — so the scoping is done here, by joining to the event, and this is the
    only way a door ever reaches one.
    """
    return Delivery.objects.filter(event__in=Event.objects.for_tenant(tenant)).select_related(
        "endpoint", "event"
    )


def get_delivery(*, tenant: Tenant | None, delivery_id: UUID) -> Delivery:
    """One delivery in this tenant, or `NotFound` — the same answer either way.

    Reached through `list_deliveries`, so the tenancy is the join to the event
    and not a column on this row: `Delivery` is dispatch machinery rather than
    the tenant's data (see `models.py`), and this is the only way a door ever
    resolves one by id.
    """
    delivery = list_deliveries(tenant=tenant).filter(pk=delivery_id).first()
    if delivery is None:
        raise NotFound()
    return delivery


def dead_lettered(*, tenant: Tenant | None) -> QuerySet[Delivery]:
    """The tenant's deliveries that gave up. The one an operator asks for."""
    return list_deliveries(tenant=tenant).filter(dead_lettered_at__isnull=False)


# --- Deployment-wide reads (shell and schedules only) ------------------------


def outbox_to_replay(
    *, since: datetime | None = None, event_id: UUID | None = None
) -> QuerySet[Outbox]:
    """Outbox rows a human has asked to send again. **Crosses tenants.**

    `manage.py replay_events` is the caller, and the shell door is the only one
    that reaches it: recovering from an outage is a deployment-level act, and
    narrowing it to one tenant would mean running it once per customer.

    Ordered oldest-first, so a replay re-sends in the order the events happened.
    """
    query = Q()
    if event_id is not None:
        query &= Q(event_id=event_id)
    if since is not None:
        query &= Q(event__occurred_at__gte=since)
    return (
        Outbox.objects.filter(query)
        .select_related("event", "event__tenant")
        .order_by("event__occurred_at")
    )


def list_stranded_outbox(
    *, before: datetime, limit: int | None = None, already_seen: int = 0
) -> QuerySet[Outbox]:
    """Pending outbox rows whose retry clock ran out. **Crosses tenants.**

    **The reader `next_attempt_at` did not have** (ADR events-3).
    `emit()` writes the column and the index over `(status, next_attempt_at)`
    exists for exactly this query, and until the relay nothing in production ran
    it: a process that died between the commit and the on-commit dispatch left a
    `pending` row holding a promise, and only a human running
    `manage.py replay_events` could ever find it.

    Deployment-wide for the same reason the purge is: the outbox is dispatch
    machinery, "which promises are overdue" is a question about the deployment,
    and asking it once per tenant is how half a recovery happens. The relay's
    activity is the one caller and it re-enqueues each row through
    `services.enqueue_dispatch`, per tenant, as the system.

    `before` is `now() - OUTBOX_GRACE`, computed in the activity, because a
    workflow may not read a clock (house rule 9). Terminal rows are excluded
    twice over: `close_outbox` moves the status off `pending` **and** sets
    `next_attempt_at` back to NULL, and a NULL never satisfies `__lt`.

    Oldest clock first, so a sweep after an outage heals in the order the
    promises were made — and, since the drain is bounded below, so that the
    **oldest promise is in the first batch** rather than the one a timeout never
    reaches.

    **`limit` is the ceiling this read did not have.** The
    candidate selection was always one indexed query at any depth, but it
    returned the whole pending population and `reconcile_outbox` walked all of
    it at nine statements a row — 180,000 statements in one activity at the
    declared 20,000 pending, which is not a runaway but a sweep that times out,
    retries from the head, and never reaches the oldest promises it re-drains
    every attempt. `None` keeps the unbounded read for the shell door and for
    measurement; the relay passes a number.

    `already_seen` skips that many rows at the head. Its one caller is the relay
    batching through a single sweep, and `types.ReconcileOutbox` carries why a
    count is a sound cursor here: the set only ever shrinks from the front and
    only ever grows at the tail.
    """
    stranded = (
        Outbox.objects.filter(status=Outbox.Status.PENDING, next_attempt_at__lt=before)
        .select_related("event", "event__tenant")
        .order_by("next_attempt_at")
    )
    if limit is None:
        return stranded[already_seen:] if already_seen else stranded
    return stranded[already_seen : already_seen + limit]


def undispatched(*, before: datetime | None = None) -> QuerySet[Outbox]:
    """Outbox rows that never reached `dispatched`. **Crosses tenants.**

    The surveyor's standing lens on the spine: an event that never dispatched is
    a promise the product made and did not keep.
    """
    query = ~Q(status=Outbox.Status.DISPATCHED)
    if before is not None:
        query &= Q(created_at__lt=before)
    return Outbox.objects.filter(query).select_related("event", "event__tenant")
