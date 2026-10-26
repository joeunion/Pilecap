"""Writes for the connections app: each a `@service`, and each change asks `authz.require` first.

`LOG_KEYS` is an allow-list without `credentials`: a credential is `[redacted]` in log and audit.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.connections.events import (
    CONNECTION_CREATED,
    CONNECTION_CREDENTIALS_UPDATED,
    CONNECTION_REVOKED,
    CONNECTION_SIGNATURE_SCHEME_UPDATED,
    WEBHOOK_RECEIVED,
    V,
)
from apps.connections.models import Connection, InboundWebhook
from apps.connections.providers import inbound_handler
from apps.connections.schemas import ConnectionOut, InboundWebhookOut
from apps.connections.types import HANDLE_WORKFLOW, HandleInboundWebhook
from apps.core import bridge
from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.exceptions import Invalid, as_invalid
from apps.core.log import get_logger
from apps.core.models import Tenant
from apps.core.retry import retry_floor_seconds
from apps.core.schemas import event_payload
from apps.core.service import service
from apps.core.services import root_organization
from apps.core.types import Swept

log = get_logger(__name__)

# What may appear un-redacted in this app's log lines and audit `input`.
# `credentials` is not on it and must never be: that is the entire point of the
# allow-list. Nor is `body` — an inbound webhook body is somebody else's
# customer data and this product is only its custodian.
LOG_KEYS: frozenset[str] = frozenset({"name", "provider", "status", "event_type", "reason"})

# The headers an `InboundWebhook` keeps. An allow-list for the same reason
# `LOG_KEYS` is one: a webhook request carries whatever the sender put on it,
# and `Authorization` and `Cookie` are exactly the two that a debugging session
# six months from now must not find sitting in a table.
KEPT_HEADERS: frozenset[str] = frozenset(
    {
        "content-type",
        "user-agent",
        "x-signature",
        "x-event-type",
        "x-request-id",
        "x-correlation-id",
        "x-delivery-id",
        # Standard Webhooks' trio, and Svix's own spelling of it. A stored
        # delivery is only replayable if the bytes AND the headers that signed
        # them survive: without these three a Resend row is a body nobody can
        # re-verify, which is precisely the row you want on the morning a
        # provider says "we sent it" and we say "we refused it".
        "webhook-id",
        "webhook-timestamp",
        "webhook-signature",
        "svix-id",
        "svix-timestamp",
        "svix-signature",
    }
)


# The headers a provider names its delivery with, in the order they are
# consulted. It began as one — `x-delivery-id`, in `KEPT_HEADERS` and stored on
# every row since this app landed, and until ADR connections-1 nothing read it,
# so a provider retry made a second row and a second hand-off and one delivery
# became two events downstream.
#
# E1′ found the same hole one layer out: a REAL ESP names its delivery with
# neither of our spellings. Resend signs with Svix, which sends `svix-id` (and
# `webhook-id`, the vendor-neutral Standard Webhooks name for the same value).
# Dedup at this door therefore did not fire for Resend at all — idempotence
# still held in the services below, but every redelivery wrote a second
# `InboundWebhook` row and a second hand-off. A tuple, not a second constant
# read in a second place: one list is what keeps the two ends in step.
#
# ORDER IS THE CONTRACT, not a preference: `x-delivery-id` first because a
# sender that names it means it, then the standard name, then the vendor's.
DELIVERY_ID_HEADER = "x-delivery-id"
WEBHOOK_ID_HEADER = "webhook-id"
SVIX_ID_HEADER = "svix-id"
DELIVERY_ID_HEADERS: tuple[str, ...] = (
    DELIVERY_ID_HEADER,
    WEBHOOK_ID_HEADER,
    SVIX_ID_HEADER,
)


def _kept_headers(headers: dict[str, str]) -> dict[str, str]:
    """The subset of an inbound request's headers worth storing."""
    return {
        str(name).lower(): str(value)
        for name, value in headers.items()
        if str(name).lower() in KEPT_HEADERS
    }


def _delivery_id(headers: dict[str, str]) -> str | None:
    """The sender's id for this delivery, or `None` when it named none.

    `None` and not `""`: it goes straight into a column whose unique constraint
    relies on Postgres treating every NULL as distinct, which is what lets
    silent providers keep a row per delivery while named ones are held to one.

    The candidate list is walked OUTSIDE the request's headers, so the answer
    is the declared priority and not whichever spelling the sender happened to
    put first — a dict order is not a contract.
    """
    lowered = {str(name).lower(): value for name, value in headers.items()}
    for candidate in DELIVERY_ID_HEADERS:
        value = lowered.get(candidate)
        if value is not None:
            return str(value)[:200] or None
    return None


