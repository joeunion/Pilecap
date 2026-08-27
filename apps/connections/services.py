"""Writes for the connections app.

Every function is `@service` — keyword-only, atomic, traced, logged and audited.
Every one that changes a connection calls `authz.require` first, because the
service authorizes and the door does not.

**The load-bearing line in this module is the one that is not here.**
`LOG_KEYS` does not contain `credentials`, and `core.service.redact` is an
allow-list, so the credential a caller passes comes out as `[redacted]` in the
`.called` log line and in the `AuditEntry.input` — automatically, on every
service in this file, including ones somebody adds later. A blocklist would
work until the day somebody named a parameter `token` instead.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
from collections.abc import Callable
from datetime import datetime
from typing import Any

from django.apps import apps as django_apps
from django.db import transaction
from django.utils import timezone

from apps.connections.events import (
    CONNECTION_CREATED,
    CONNECTION_CREDENTIALS_UPDATED,
    CONNECTION_REVOKED,
    WEBHOOK_RECEIVED,
    V,
)
from apps.connections.models import Connection, InboundWebhook
from apps.connections.providers import inbound_handler
from apps.connections.schemas import ConnectionOut, InboundWebhookOut
from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.exceptions import Invalid, as_invalid
from apps.core.log import get_logger
from apps.core.models import Tenant
from apps.core.service import service
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
) -> Connection:
    """Open a connection to an external system for this tenant."""
    require(actor, "connection.create")
    connection = Connection(
        tenant=tenant,
        provider=str(provider).strip().lower(),
        name=str(name).strip(),
        credentials=dict(credentials or {}),
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
    require(actor, "connection.update", connection)
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
    require(actor, "connection.revoke", connection)
    connection.credentials = {}
    connection.status = Connection.Status.REVOKED
    connection.revoked_at = timezone.now()
    connection.last_error = str(reason)[:500]
    connection.save(
        update_fields=["credentials", "status", "revoked_at", "last_error", "updated_at"]
    )
    _emit(CONNECTION_REVOKED, tenant=tenant, connection=connection, actor=actor)
    return connection


@service
def record_failure(
    *,
    tenant: Tenant,
    actor: Actor,
    connection: Connection,
    reason: str,
) -> Connection:
    """Mark a connection as failing, with a reason a human can read.

    Called by whatever made the outbound call — an activity, in the ordinary
    case. `reason` is a summary, never a response body and never a header: an
    upstream 401 very often echoes the token straight back.
    """
    require(actor, "connection.update", connection)
    connection.status = Connection.Status.ERROR
    connection.last_error = str(reason)[:500]
    connection.save(update_fields=["status", "last_error", "updated_at"])
    return connection


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
    this provider's deliveries, and call it (ADR comms-4). That call is inside
    this transaction and inside this request, so a handler owes the same
    promise the spine hand-off does: be quick, and put anything that waits or
    retries in a workflow.

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
    """
    require(actor, "connection.receive_webhook", connection)
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
    received.save()

    handed_off_to = _hand_off(received=received, actor=actor)
    if handed_off_to:
        received.status = InboundWebhook.Status.HANDED_OFF
        received.handed_off_to = handed_off_to
        received.handed_off_at = timezone.now()
        received.save(update_fields=["status", "handed_off_to", "handed_off_at", "updated_at"])
    _hand_to_registered_handler(received=received, actor=actor)
    return received


def _hand_to_registered_handler(*, received: InboundWebhook, actor: Actor) -> None:
    """Give the stored delivery to whichever app claimed this provider slug.

    **After** the store and after the spine hand-off, and never instead of
    either: those two are what make the delivery survivable, and this is what
    makes it *mean* something. A provider with no registered handler is the
    ordinary case and is silent.

    **A raising handler is caught and logged, and the 202 stands.** That is the
    whole reason the store comes first. The receipt row is the durability — a
    human can replay it, and the sender will retry anyway — so turning one
    app's bad afternoon into a 500 on the shared inbound door would take every
    *other* provider's deliveries down with it. `Exception` rather than a
    narrower catch on purpose: this service cannot know what a handler it has
    never seen might raise, and a `BaseException` (a cancellation, a
    `KeyboardInterrupt`) still propagates.

    **The savepoint is what makes that promise true rather than nearly true.**
    Catching an exception is not enough on Postgres: a handler whose failure was
    a database error leaves the enclosing transaction aborted, and the receipt
    this service just wrote would then fail to commit — a 500 arriving by the
    back door, on the one route that must not have one. `atomic()` here rolls
    the handler's work back to the point before it ran and leaves the receipt
    intact.
    """
    handler = inbound_handler(received.connection.provider)
    if handler is None:
        return
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


# --- The hand-off to the event spine ----------------------------------------
# `apps/events` sits beside this app rather than above it: the layer contract in
# `pyproject.toml` makes the platform apps siblings, and a template has to keep
# running — and this app's tests have to keep passing — in a tree where
# `apps/events` has not landed. So the reach across is a **runtime lookup
# through the app registry, never an import**, and its absence is an ordinary
# branch rather than an ImportError at module load.


