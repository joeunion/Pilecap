"""The connections API: the CRUD door, the OAuth handshake, and the one receiver.

Three kinds of route live here and they have three different authentication
stories, which is the interesting part of this module:

* the **CRUD routes** are ordinary: `API_AUTH`, tenant from the request, writes
  through services;
* the **OAuth routes** are ordinary too — the person clicking "connect" is
  signed in, and the callback lands in the same browser session. The `state`
  parameter is not authentication; it is what proves the *callback* belongs to
  the *start*, and it is single-use;
* the **inbound receiver** has no user at all. It is the one `auth=None` in this
  app, it is on `rules.yaml`'s allow-list for exactly this shape, and what
  stands in for a credential is an HMAC keyed on the connection's own secret —
  over a timestamp and the raw body (`X-Signature-V2`, the preferred scheme and
  the one this template also *sends*, whose signed timestamp is what closes the
  replay window), or over the raw body alone (`X-Signature`, kept for senders
  that cannot timestamp a request) — or, since E1′, whatever scheme the app that
  owns this provider's deliveries registered instead
  (`providers.register_webhook_verifier`). One route, one credential per
  request, and never a request that goes unchecked: `_verified` below is the
  whole of that decision.

The receiver does four things and stops: verify, store, hand off, 202. It never
parses the body. A handler that runs inline is a handler that loses the delivery
the first time the sender's timeout is shorter than ours
(`architecture.md`, "Rejected, and why").
"""

# NOTE: no `from __future__ import annotations` here, for the same reason
# `apps/example/api.py` has none — ninja builds a Pydantic model out of a
# route's signature at import time, and a postponed `Query[ConnectionFilter]`
# annotation comes back as an unresolvable forward reference.

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.core.cache import cache
from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse
from ninja import Query, Router, Status
from ninja.errors import HttpError
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
    WebhookAcceptedOut,
)

# The private name, imported deliberately: it is this app's ONE reach across the
# sibling border (`services.py`, "The hand-off to the event spine"), and a second
# copy of the lookup here would be the second copy of exactly the thing this
# rung exists to avoid. Same app, one implementation, one place to change it.
from apps.connections.services import _events_attr
from apps.core import context
from apps.core.actor import Actor, actor_from_request, system_actor
from apps.core.api import CursorPagination, ordered_by
from apps.core.api.docs import Tag, refuses
from apps.core.models import Tenant
from apps.core.requests import TenantRequest

# What `?ordering=` may name, and nothing else.
ORDERING = ("created_at", "updated_at", "name", "provider", "status")

# Where the OAuth `state` is parked between the start and the callback, and for
# how long. The cache rather than the session, because the two halves of the
# handshake are two requests that may not share a session cookie (a provider
# that redirects through its own domain, a browser that dropped a `SameSite`
# cookie on the way back) — and the entry has to expire on its own whether or
# not the user ever comes back.
STATE_CACHE_PREFIX = "connections:oauth:state:"
STATE_TTL_SECONDS = 600

# The header an inbound webhook signs with, and the scheme of the signature.
# A product whose provider uses a different header overrides both on the
# provider; this is the shape, and it is the one `ExampleProvider` speaks.
SIGNATURE_HEADER = "X-Signature"
SIGNATURE_PREFIX = "sha256="
EVENT_TYPE_HEADER = "X-Event-Type"

# The second scheme, and the freshness half this door was missing. It is not a
# new invention: `X-Signature-V2: t=<unix>,sha256=<hex over "<t>.<body>">` is
# the exact envelope this template's own outbound signer already sends, so a
# product that points this template's webhooks at this template's receiver
# speaks one scheme in both directions rather than two that resemble each other.
#
# **The header NAME is here; the window and the parse grammar are not.** A name
# is the wire contract and has to be readable before anything else can happen —
# the door cannot ask "is V2 present" without it. The tolerance and the element
# grammar are `apps.events.receivers`', read at call time through
# `services._events_attr` and never copied, because two five-minute numbers
# agree on the day the second is typed and disagree six months later inside
# somebody's verifier. The name is held to the signer's by
# `test_the_v2_header_name_is_the_signers_own`, which is the drift this copy
# could otherwise cause.
#
# A runtime lookup rather than an import for the reason every reach across this
# border is one (`apps/connections/apps.py`): the platform apps are siblings and
# this app keeps working in a tree where `apps/events` never landed. In such a
# tree nothing sends V2 — and a request that claims to anyway is refused rather
# than waved through, which is what `signature_v2_matches` returning `False` on
# an unreachable grammar means.
SIGNATURE_V2_HEADER = "X-Signature-V2"

# What this app's tag is FOR — collected into the document's `tags` section by
# discovery (ADR api-1). An undescribed tag is a house-rule-41 violation.
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


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    """The actor and tenant a write happens as.

    Whether the actor *may* do the thing is not decided here — `services.py`
    calls `authz.require`. What is decided here is that a write with no
    resolved tenant is refused rather than guessed at.
    """
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    return actor_from_request(request), request.tenant


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
    whether one is stored; `status` and `last_error` tell you whether it is
    working.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — the request resolved no tenant. Send `X-Tenant` naming
      one you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    connections: QuerySet[Connection] = selectors.list_connections(tenant=request.tenant)
    connections = filters.filter(connections)
    return ordered_by(connections, ordering, allowed=ORDERING, default="-created_at")