@service
def create_connection(
    *,
    tenant: Tenant,
    actor: Actor,
    provider: str,
    name: str,
    credentials: dict[str, Any] | None = None,
    is_signature_v2_required: bool = True,
) -> Connection:
    """Open a connection to an external system for this tenant."""
    # **AT THE TENANT'S ROOT, not at the acting hat.** A connection holds one
    # credential that acts as the WHOLE tenant against somebody else's system,
    # so it is the tenant's configuration and never a branch's. A `require` with
    # no node resolves at the caller's hat, where an administrator of one leaf
    # holds `*` — and did open, re-credential and revoke the tenant's
    # connections. The shape is `update_tenant_settings`' (`core/services.py`)
    # and the SSO sites' (`accounts/services.py`), for the same reason.
    require(actor, "connection.create", root_organization(tenant=tenant))
    connection = Connection(
        tenant=tenant,
        provider=str(provider).strip().lower(),
        name=str(name).strip(),
        credentials=dict(credentials or {}),
        is_signature_v2_required=bool(is_signature_v2_required),
    )
    connection.connected_at = timezone.now() if connection.credentials else None
    with as_invalid():
        connection.full_clean()
    connection.save()
    _emit(CONNECTION_CREATED, tenant=tenant, connection=connection, actor=actor)
    return connection


@service
def update_credentials(
    *,
    tenant: Tenant,
    actor: Actor,
    connection: Connection,
    credentials: dict[str, Any],
) -> Connection:
    """Store new credentials for a connection, and mark it connected.

    **Merged, not replaced.** An OAuth refresh returns an access token and
    nothing else; a replace would take the webhook secret and the refresh token
    with it, and the first symptom would be inbound webhooks failing signature
    verification days later. A key is removed by `revoke_connection`, which
    removes all of them, which is the only removal that has ever been wanted.
    """
    # At the root: this row is the tenant's, not a branch's (see `create`).
    # Asked with the ROW, the question resolves at the hat exactly as a question
    # with no node does — a `Connection` names no organization, so there is
    # nothing on it for `where_of` to read.
    require(actor, "connection.update", root_organization(tenant=tenant))
    if not credentials:
        raise Invalid({"credentials": ["There is nothing to store."]})
    connection.credentials = {**(connection.credentials or {}), **credentials}
    connection.status = Connection.Status.CONNECTED
    connection.connected_at = timezone.now()
    connection.last_error = ""
    with as_invalid():
        connection.full_clean()
    connection.save(
        update_fields=["credentials", "status", "connected_at", "last_error", "updated_at"]
    )
    _emit(CONNECTION_CREDENTIALS_UPDATED, tenant=tenant, connection=connection, actor=actor)
    return connection


@service
def set_signature_scheme(
    *,
    tenant: Tenant,
    actor: Actor,
    connection: Connection,
    is_signature_v2_required: bool,
) -> Connection:
    """Choose whether this connection's inbound webhook refuses a body-only signature."""
    # At the root: this row is the tenant's, not a branch's (see `create`).
    require(actor, "connection.update", root_organization(tenant=tenant))
    if connection.is_signature_v2_required == is_signature_v2_required:
        return connection
    connection.is_signature_v2_required = is_signature_v2_required
    connection.save(update_fields=["is_signature_v2_required", "updated_at"])
    _emit(CONNECTION_SIGNATURE_SCHEME_UPDATED, tenant=tenant, connection=connection, actor=actor)
    return connection


@service
def revoke_connection(
    *,
    tenant: Tenant,
    actor: Actor,
    connection: Connection,
    reason: str = "",
) -> Connection:
    """Stop using a connection, and stop holding its credentials.

    The credentials are cleared rather than kept "in case": a revoked connection
    that still holds a live token is a credential nobody is watching. Clearing
    them also clears the webhook secret, which is what makes
    `ConnectionManager.for_webhook` refuse further deliveries — the inbound door
    closes with the outbound one, rather than a release later.
    """
    # At the root: this row is the tenant's, not a branch's (see `create`).
    require(actor, "connection.revoke", root_organization(tenant=tenant))
    connection.credentials = {}
    connection.status = Connection.Status.REVOKED
    connection.revoked_at = timezone.now()
    connection.last_error = str(reason)[:500]
    connection.save(
        update_fields=["credentials", "status", "revoked_at", "last_error", "updated_at"]
    )
    _emit(CONNECTION_REVOKED, tenant=tenant, connection=connection, actor=actor)
    return connection


