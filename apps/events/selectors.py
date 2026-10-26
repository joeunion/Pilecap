"""Reads for the event spine. Nothing here writes (house rule 12).

Two audiences, and the split matters:

* **A tenant's own reads** go through `for_tenant(...)` like every other read in
  the product — its events, its endpoints, its deliveries, and nothing else.
* **The deployment's reads** — the replay command, the housekeeping schedule —
  cross tenants deliberately, because "which events never dispatched" is a
  question about the deployment and not about a customer. Each one says so in
  its docstring and each is reachable only from the shell door or a schedule.

**And since Phase R every read a DOOR reaches ASKS** (ADR core-27, §C6). `actor`
is a required keyword on those — never optional, because an `actor=None` default
is a read that fails open the first time a caller forgets — and each calls
`require(actor, "<kind>.read", ...)` exactly once. **Two questions, two owners**
(rule 24): `for_tenant` decides WHICH rows, `require` decides WHETHER this kind.
Nothing here filters rows by permission.

A `list_` asks at the acting hat before it builds the queryset; a `get_` asks
after the scoped fetch, so another tenant's row stays `not_found`. Every model
this app reads is TENANT-scoped (a `Delivery` is not even that — it is dispatch
machinery, scoped by the join to its event), so there is no node below the
tenant for the question to be asked at and the acting hat is the only node it
has.

**Sight is the hat's; configuration is the root's.** A branch's people SEE the
tenant's endpoints, deliveries and events — never a secret, because no `Out`
carries one — and cannot change any of them: every write here is asked at the
tenant's root and stays there. That is the answer three other doors already
gave (the socket narrows per hat, `search` asks at the hat, the admin
changelist asks with `obj=None`), so this one stopped disagreeing with them.
Each site carries a DATED hat-scoped valve saying so, counted on rule 55's
status line, and the rung that gives these kinds a home in v2.2 deletes it
(the universal-homing proposal, 2026-09-17 — every record homed at a node).
`Event` is the exception and carries no marker: it has a nullable
`organization`, so it is outside that rule's population already and its `get_`
asks at the row's own node when the row has one.

**The deployment's reads ask nothing, and each says why on its own line.** There
is no person behind a housekeeping sweep or a replay command, and `system` passes
`allows` at step 1 anyway — what would be wrong is a DOOR reaching one of them.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from django.db.models import Q, QuerySet

from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.exceptions import NotFound
from apps.core.models import ScopedQuerySet, Tenant
from apps.events.models import Delivery, Event, Outbox, WebhookEndpoint


def _events_in(*, tenant: Tenant | None) -> ScopedQuerySet[Event]:
    """The tenant's events, newest first. No capability asked."""
    return Event.objects.for_tenant(tenant).order_by("-occurred_at")


def _endpoints_in(*, tenant: Tenant | None, active_only: bool) -> ScopedQuerySet[WebhookEndpoint]:
    """The tenant's endpoints, optionally only the active ones. No capability."""
    endpoints = WebhookEndpoint.objects.for_tenant(tenant)
    if active_only:
        endpoints = endpoints.filter(is_active=True)
    return endpoints


def _deliveries_in(*, tenant: Tenant | None) -> QuerySet[Delivery]:
    """The tenant's deliveries, through the events they belong to. No capability."""
    return Delivery.objects.filter(event__in=Event.objects.for_tenant(tenant)).select_related(
        "endpoint", "event"
    )


def list_events(*, tenant: Tenant | None, actor: Actor) -> ScopedQuerySet[Event]:
    """The tenant's events, newest first."""
    # THE CAPABILITY, at the hat, BEFORE the queryset: a list has no row to
    # hide, so somebody without `event.read` hears that rather than an empty
    # page that looks like a tenant nothing has happened in.
    #
    # No valve marker here, and that is not an oversight: `Event` carries a
    # nullable `organization`, so `event` is OUTSIDE house rule 55's population
    # (the derivation reads the column) and a marker on this line would be
    # counted by nothing — a valve nobody counts is an off switch with a comment
    # on it. What the list asks at is the hat, for the reason every other read of
    # a tenant-wide kind does, DATED 2026-09-17 as the v2.1 stopgap until v2.2
    # homes these kinds (the universal-homing proposal, 2026-09-17 — every
    # record homed at a node).
    require(actor, "event.read")
    return _events_in(tenant=tenant)