def _events_attr(module: str, name: str) -> Any:
    """`apps.events.<module>.<name>`, if the app is installed and has it, else `None`.

    The one reach across the sibling border, and the only one this app has.
    `api.py` uses it too, for the freshness half of the inbound signature check:
    the window and the parse grammar for `X-Signature-V2` belong to
    `apps.events.receivers`, which is where the scheme is *sent* from, and a
    second copy of a five-minute number is a second copy that drifts. A value
    and not only a callable, because a tolerance is a `timedelta`.
    """
    if not django_apps.is_installed("apps.events"):
        return None
    module_name = f"apps.events.{module}"
    try:
        if importlib.util.find_spec(module_name) is None:
            return None
        return getattr(importlib.import_module(module_name), name, None)
    except ImportError:  # pragma: no cover - a broken sibling app, not our failure
        return None


def _events_callable(module: str, name: str) -> Callable[..., Any] | None:
    """`apps.events.<module>.<name>`, if the app is installed and it is callable."""
    found = _events_attr(module, name)
    return found if callable(found) else None


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
    """Give the stored delivery to the event spine. Returns what took it, or ``""``.

    Two interfaces, in order of specificity:

    1. `apps.events.receivers.verify_and_store` — the inbound receiver, if the
       events app exposes one whose signature accepts what we have;
    2. `apps.events.services.emit` — the documented spine interface
       (`build-contract.md`), which fans out to the tenant's subscribers.

    **Against the spine as it landed, (1) does not bind, and that is right.**
    Its `verify_and_store(request_body, signature, *, source, name)` is a
    *door-side* helper for a route that still has the raw bytes and an unchecked
    signature in hand; by the time this function is reached the signature has
    been checked — by `api.receive_webhook`, against this connection's own
    secret — and the body stored, here, by the service above. Handing it over
    again would verify twice and store twice. So the live path is (2), and it is
    a decision the guard makes rather than a `TypeError` caught around a call —
    see `_accepts`. The first branch stays because "an events app with a
    receiver shaped for us" is a thing a product may well grow, and a checked
    signature costs nothing to keep offering.

    **The narrowing (ADR connections-1) is why the probe now offers the row.**
    `verify_and_store` used to take `secret` and `tenant` as two loose values,
    and this — its one discovered caller — was exactly the place a builder would
    eventually pair connection A's secret with tenant B. It takes `source=` now:
    one object, carrying both, and `received.connection` is the only thing this
    function could sensibly pass. The mismatch is not refused; it cannot be
    written.

    Nothing else in this app knows `apps.events` exists.
    """
    payload = {"v": V, **InboundWebhookOut.from_orm(received).model_dump(mode="json")}

    receiver = _events_callable("receivers", "verify_and_store")
    receiver_kwargs: dict[str, Any] = {
        # The row, never a tenant-and-secret pair: whatever a product's events
        # app grows here, it gets both facts from one object or it does not bind.
        "source": received.connection,
        "event_type": received.event_type,
        "body": received.body,
        "headers": received.headers,
        "verified": True,
    }
    if receiver is not None and _accepts(receiver, **receiver_kwargs):
        receiver(**receiver_kwargs)
        return "events.verify_and_store"

    emit = _events_callable("services", "emit")
    if emit is not None:
        emit(name=WEBHOOK_RECEIVED, tenant=received.tenant, payload=payload, actor=actor)
        return "events.emit"

    log.info(
        "connections.webhook.stored_without_hand_off",
        inbound_webhook_id=str(received.pk),
        connection_id=str(received.connection_id),
    )
    return ""


def _emit(name: str, *, tenant: Tenant, connection: Connection, actor: Actor) -> None:
    """Say that something happened, if there is anything listening yet.

    Called inside the service's transaction (the `@service` decorator opens it),
    so the outbox row and the business row land together or not at all.
    """
    emit = _events_callable("services", "emit")
    if emit is None:
        return
    payload = {"v": V, **ConnectionOut.from_orm(connection).model_dump(mode="json")}
    # `name=`: the spine's `emit` is `@service` and therefore keyword-only,
    # including the name (house rule 13).
    emit(name=name, tenant=tenant, payload=payload, actor=actor)


# --- Housekeeping ------------------------------------------------------------
#
# `InboundWebhook` declares itself `purged` and names the function below (ADR
# core-13, house rule 31). The declaration and the machine that keeps it are
# written in one commit on purpose: a table shaped for a sweeper with no sweeper
# is the poller that was never built, and it looks exactly like a table that is
# finished.


@service
def purge_inbound_webhooks(*, before: datetime, tenant: Tenant | None) -> Swept:
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

    **Only handed-off rows, and the clock is the hand-off's.** A `received` row
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
        status=InboundWebhook.Status.HANDED_OFF, handed_off_at__lt=before
    ).delete()
    return Swept(label=InboundWebhook._meta.label, count=int(deleted))