#: The columns the hand-off stamps on a stored delivery. A module constant so the
#: write line has room for its `# authz-kind:` valve, which rule 13 reads on the
#: line itself — the reason is the one `record_inbound_webhook`'s docstring gives.
HANDED_OFF_FIELDS = ["status", "handed_off_to", "handed_off_at", "updated_at"]
#: What the purge may take: a hand-off nobody claimed, or a handler that answered; never a failure.
CLOSED_STATUSES = (InboundWebhook.Status.HANDED_OFF, InboundWebhook.Status.HANDLED)


@service
def record_inbound_webhook(
    *,
    tenant: Tenant,
    actor: Actor,
    connection: Connection,
    body: str,
    headers: dict[str, str],
    event_type: str = "",
) -> InboundWebhook:
    """Store a verified inbound delivery, then hand it on. **Never interpret it.**

    `verify → store → hand off → 202`. The store comes first and is not
    conditional on the hand-off working: an `apps/events` that is not in the
    tree, a dispatch that raises, a Redis that is down — each of those costs a
    retry of the hand-off, and none of them costs the event.

    The signature has already been checked by the receiver (`api.py`), which is
    the door's job: the door authenticates, the service authorizes. What this
    service will not do is parse the body or branch on it — **it does not know
    what any of this means and must not learn.** The one thing it does after
    the store is ask `providers.inbound_handler` whether some other app claimed
    this provider's deliveries, and start that handler's run on the commit
    (ADR comms-4): the handler never runs inside this request.

    **A redelivery is answered with the row it already stored** (ADR
    connections-1). Each retry carries the same `DELIVERY_ID_HEADERS` id — the
    sender's own claim that this is the same delivery.
    Where one is present and this connection already has that row, the stored
    row comes back: same response shape, no second row, and — the part that
    actually costs something — **no second hand-off**, so one provider retry
    does not become two events on the spine.

    A provider that sends no id has claimed nothing, and gets a row per
    delivery. Deduping those would be this product overruling a sender about its
    own events: two identical `payment.retried` bodies are two things that
    happened, which is also why the identity is never a hash of the body.

    **This is dedup, not a replay window** — the residual is declared in full in
    `apps.events.receivers`' module docstring. And a true race is the
    constraint's to arbitrate rather than this read's: two simultaneous copies
    can both pass the lookup, and the second loses on
    `inboundwebhook_unique_delivery_per_connection`, which a sender retries
    through. The read is what makes the ordinary case free.

    **Why the two `InboundWebhook` writes carry `# authz-kind:`** (house rule
    13): the row IS the act, and the act is the key asked on the first line.
    An `InboundWebhook` is the RECEIPT of a delivery to this connection — nobody
    creates one, a sender causes one — so there is no `inbound_webhook.create`
    capability for anybody to hold or to be refused, and minting one would be a
    second word for `connection.receive_webhook`. The kind exists for its READ
    half (`inbound_webhook.read`, the receipt log), which
    `selectors.list_inbound_webhooks` asks for.

    **And why the `require` below carries `# hat-scoped:` where the three
    services above resolve the tenant's root.** `connection` is a tenant-wide
    row — it names no organization — so a question asked *with* it resolves at
    the CALLER'S HAT, which for an administrator of one branch is that branch;
    the other three sites therefore hand `require` the tenant's root instead.
    This one has exactly one caller: the receiver in `api.py`, which arrives
    with no session and no user, verifies an HMAC over the raw body and builds
    `system_actor(tenant)` on the spot. `allows` answers a system actor at step
    one, before any node is resolved, so resolving the root here would be a
    query per delivery for an answer nothing reads — on the hottest write in
    this app. The valve is that sentence, and
    `test_the_receiver_still_stores_a_delivery_as_the_system` is that sentence
    driven rather than left as prose.
    """
    require(actor, "connection.receive_webhook", connection)  # hat-scoped: system-only caller
    delivery_id = _delivery_id(headers)
    if delivery_id is not None:
        already = (
            InboundWebhook.objects.for_tenant(tenant)
            .filter(connection=connection, delivery_id=delivery_id)
            .first()
        )
        if already is not None:
            log.info(
                "connections.webhook.redelivered",
                inbound_webhook_id=str(already.pk),
                connection_id=str(connection.pk),
                event_type=already.event_type,
            )
            return already

    received = InboundWebhook(
        tenant=tenant,
        connection=connection,
        delivery_id=delivery_id,
        body=body,
        headers=_kept_headers(headers),
        event_type=str(event_type)[:200],
    )
    with as_invalid():
        received.full_clean()
    received.save()  # authz-kind: the receipt of the act asked above (docstring)

    handed_off_to = _hand_off(received=received, actor=actor)
    if handed_off_to:
        received.status = InboundWebhook.Status.HANDED_OFF
        received.handed_off_to = handed_off_to
        received.handed_off_at = timezone.now()
        received.save(update_fields=HANDED_OFF_FIELDS)  # authz-kind: same row, same act
    _start_registered_handler(received=received)
    return received