@router.post("/", response={201: ConnectionOut}, url_name="connection-create")
def create_connection_route(request: TenantRequest, payload: ConnectionIn) -> Status[Connection]:
    """Create a connection

    Register a link between this tenant and one outside provider.

    Send `provider` (the provider's short name — letters, digits, `-` and `_`)
    and `name` (yours, to tell two connections to the same provider apart).

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
      tenant, or the request resolved no tenant.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    connection = services.create_connection(
        tenant=tenant,
        actor=actor,
        provider=payload.provider,
        name=payload.name,
        credentials=payload.credentials,
    )
    return Status(201, connection)


# Declared before `/{connection_id}/…` so that the fixed path wins however the
# URL resolver is feeling. The `connection_id` routes are typed `UUID`, so
# "oauth" could not match one anyway; belt as well as braces, because the day
# somebody widens that path parameter to `str` is not the day to discover this.
@router.get("/oauth/callback/", response=ConnectionOut, url_name="connection-oauth-callback")
# A path that names no row and still resolves one — the connection comes off the
# stored state — so `not_found` is real here and the derivation cannot see it
# (house rule 41's valve).
@refuses("invalid", "forbidden", "not_found", "rate_limited")
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
    * `404 not_found` — the connection the `state` names no longer exists.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    actor, tenant = _acting(request)
    stored = _consume_state(state)
    if stored is None:
        raise HttpError(400, "That OAuth state is unknown or has expired.")
    if str(stored.get("tenant_id")) != str(tenant.pk):
        raise HttpError(400, "That OAuth state belongs to another tenant.")

    connection = selectors.get_connection(
        tenant=tenant, connection_id=UUID(str(stored["connection_id"]))
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
    `has_credentials`, the last error the provider gave (`last_error`, empty
    string when there is none), and when it was connected or revoked.

    The stored credentials are not in the answer and cannot be read back through
    any route here. A connection belonging to another tenant, or an id that
    names nothing, answers `404 not_found`.

    Refusals you can get here:

    * `404 not_found` — no connection of this tenant's has that id.
    * `403 forbidden` — the request resolved no tenant. Send `X-Tenant` naming
      one you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    return selectors.get_connection(tenant=request.tenant, connection_id=connection_id)


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
    `last_error`, so this is how you bring a failing connection back after
    rotating a key.

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
    actor, tenant = _acting(request)
    connection = selectors.get_connection(tenant=tenant, connection_id=connection_id)
    return services.update_credentials(
        tenant=tenant, actor=actor, connection=connection, credentials=payload.credentials
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
    actor, tenant = _acting(request)
    connection = selectors.get_connection(tenant=tenant, connection_id=connection_id)
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
    * `403 forbidden` — the request resolved no tenant. Send `X-Tenant` naming
      one you belong to.
    * `404 not_found` — no connection of this tenant's has that id.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under
      it has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.
    """
    _actor, tenant = _acting(request)
    connection = selectors.get_connection(tenant=tenant, connection_id=connection_id)
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
    """Read the parked state and delete it, so it works exactly once."""
    key = _state_key(state)
    stored = cache.get(key)
    cache.delete(key)
    return dict(stored) if isinstance(stored, dict) else None


# --- The inbound receiver ------------------------------------------------------