def get_event(*, tenant: Tenant | None, event_id: UUID, actor: Actor) -> Event:
    """One event in this tenant, or `NotFound` — the same answer either way.

    **Reach before capability** (§C8): the scoped fetch is what makes another
    tenant's event `not_found`, and the `require` below is what makes one inside
    this tenant `forbidden` when the caller holds no `event.read`.
    """
    event = _events_in(tenant=tenant).select_related("tenant").filter(pk=event_id).first()
    if event is None:
        raise NotFound()
    # THE ROW, which for an `Event` is a real node when the write that made it
    # landed in a branch: `where_of` resolves the row's own `organization` and
    # falls back to the acting hat when it has none. So an event homed in a
    # sibling branch is refused where the caller holds nothing, and a tenant-wide
    # one answers at the hat — the right altitude under either register, and the
    # reason this app's `event` reads need no rule-55 valve (the column is what
    # puts them outside the population).
    require(actor, "event.read", event)
    return event


def list_endpoints(
    *, tenant: Tenant | None, active_only: bool = True, actor: Actor
) -> ScopedQuerySet[WebhookEndpoint]:
    """The tenant's webhook endpoints."""
    # hat-scoped: sight is the acting hat's — a webhook endpoint is TENANT-WIDE
    # configuration and a branch's people may SEE where the tenant's data is sent;
    # they cannot change it, because the writes are asked at the root and stay there.
    # The row names no organization, so there is no node below the tenant for
    # this question to be asked at, and the hat is the only node it has.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, "endpoint.read")
    return _endpoints_in(tenant=tenant, active_only=active_only)


def get_endpoint(*, tenant: Tenant | None, endpoint_id: UUID, actor: Actor) -> WebhookEndpoint:
    """One endpoint in this tenant, or `NotFound`.

    Deliberately not filtered to the active ones: the delivery activity looks a
    row up by the id the workflow was handed, and an endpoint deactivated
    halfway through a fan-out should have its delivery recorded rather than
    disappear mid-flight. That caller passes a `system` actor, which `allows`
    admits at step 1, so the capability below costs the fan-out nothing.
    """
    endpoint = _endpoints_in(tenant=tenant, active_only=False).filter(pk=endpoint_id).first()
    if endpoint is None:
        raise NotFound()
    # **Which wall answers first, and it is not `may_be_named`.** Reach is the
    # `for_tenant` fetch above raising `NotFound` — `may_be_named` returns False
    # for a row with no organization, so a tenant-scoped kind has no reach wall
    # of that shape and never had one. Reachability before capability (house
    # rule 26's order) is therefore the scoped fetch, then this line. The same
    # holds for `get_event` and `get_delivery` below.
    # hat-scoped: sight is the acting hat's — the row is handed over for the
    # POLICY to read and never as a node to resolve at, so this asks exactly what
    # the list asks and answers at the same node.
    # The row names no organization, so there is no node below the tenant for
    # this question to be asked at, and the hat is the only node it has.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, "endpoint.read", endpoint)
    return endpoint


def list_endpoints_for(*, tenant: Tenant | None, name: str) -> list[WebhookEndpoint]:
    """The active endpoints that have asked for this event name.

    # read-open: the dispatch activity's machine read; a door reads `list_endpoints`, which asks.
    The name filter is Python: `WebhookEndpoint.wants` is the one rule (empty means everything).
    """
    return [
        endpoint
        for endpoint in _endpoints_in(tenant=tenant, active_only=True)
        if endpoint.wants(name)
    ]