def _start_registered_handler(*, received: InboundWebhook) -> None:
    """Start the run that hands this receipt to its provider's handler, on the commit."""
    if inbound_handler(received.connection.provider) is None:
        return
    build_id = bridge.get(bridge.WORKFLOW_ID)
    bridge.get(bridge.START_WORKFLOW_ON_COMMIT)(
        workflow=HANDLE_WORKFLOW,
        arg=HandleInboundWebhook(
            inbound_webhook_id=str(received.pk), retry_floor=retry_floor_seconds()
        ),
        tenant=received.tenant,
        id=build_id(
            tenant=received.tenant, app="connections", noun="inbound_webhook", key=str(received.pk)
        ),
    )


#: The activity's write once the handler answered: the clock it closes is the purge's.
HANDLED_FIELDS = ["status", "handed_off_at", "updated_at"]


# door: only this tree's own hands reach it — the handler run's activity, nothing else
@service
def apply_inbound_webhook(
    *, tenant: Tenant, actor: Actor, inbound_webhook_id: UUID
) -> InboundWebhook:
    """Hand one stored receipt to its provider's handler; the status says how it went.

    A raise is caught so `handler_failed` commits, and the activity raises it again for the run.
    """
    received = (
        InboundWebhook.objects.for_tenant(tenant)
        .select_related("connection")
        .get(pk=inbound_webhook_id)
    )
    # hat-scoped: system-only caller, the run's activity, as `record_inbound_webhook` asks it
    require(actor, "connection.receive_webhook", received.connection)
    handler = inbound_handler(received.connection.provider)
    if handler is None:
        return received
    try:
        with transaction.atomic():
            handler(received=received, actor=actor)
    except Exception:
        log.exception(
            "connections.webhook.handler_failed",
            inbound_webhook_id=str(received.pk),
            connection_id=str(received.connection_id),
            provider=received.connection.provider,
        )
        received.status = InboundWebhook.Status.HANDLER_FAILED
    else:
        received.status = InboundWebhook.Status.HANDLED
    received.handed_off_at = received.handed_off_at or timezone.now()
    received.save(update_fields=HANDLED_FIELDS)  # authz-kind: same row, same act
    return received


# --- The hand-off to the event spine ----------------------------------------
# `apps/events` sits beside this app rather than above it: the layer contract in
# `pyproject.toml` makes the platform apps siblings, so this app never imports
# it. Every reach across is a `core.bridge` name `apps/events/apps.py` fills —
# `EMIT`, `VERIFY_AND_STORE`, and the two verifiers `api.py` uses — looked up
# with `get()`: in production a name nobody registered is `BridgeNotRegistered`
# at the first call, never a silent second road; elsewhere the bridge's no-op
# answers `None`, and `None` is read below as "nothing took it".


def _accepts(fn: Callable[..., Any], **kwargs: Any) -> bool:
    """Whether `fn` can actually be called with these keywords.

    Checked rather than attempted, because attempting means catching `TypeError`
    around the call — which would also swallow a genuine `TypeError` raised
    inside the receiver and turn a real failure into a silent fallback.
    """
    try:
        inspect.signature(fn).bind(**kwargs)
    except (TypeError, ValueError):
        return False
    return True


