"""The connections door: CRUD, the OAuth round trip, and the one signed inbound receiver.

The receiver's credential is its signature (`_signature_verified`): verify, store, hand off, 202.
# why-not `from __future__ import annotations`: ninja reads the route signatures at import.
"""

import hashlib
import secrets
from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.core.cache import cache
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from ninja import Query, Router, Status
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH
from apps.connections import selectors, services
from apps.connections.models import Connection
from apps.connections.providers import get_provider
from apps.connections.providers import webhook_verifier as get_webhook_verifier
from apps.connections.schemas import (
    ConnectionFilter,
    ConnectionIn,
    ConnectionOut,
    CredentialsIn,
    OAuthStartIn,
    OAuthStartOut,
    RevokeIn,
    SignatureSchemeIn,
    WebhookAcceptedOut,
)
from apps.core import bridge, context
from apps.core.actor import system_actor
from apps.core.api import CursorPagination, ordered_by
from apps.core.api.acting import acting
from apps.core.api.docs import Tag, refuses
from apps.core.exceptions import (
    DomainError,
    Forbidden,
    Invalid,
    InvalidSignature,
    Remedy,
    register_refusal,
)
from apps.core.middleware import (
    AUTHORIZATION_HEADER,
    ORG_HEADER,
    TENANT_HEADER,
)
from apps.core.requests import TenantRequest

#: What `?ordering=` may name, and nothing else.
ORDERING = ("created_at", "updated_at", "name", "provider", "status")

#: Where the OAuth `state` waits between start and callback: the cache, because the two
#: halves may not share a session cookie, and the entry must expire whether or not anyone returns.
STATE_CACHE_PREFIX = "connections:oauth:state:"
STATE_TTL_SECONDS = 600

#: The inbound signature headers; `X-Signature-V2` is the envelope this template's own signer sends.
SIGNATURE_HEADER = "X-Signature"
SIGNATURE_PREFIX = "sha256="
EVENT_TYPE_HEADER = "X-Event-Type"
#: The name only: the verifiers and the window are `apps.events.receivers`', via `core.bridge`.
SIGNATURE_V2_HEADER = "X-Signature-V2"

TAGS = {
    "connections": Tag(
        "Outside systems",
        "This tenant's links to outside systems: registering a provider, the OAuth "
        "round trip, storing and revoking credentials, and the signed inbound "
        "webhook the provider calls back on. Credentials are stored encrypted and "
        "no response here ever carries one out.",
        plane="administrative",
        plane_note=(
            "this tenant's links to outside systems, the credentials behind them, and the signed "
            "webhooks those systems send in."
        ),
    ),
}

router = Router(tags=["connections"], auth=API_AUTH)


# --- The connections themselves ----------------------------------------------