def list_deliveries(*, tenant: Tenant | None, actor: Actor) -> QuerySet[Delivery]:
    """The tenant's deliveries, read through the events they belong to.

    `Delivery` is not tenant-scoped — it is dispatch machinery, not the tenant's
    data — so the scoping is done here, by joining to the event, and this is the
    only way a door ever reaches one.
    """
    # hat-scoped: sight is the acting hat's — a delivery is the tenant's dispatch
    # machinery, shared by every branch, and seeing an attempt is not changing one.
    # The row names no organization, so there is no node below the tenant for
    # this question to be asked at, and the hat is the only node it has.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, "delivery.read")
    return _deliveries_in(tenant=tenant)


def get_delivery(*, tenant: Tenant | None, delivery_id: UUID, actor: Actor) -> Delivery:
    """One delivery in this tenant, or `NotFound` — the same answer either way.

    Reached through `list_deliveries`, so the tenancy is the join to the event
    and not a column on this row: `Delivery` is dispatch machinery rather than
    the tenant's data (see `models.py`), and this is the only way a door ever
    resolves one by id.
    """
    delivery = _deliveries_in(tenant=tenant).filter(pk=delivery_id).first()
    if delivery is None:
        raise NotFound()
    # hat-scoped: sight is the acting hat's — the row is handed over for the
    # POLICY to read and never as a node; reach was already answered above.
    # The row names no organization, so there is no node below the tenant for
    # this question to be asked at, and the hat is the only node it has.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, "delivery.read", delivery)
    return delivery


def list_dead_letters(*, tenant: Tenant | None, actor: Actor) -> QuerySet[Delivery]:
    """The tenant's deliveries that gave up. The one an operator asks for."""
    # hat-scoped: a delivery names no organization, so the hat is the only node to ask at.
    require(actor, "delivery.read")
    return _deliveries_in(tenant=tenant).filter(dead_lettered_at__isnull=False)


# --- Deployment-wide reads (shell and schedules only) ------------------------


def list_outbox_to_replay(
    *, since: datetime | None = None, event_id: UUID | None = None
) -> QuerySet[Outbox]:
    """Outbox rows a human has asked to send again, across tenants, oldest first.

    # read-open: `manage.py replay_events`' shell read; recovery is deployment-wide, no hat.
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


def list_active_endpoints_everywhere() -> QuerySet[WebhookEndpoint]:
    """Every active endpoint in every tenant, oldest first, with its tenant.

    # read-open: `manage.py webhook_endpoints`' shell read; the refused list is deployment-wide.
    """
    return (
        # rule-8: the operator's refused-target list spans every tenant, as `replay_events` does.
        WebhookEndpoint.objects.filter(is_active=True)
        .select_related("tenant")
        .order_by("created_at", "pk")
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

    # read-open: the relay sweeping its own machinery, with no person behind it.
    # `Outbox` is the spine's own bookkeeping — a promise this deployment made to
    # itself — and this read crosses tenants by design, so there is no hat to ask
    # at and no tenant whose key would be the right question. The one caller is
    # the reconcile activity (`activities.py`), which runs as `system`; the shell
    # door's `replay_events` reaches `list_outbox_to_replay` beside it.
    """
    stranded = (
        Outbox.objects.filter(status=Outbox.Status.PENDING, next_attempt_at__lt=before)
        .select_related("event", "event__tenant")
        .order_by("next_attempt_at")
    )
    if limit is None:
        return stranded[already_seen:] if already_seen else stranded
    return stranded[already_seen : already_seen + limit]


def list_undispatched_outbox(*, before: datetime | None = None) -> QuerySet[Outbox]:
    """Outbox rows that never reached `dispatched`, across tenants.

    # read-open: the surveyor's standing lens on the spine, with no person behind it.
    """
    query = ~Q(status=Outbox.Status.DISPATCHED)
    if before is not None:
        query &= Q(created_at__lt=before)
    return Outbox.objects.filter(query).select_related("event", "event__tenant")