def _hand_off(*, received: InboundWebhook, actor: Actor) -> str:
    """Give the stored delivery to the event spine; answers what took it, or ``""``.

    `bridge.VERIFY_AND_STORE` when it binds a verified row (ADR connections-1), else `bridge.EMIT`.
    """
    payload = {"v": V, **event_payload(InboundWebhookOut.from_orm(received))}

    receiver = bridge.get(bridge.VERIFY_AND_STORE)
    receiver_kwargs: dict[str, Any] = {
        # The row, never a tenant-and-secret pair: whatever a product's events
        # app grows here, it gets both facts from one object or it does not bind.
        "source": received.connection,
        "event_type": received.event_type,
        "body": received.body,
        "headers": received.headers,
        "verified": True,
    }
    # A hand-off that answered nothing did not happen: the bridge's no-op outside
    # production binds any keywords and answers `None`, and must never be
    # recorded as a receiver that took the delivery.
    if _accepts(receiver, **receiver_kwargs) and receiver(**receiver_kwargs) is not None:
        return "events.verify_and_store"

    emitted = bridge.get(bridge.EMIT)(
        name=WEBHOOK_RECEIVED, tenant=received.tenant, payload=payload, actor=actor
    )
    if emitted is not None:
        return "events.emit"

    log.info(
        "connections.webhook.stored_without_hand_off",
        inbound_webhook_id=str(received.pk),
        connection_id=str(received.connection_id),
    )
    return ""


def _emit(name: str, *, tenant: Tenant, connection: Connection, actor: Actor) -> None:
    """Say what happened to a connection, inside the service's transaction, in the REST shape."""
    payload = {"v": V, **event_payload(ConnectionOut.from_orm(connection))}
    bridge.get(bridge.EMIT)(name=name, tenant=tenant, payload=payload, actor=actor)


# --- Housekeeping ------------------------------------------------------------
#
# `InboundWebhook` declares itself `purged` and names the function below (ADR
# core-13, house rule 31). The declaration and the machine that keeps it are
# written in one commit on purpose: a table shaped for a sweeper with no sweeper
# is the poller that was never built, and it looks exactly like a table that is
# finished.


# door: only this tree's own hands reach this; the scheduled purge activity's own step
@service
def purge_inbound_webhooks(*, before: datetime, tenant: None) -> Swept:
    """Drop inbound webhooks handed off before `before`. Returns how many went.

    **What it returns is a `Swept`, not a bare count** (ADR core-22, L6). The
    number is unchanged; what the typed result adds is the POPULATION — the
    swept model's label, which `core.service._object_of` reads off
    `audit_object` and files as `object_type` with a NULL `object_id`. A sweep
    acts on a population and not on an object, and a row that named one
    arbitrary victim out of nine hundred would read as a single deletion
    somebody could go and look up.

    **`tenant` is declared and is always `None`, and that is the audit row.**
    `@service` writes an `AuditEntry` for every service that DECLARES a `tenant`
    (ADR core-8), and `None` is that ADR's named population: the deployment's
    own actions, the ones a compliance trail exists for. So a purge that ran and
    took eleven thousand of somebody's stored deliveries leaves a row saying so,
    with `tenant=None` and `actor=None` — the platform shape, reachable by no
    tenant's `for_tenant` read. The sibling precedent is
    `accounts.sync_workforce_identity_config`, whose `tenant` is also always
    `None` for the same reason. A retention sweep with no record of having run
    is the second half of the poller that was never built: nobody can tell it
    apart from one that never fired.

    **Only closed rows (`CLOSED_STATUSES`), and the clock is the hand-off's.** A `received` row
    is an open promise — the hand-off has not happened, or has not been retried
    to a conclusion — and a purge that swept by `created_at` would destroy a
    replayable delivery before its workflow ever consumed it. That is the one
    failure this function exists not to have, so the filter is a status AND a
    timestamp rather than an age. `handed_off_at` is written in the same
    `save()` as the status (`record_inbound_webhook`), so a row can never be
    handed off with a null clock; a null one is excluded by the comparison
    anyway, which is the belt.

    Idempotent by construction — it deletes by age, so a second run in the same
    window removes nothing.

    # authz: deployment housekeeping, run by a schedule as the system. It names
    # no tenant and resolves no actor: it is scoped by the hand-off clock and it
    # deletes rows rather than returning any, so there is nobody whose reach
    # could be exceeded and nothing for a caller to read.
    """
    # rule-8: the population is every tenant's processed deliveries at once,
    # which is what a retention sweep is — there is no tenant to scope by
    # because the sweep is not acting for one. Nothing crosses a tenant
    # boundary: the rows are deleted, never returned, and the only value that
    # leaves is a count.
    deleted, _ = InboundWebhook.objects.filter(
        status__in=CLOSED_STATUSES, handed_off_at__lt=before
    ).delete()
    return Swept(label=InboundWebhook._meta.label, count=int(deleted))