@router.get("/", response=list[ConnectionOut], url_name="connection-list")
@paginate(CursorPagination)
def list_connections_route(
    request: TenantRequest,
    filters: Query[ConnectionFilter],
    ordering: str = "-created_at",
) -> QuerySet[Connection]:
    """List connections

    List this tenant's connections to outside systems, newest first.

    Narrow with `provider` (exact), `status` (exact) or `name` (case-insensitive
    substring). Sort with `ordering`, which accepts `created_at`, `updated_at`,
    `name`, `provider` or `status`, each optionally prefixed with `-`; the
    default is `-created_at` and any other value is refused with `400 invalid`.
    Paged with `?cursor=` and `?limit=` (50 by default, 200 at most); the body
    is `{"items": [...], "has_more": ..., "next_cursor": ...}`, and `count`
    arrives only with `?include_count=true`.

    **No stored credential is ever in the response.** There is no field on the
    connection shape that carries one, on this route or any other in this API,
    so there is no way to read back a key you sent. `has_credentials` tells you
    whether one is stored; `status` is `connected` or `revoked` (`error` is
    reserved and unset), and `last_error` is the reason given at revocation.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 no_acting_scope` — the request resolved no tenant. Send `X-Tenant`
      naming one you belong to.
    * `403 forbidden` — your role here does not let you read connections. A
      role with no read of this kind reads none of them: ask an administrator
      for the permission, or act under an organization where you hold it.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    connections: QuerySet[Connection] = selectors.list_connections(tenant=tenant, actor=actor)
    connections = filters.filter(connections)
    return ordered_by(connections, ordering, allowed=ORDERING, default="-created_at")


@router.post("/", response={201: ConnectionOut}, url_name="connection-create")
def create_connection_route(request: TenantRequest, payload: ConnectionIn) -> Status[Connection]:
    """Create a connection

    Register a link between this tenant and one outside provider.

    Send `provider` (the provider's short name — letters, digits, `-` and `_`)
    and `name` (yours, to tell two connections to the same provider apart).

    Its inbound webhook accepts only `X-Signature-V2` unless you send
    `is_signature_v2_required: false`, for a provider that cannot timestamp a request.

    There are two ways to supply the credentials, and you pick one here:

    * **A static API key or secret** — put it in `credentials` now, as an
      object. The connection comes back ready to use.
    * **OAuth** — leave `credentials` out. The connection is created empty, and
      you then call `POST /api/v1/connections/{connection_id}/oauth/start/`,
      send the user to the URL it returns, and let the provider redirect back to
      the callback, which fills the credentials in.

    Either way the credentials are stored encrypted and **no response anywhere
    in this API carries one back out**. There is no field on the connection
    shape that could; `has_credentials` is how you tell whether one is stored.

    Answers `201` with the connection.

    Refusals you can get here:

    * `400 invalid` — a field is missing or malformed. `errors` names the
      fields and nothing is created.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `403 no_acting_scope` — the request resolved no tenant. Send `X-Tenant`
      naming one you belong to.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    connection = services.create_connection(
        tenant=tenant,
        actor=actor,
        provider=payload.provider,
        name=payload.name,
        credentials=payload.credentials,
        is_signature_v2_required=payload.is_signature_v2_required,
    )
    return Status(201, connection)


# Declared before `/{connection_id}/…`, so the fixed path wins even if that parameter widens.
@router.get("/oauth/callback/", response=ConnectionOut, url_name="connection-oauth-callback")
# The connection comes off the stored state, so `not_found` is real and underivable (rule 41).
@refuses("invalid", "forbidden", "no_acting_scope", "not_found", "rate_limited")
def oauth_callback(request: TenantRequest, code: str, state: str) -> Connection:
    """Complete an OAuth handshake

    The OAuth redirect target: exchange the provider's code for credentials.

    **You do not call this yourself.** The provider's authorization page
    redirects the user's browser here, carrying the `code` and `state` query
    parameters, after they approve the connection. You reach this point by
    calling `POST /api/v1/connections/{connection_id}/oauth/start/` and sending
    the user to the `authorization_url` it gave you.

    On success the credentials are stored against the connection this handshake
    was started for, and the answer is `200` with that connection (without the
    credentials — nothing here returns those).

    **Each `state` works exactly once**, and expires ten minutes after it was
    issued. Loading this URL a second time — from a browser history entry, a
    proxy log, a retry — answers `400` and stores nothing. If that happens,
    start a fresh handshake; there is no way to reuse a spent state.

    The browser session that arrives here must belong to the same tenant that
    started the handshake, or the answer is `400`.

    Refusals you can get here:

    * `400 invalid` — the `state` is unknown, has expired, has already been
      used, or belongs to another tenant. Start the handshake again.
    * `403 forbidden` — storing credentials changes the connection, and you
      are not an owner or an administrator of the tenant. This is where a
      handshake a member started is refused; nothing is stored.
    * `403 no_acting_scope` — the request resolved no tenant. Send `X-Tenant`
      naming one you belong to.
    * `404 not_found` — the connection the `state` names no longer exists.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    stored = _consume_state(state)
    if stored is None:
        raise Invalid({"state": ["That OAuth state is unknown or has expired."]})
    if str(stored.get("tenant_id")) != str(tenant.pk):
        raise Invalid({"state": ["That OAuth state belongs to another tenant."]})

    connection = selectors.get_connection(
        tenant=tenant, connection_id=UUID(str(stored["connection_id"])), actor=actor
    )
    provider = get_provider(connection.provider)
    credentials = provider.exchange_code(
        connection=connection,
        code=code,
        redirect_uri=str(stored.get("redirect_uri") or ""),
    )
    return services.update_credentials(
        tenant=tenant, actor=actor, connection=connection, credentials=credentials
    )


@router.get("/{connection_id}/", response=ConnectionOut, url_name="connection-detail")
def retrieve_connection(request: TenantRequest, connection_id: UUID) -> Connection:
    """Retrieve a connection

    Fetch one connection by id.

    Answers with its `provider`, your `name` for it, its `status`,
    `has_credentials`, the reason given when it was revoked (`last_error`,
    empty string when there is none), and when it was connected or revoked.

    The stored credentials are not in the answer and cannot be read back through
    any route here. A connection belonging to another tenant, or an id that
    names nothing, answers `404 not_found`.

    Refusals you can get here:

    * `404 not_found` — no connection of this tenant's has that id.
    * `403 no_acting_scope` — the request resolved no tenant. Send `X-Tenant`
      naming one you belong to.
    * `403 forbidden` — your role here does not let you read connections. A
      role with no read of this kind reads none of them: ask an administrator
      for the permission, or act under an organization where you hold it.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    return selectors.get_connection(tenant=tenant, connection_id=connection_id, actor=actor)


@router.post(
    "/{connection_id}/credentials/",
    response=ConnectionOut,
    url_name="connection-credentials",
)
def update_credentials_route(
    request: TenantRequest, connection_id: UUID, payload: CredentialsIn
) -> Connection:
    """Set connection credentials

    Set or update a connection's credentials directly.

    This is the route for providers that hand you a static API key or secret,
    rather than one you connect to over OAuth. Send `credentials` as an object
    with at least one key in it; an empty object is refused with `400 invalid`.

    What you send is **merged** into what is already stored, key by key — a key
    you do not mention keeps its current value. There is no route that reads the
    result back, so keep your own copy of anything you cannot regenerate.

    A successful call also marks the connection `connected` and clears
    `last_error`, so this is how you bring a revoked connection back with a
    new key.

    Answers `200` with the connection (credentials not included).

    Refusals you can get here:

    * `400 invalid` — the credentials were not the shape this provider takes.
      `errors` names the fields and nothing is stored.
    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `404 not_found` — no connection of this tenant's has that id.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    connection = selectors.get_connection(tenant=tenant, connection_id=connection_id, actor=actor)
    return services.update_credentials(
        tenant=tenant, actor=actor, connection=connection, credentials=payload.credentials
    )


@router.post(
    "/{connection_id}/signature-scheme/",
    response=ConnectionOut,
    url_name="connection-signature-scheme",
)
def set_signature_scheme_route(
    request: TenantRequest, connection_id: UUID, payload: SignatureSchemeIn
) -> Connection:
    """Choose the webhook signature scheme

    Send `is_signature_v2_required`: `true` (new connections) refuses a delivery signed only
    with `X-Signature`; `false` (connections older than 2.5.0) also accepts it. Answers `200`.

    Refusals: `403 forbidden` (not an owner or administrator), `404 not_found`, `422 invalid_body`.
    """
    actor, tenant = acting(request)
    connection = selectors.get_connection(tenant=tenant, connection_id=connection_id, actor=actor)
    return services.set_signature_scheme(
        tenant=tenant,
        actor=actor,
        connection=connection,
        is_signature_v2_required=payload.is_signature_v2_required,
    )


@router.post("/{connection_id}/revoke/", response=ConnectionOut, url_name="connection-revoke")
def revoke_connection_route(
    request: TenantRequest, connection_id: UUID, payload: RevokeIn
) -> Connection:
    """Revoke a connection

    Stop using a connection, and record why.

    Send an optional `reason` — up to 500 characters, and anything longer is cut
    rather than refused. It comes back on the connection as `last_error`, so
    whoever finds the integration switched off later can read what happened.

    This is not a delete. The connection stays, its `status` becomes `revoked`
    and `revoked_at` is set, so the history of what you were connected to
    survives.

    **The stored credentials are destroyed, and this API cannot give them back.**
    That includes the secret this connection's inbound webhook is signed with, so
    deliveries the provider sends after this stop being accepted. Reconnecting
    means supplying credentials again — a fresh OAuth handshake, or a new
    `POST .../credentials/`.

    Answers `200` with the connection.

    Refusals you can get here:

    * `403 forbidden` — you are not an owner or an administrator of the
      tenant.
    * `404 not_found` — no connection of this tenant's has that id.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    connection = selectors.get_connection(tenant=tenant, connection_id=connection_id, actor=actor)
    return services.revoke_connection(
        tenant=tenant, actor=actor, connection=connection, reason=payload.reason
    )


# --- OAuth: start --------------------------------------------------------------


@router.post(
    "/{connection_id}/oauth/start/",
    response=OAuthStartOut,
    url_name="connection-oauth-start",
)
def oauth_start(
    request: TenantRequest, connection_id: UUID, payload: OAuthStartIn
) -> OAuthStartOut:
    """Start an OAuth handshake

    Begin an OAuth handshake, and get the URL to send the user to.

    Call this on a connection you already created (with `POST
    /api/v1/connections/` and no credentials). Optionally send `redirect_uri` to
    say where the provider should return the browser; omit it and this API's own
    callback is used, which is the path that works out of the box.

    You get back `authorization_url` — send the user's browser there — plus the
    `state` that ties the return trip to this call and `expires_in`, the seconds
    you have before that state stops working (600). Nothing is stored against
    the connection yet: if the user closes the tab, no credentials appear and
    nothing needs cleaning up. You can simply call this again.

    Answers `200`. A connection id your tenant does not hold answers
    `404 not_found`.

    **Starting a handshake is not role-gated; finishing one is.** This call
    stores nothing against the connection, so any member of the tenant may ask
    for an authorization URL. The credentials land at
    `GET /api/v1/connections/oauth/callback/`, which asks the same permission
    `POST /api/v1/connections/{connection_id}/credentials/` asks — so a member
    who starts a handshake is refused on the way back, with nothing stored.
    Start one as the person who will finish it.

    Refusals you can get here:

    * `400 invalid` — this connection's provider is not one this deployment
      has OAuth configured for.
    * `403 no_acting_scope` — the request resolved no tenant. Send `X-Tenant`
      naming one you belong to.
    * `404 not_found` — no connection of this tenant's has that id.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = acting(request)
    connection = selectors.get_connection(tenant=tenant, connection_id=connection_id, actor=actor)
    provider = get_provider(connection.provider)

    redirect_uri = payload.redirect_uri or request.build_absolute_uri(
        reverse("api:connection-oauth-callback")
    )
    state = secrets.token_urlsafe(32)
    cache.set(
        _state_key(state),
        {
            "connection_id": str(connection.pk),
            "tenant_id": str(tenant.pk),
            "redirect_uri": redirect_uri,
        },
        STATE_TTL_SECONDS,
    )
    return OAuthStartOut(
        connection_id=connection.pk,
        authorization_url=provider.authorization_url(
            connection=connection, state=state, redirect_uri=redirect_uri
        ),
        state=state,
        expires_in=STATE_TTL_SECONDS,
    )


def _state_key(state: str) -> str:
    return f"{STATE_CACHE_PREFIX}{hashlib.sha256(state.encode('utf-8')).hexdigest()}"


def _consume_state(state: str) -> dict[str, Any] | None:
    """Take the parked state once: of two racing callbacks, only the winning delete consumes."""
    key = _state_key(state)
    stored = cache.get(key)
    if not cache.delete(key):
        return None
    return dict(stored) if isinstance(stored, dict) else None


# --- The inbound receiver ------------------------------------------------------


def signature_v2_tolerance() -> timedelta | None:
    """How stale an `X-Signature-V2` delivery may be: `apps.events.receivers`' number, or `None`."""
    tolerance = bridge.get(bridge.SIGNATURE_V2_TOLERANCE)()
    return tolerance if isinstance(tolerance, timedelta) else None


def _signature_verified(*, connection: Connection, body: bytes, headers: dict[str, str]) -> bool:
    """Did the sender prove it is the sender — one scheme decides, and none is skipped.

    Order: the provider's registered verifier, then `X-Signature-V2` if offered, then `X-Signature`.
    A verifier answering `None` has no opinion; the bridge's no-op `None` is a refusal (`is True`).
    A verified `X-Signature` on a connection that requires v2 raises `TimestampedSignatureRequired`.
    """
    verifier = get_webhook_verifier(connection.provider)
    if verifier is not None:
        verdict = verifier(connection=connection, body=body, headers=headers)
        if verdict is not None:
            return verdict
    offered = headers.get(SIGNATURE_V2_HEADER, "")
    if offered:
        # why-not a V1 fallback: a replayer would drop the header that carries the window.
        verified_v2 = bridge.get(bridge.SIGNATURE_V2_MATCHES)(
            secret=connection.webhook_secret, body=body, signature=offered
        )
        return verified_v2 is True
    # Contraction trigger: `Connection.is_signature_v2_required`'s contract line.
    verified = bridge.get(bridge.SIGNATURE_MATCHES)(
        secret=connection.webhook_secret,
        body=body,
        signature=headers.get(SIGNATURE_HEADER, ""),
    )
    # Checked after the digest: only a holder of the secret learns which scheme is required.
    if verified is True and connection.is_signature_v2_required:
        raise TimestampedSignatureRequired()
    return verified is True


register_refusal(
    code="timestamped_signature_required",
    boundary="door",
    remedy=(
        "A sender holding the connection's secret signed with the body-only X-Signature scheme, "
        "and this connection requires X-Signature-V2. Sign with X-Signature-V2, or, for a "
        "provider that cannot timestamp a request, set the connection's "
        "is_signature_v2_required to false through its signature-scheme route."
    ),
    fact=(
        "This connection accepts only the timestamped X-Signature-V2 scheme, and this "
        "delivery carried only the body-only X-Signature. Nothing was stored."
    ),
    remedies=(
        Remedy(
            "Sign the delivery with X-Signature-V2: a timestamp, a full stop and the raw body",
            f"header:{SIGNATURE_V2_HEADER}",
        ),
    ),
    status=401,
)


class TimestampedSignatureRequired(DomainError):
    """A correct body-only signature on a connection that requires `X-Signature-V2`."""

    code = "timestamped_signature_required"
    default_detail = "This connection requires X-Signature-V2; X-Signature alone is refused."


register_refusal(
    code="signed_door_takes_no_address",
    boundary="door",
    remedy=(
        "A client that drives every door sent its bearer or an addressing header to the "
        "signed inbound receiver. The receiver reads neither: the signature over the body "
        "is the credential and the connection in the URL names the tenant. Remove the "
        "header from this one call and send the same signed bytes."
    ),
    fact=(
        "this door takes no bearer and no addressing header — the signature is the "
        "credential; send the signed bytes bare"
    ),
    remedies=(
        Remedy("Send no Authorization header to this door", f"header:{AUTHORIZATION_HEADER}"),
        Remedy("Send no X-Tenant header to this door", f"header:{TENANT_HEADER}"),
        Remedy("Send no X-Org header to this door", f"header:{ORG_HEADER}"),
    ),
    status=403,
)


class SignedDoorTakesNoAddress(Forbidden):
    """A bearer or an addressing header sent to the signed inbound receiver."""

    code = "signed_door_takes_no_address"


def _takes_no_address(sent: Sequence[str]) -> SignedDoorTakesNoAddress:
    """The refusal, naming the headers that were sent."""
    named = ", ".join(f"`{name}`" for name in sent)
    return SignedDoorTakesNoAddress(
        f"This door takes no bearer and no addressing header, and this request sent "
        f"{named}. The signature is the credential; send the signed bytes bare."
    )


@router.post(
    "/{connection_id}/webhook/",
    # rule-3: signature-verified inbound webhook. There is no user and no token
    # on this request — it comes from somebody else's server — so the credential
    # is the HMAC over the raw body, checked below with `compare_digest` before
    # anything is read or written. This is the one `auth=None` in the app and
    # the shape `rules.yaml` allow-lists.
    auth=None,
    response={202: WebhookAcceptedOut},
    url_name="connection-webhook",
)
@refuses(
    "conflict",
    "database_unavailable",
    "idempotency_key_reuse",
    "in_progress",
    "invalid_signature",
    "rate_limited",
    "signed_door_takes_no_address",
    "timestamped_signature_required",
)
# rule-41: TenantMiddleware answers this code before routing, declared in `apps.py` ready().
def receive_webhook(request: HttpRequest, connection_id: UUID) -> Status[WebhookAcceptedOut]:
    """Receive a provider webhook

    Where a provider POSTs its webhook deliveries for one connection.

    **The provider calls this, not you**, and it takes no token and no session.
    What stands in for a credential is a signature over the exact bytes of the
    request body, keyed on this connection's webhook secret. There are two
    schemes, and the one to send is the first:

    * **`X-Signature-V2: t=<seconds>,sha256=<hex>`** — the preferred scheme.
      `t` is the moment you signed, in whole seconds since the Unix epoch, and
      the hex is an HMAC-SHA256 over the string made of `t`, a full stop, and
      the raw body bytes. The timestamp is covered by the signature, so it
      cannot be edited on the way, and a delivery whose `t` is more than
      5 minutes away from this server's clock is refused however correct the
      signature is. That window is what stops a delivery captured off the wire
      from being sent again tomorrow.
    * `X-Signature: sha256=<hex>` — HMAC-SHA256 over the raw body bytes and
      nothing else. `sha256=<hex>` or the bare hex are both accepted, in either
      case. No freshness: those bytes verify as long as the secret lives, so it
      is accepted only where the connection's `is_signature_v2_required` is
      `false`, and refused with `401 timestamped_signature_required` everywhere else.

    **Send one, not a hopeful pair.** When `X-Signature-V2` is present it is the
    only header consulted: a correct `X-Signature` beside a stale or wrong
    `X-Signature-V2` is refused. A scheme a sender can be stepped down from
    would give you nothing, because anyone replaying a captured delivery would
    simply drop the header that carries the window.

    Send `X-Event-Type` too if you have one; it is recorded against the
    delivery. Give the provider the full URL of this route, connection id and
    all.

    **`202` means accepted, not processed.** The body is stored and handed on to
    be worked through afterwards, and this answer says only that it is safely
    ours. Do not read a 202 as "the effects have happened".

    Refusals you can get here:

    * `401 invalid_signature` — the signature did not check out, or there is
      no connection with that id. Those answer identically and deliberately: whether the
      connection exists, whether it has a secret, what the expected signature
      was, and whether a `t` you sent was outside the 5 minutes are all
      withheld. Check that you are signing the raw body bytes with the right
      secret, that your `t` is current, and that you have not re-serialized the
      JSON on the way.
    * `401 timestamped_signature_required` — a correct `X-Signature` on a connection
      that accepts only `X-Signature-V2`.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    Retry on anything other than a `202`; nothing was stored.
    """
    connection = selectors.get_connection_for_webhook(connection_id=connection_id)
    body = request.body
    # One answer for no such connection and a bad signature: neither existence nor the secret leaks.
    # does-not-cover: an unknown id skips the HMAC, so timing may tell the two branches apart.
    if connection is None or not _signature_verified(
        connection=connection, body=body, headers=dict(request.headers)
    ):
        raise InvalidSignature()

    tenant = connection.tenant
    # No user and no session arrived, so the door binds its own context.
    context.bind(door="webhook", tenant_id=str(tenant.pk), actor_kind="system")
    received = services.record_inbound_webhook(
        tenant=tenant,
        actor=system_actor(tenant),
        connection=connection,
        body=body.decode("utf-8", "replace"),
        headers=dict(request.headers),
        event_type=request.headers.get(EVENT_TYPE_HEADER, ""),
    )
    return Status(202, WebhookAcceptedOut(id=received.pk, status=received.status))