def expected_signature(*, secret: str, body: bytes) -> str:
    """The HMAC an honest sender would have computed."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def signature_matches(*, secret: str, body: bytes, provided: str) -> bool:
    """Constant-time comparison, and a refusal when there is no secret.

    `hmac.compare_digest` rather than `==`, because `==` returns as soon as two
    bytes differ and the time it took is a slow read of the expected value.

    An empty secret is `False` and not "skip the check": a connection whose
    credentials have been revoked has no secret, and the reading of "no secret
    configured" that lets everything through is how a receiver ends up open.
    """
    if not secret:
        return False
    offered = provided.strip().lower().removeprefix(SIGNATURE_PREFIX)
    return hmac.compare_digest(expected_signature(secret=secret, body=body), offered)


def signature_v2_tolerance() -> timedelta | None:
    """How stale a `X-Signature-V2` delivery may be, or `None` when there is no scheme.

    Read off `apps.events.receivers`, never redeclared here: this door refuses
    what that module's verifier refuses, and the only way to keep that true is
    for there to be one number. The docstring on `receive_webhook` publishes it
    in minutes and `test_the_published_window_is_the_constant` holds the prose
    to whatever this returns.
    """
    tolerance = _events_attr("receivers", "SIGNATURE_V2_TOLERANCE")
    return tolerance if isinstance(tolerance, timedelta) else None


def signature_v2_matches(*, secret: str, body: bytes, provided: str) -> bool:
    """Digest **and** freshness, or false. The whole of the second scheme's check.

    Two things have to be true and this function owns neither of them: the
    digest is the one this key produces over `<timestamp>.<the raw bytes>`, and
    the timestamp is inside `signature_v2_tolerance()` of now. Both are decided
    by the house verifier in `apps.events.receivers`, which is the module the
    matching signer lives beside — so a delivery this template sends and this
    door receives is judged by one implementation, with one window and one
    parse grammar, rather than by two that were equal when they were written.

    What is decided *here*, before the delegation, is the same fail-closed
    clause `signature_matches` has: **an empty secret is `False`, never "skip
    the check"**. A revoked connection has no secret, and the reading of "no
    secret configured" that lets everything through is how a receiver ends up
    open. It is stated here rather than relied on from over the border because a
    verifier's fail-closed behaviour is this door's promise to make.

    An unreachable grammar — a tree with no `apps/events` in it — is `False` for
    the same reason: a scheme that cannot be checked has not been checked.
    """
    if not secret:
        return False
    matches = _events_attr("receivers", "signature_v2_matches")
    if not callable(matches):
        return False
    return bool(matches(secret=secret, body=body, signature=provided))


def _verified(*, connection: Connection, body: bytes, headers: dict[str, str]) -> bool:
    """Did the sender prove it is the sender? **One answer, one chosen scheme.**

    Three ways a request can be judged, in this order, and exactly one of them
    ever runs: a verifier the provider's own app registered, then
    `X-Signature-V2` if the sender offered one, then `X-Signature`. The order is
    not a fallback chain — each step that has an opinion is the answer, and a
    later step is reached only when the earlier one had none to give.

    The app that owns a provider's deliveries may also own its signature scheme
    (`providers.register_webhook_verifier`), because an ESP signs the way its
    vendor decided and this template's HMAC-over-body is nobody's standard but
    ours. A registered verifier that recognises the request decides; one that
    says `None` — not configured, vendor library absent, no secret to check with
    — has no opinion, and the door's own HMAC decides, exactly as it did before
    the seam existed.

    **There is no third branch where nothing is checked.** A verifier can only
    ever move the decision from `signature_matches` to itself; it can never skip
    it. That is the whole reason `None` is a value rather than an absence.
    """
    verifier = get_webhook_verifier(connection.provider)
    if verifier is not None:
        verdict = verifier(connection=connection, body=body, headers=headers)
        if verdict is not None:
            return verdict
    offered = headers.get(SIGNATURE_V2_HEADER, "")
    if offered:
        # **Present means decisive.** Not "try V2, fall back to V1": a scheme a
        # sender can be stepped down from buys nothing, because an attacker
        # replaying yesterday's capture would simply drop the header that
        # carries the window and keep the one that does not. So a correct
        # `X-Signature` beside a stale or forged `X-Signature-V2` is refused,
        # and the only way to be accepted is to satisfy the strongest scheme you
        # chose to speak.
        return signature_v2_matches(secret=connection.webhook_secret, body=body, provided=offered)
    # CONTRACTION TRIGGER — 2026-08-24, the expand half of this migration.
    # This branch is the v1-only path and it stays until BOTH are true: every
    # provider whose deliveries a product here receives sends `X-Signature-V2`,
    # and `scripts/mail_demo.py` (which still signs v1 to drive this door from
    # outside) has moved with them. Review it at the first of those, and no
    # later than 2027-02-24 — six months, long enough for a sender that cannot
    # put a timestamp on a request to say so, short enough that "we accept both
    # forever" is a decision somebody makes rather than one that happens.
    # The contraction is one commit: this branch, `signature_matches` above it,
    # and the paragraph the route's docstring publishes about `X-Signature`.
    return signature_matches(
        secret=connection.webhook_secret,
        body=body,
        provided=headers.get(SIGNATURE_HEADER, ""),
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
      nothing else. Still accepted, and still the whole scheme for a sender that
      cannot put a timestamp on a request, but it carries no freshness at all:
      those exact bytes keep verifying for as long as the secret lives.

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

    `401` means the signature did not check out. It says nothing more —
    deliberately, and whether the connection exists, whether it has a secret,
    what the expected signature was, and whether what failed was the digest or
    the 5 minutes of freshness are all withheld. If you get one, check that you
    are signing the raw body bytes with the right secret, that the `t` you sign
    and send is the current time in whole seconds, and that you have not
    re-serialized the JSON on the way.

    Refusals you can get here:

    * `401` — the signature did not check out, or there is no connection with
      that id. Those answer identically and deliberately: whether the
      connection exists, whether it has a secret, what the expected signature
      was, and whether a `t` you sent was outside the 5 minutes are all
      withheld. Check that you are signing the raw body bytes with the right
      secret, that your `t` is current, and that you have not re-serialized the
      JSON on the way.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    Retry on anything other than a `202`; nothing was stored.
    """
    connection = selectors.get_connection_for_webhook(connection_id=connection_id)
    body = request.body
    if not _verified(connection=connection, body=body, headers=dict(request.headers)):
        # Deliberately says nothing about whether the connection exists, whether
        # it has a secret, or what the expected value was.
        raise HttpError(401, "Invalid signature.")

    tenant = connection.tenant
    # The door binds its own context: this request arrived with no user and no
    # session, so nothing upstream of here could have said which tenant it is
    # for or which door it came through.
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
