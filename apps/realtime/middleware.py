"""Bearer-token authentication for the socket door.

The template's three machine-facing doors now resolve a caller the same way:
REST through `accounts.auth.ApiTokenAuth`, MCP through
`config.mcp.TokenAuthMiddleware`, and sockets through this — all three calling
the one `apps.accounts.services.authenticate_token`, so a token that can read a
row over HTTP can watch that row change over a socket, and a token that cannot,
cannot. A door that authenticated differently would be a door that could see
something the others cannot.

**Where it sits.** `config/asgi.py` wraps every discovered pattern in
`AuthMiddlewareStack` (session) and `TenantMiddlewareASGI` (tenant), then routes
by path. This middleware wraps *one route's consumer*, inside that stack, and is
attached in `consumers.py` where the pattern is declared. No shared file is
edited to add it: an ASGI application is what a `path()` entry holds, and a
middleware wrapping a consumer is an ASGI application.

Running after the session stack rather than before it is what makes the two
credentials compose instead of fight. `TenantMiddlewareASGI` has already
resolved a session user and their tenant by the time this runs; a request with
no `Authorization` header and no `?token=` passes straight through untouched,
and a request with one *overrides* what the session stack concluded — which for
a token request is `AnonymousUser` and no tenant.

**`X-Tenant` symmetry.** The header (or `?tenant=`, because a browser cannot set
headers on a websocket handshake) is read here exactly as `TenantMiddlewareASGI`
reads it and handed to `authenticate_token`, which answers WHO — a pinned
token's own tenant, whatever was asked for. The other half, "and may this
credential act where it asked", is the addressing-header law
(`core.middleware.addressing_refusal`, ADR core-21), asked below by this door
exactly as the REST and MCP doors ask it: a token pinned to a tenant that is
*asked* for a different one is refused outright rather than quietly answered as
the pinned tenant. The refusal is a closed handshake because a handshake has no
body to put one in.

**`X-Org` symmetry, and why overriding half a principal is worse than
overriding none.** Overriding `scope["user"]` and `scope["tenant"]` and
leaving `scope["org"]` alone did not leave the hat *unresolved* — it left the
hat the session stack had resolved *for somebody else*, which for the ordinary
token handshake is `AnonymousUser`'s, which is `None`. So a bearer socket
joined no branch group and heard no org-bearing event however it dressed its
`X-Org`, while the same person's cookie socket heard all of them: one door
answering two ways depending on the credential, which is the disagreement
`architecture.md` calls a finding. The hat is therefore re-resolved here from
the same header, by the same `core.middleware.resolve_org` the HTTP door, the
MCP mount and the session socket stack all call — **the one function**, so
there is no second rule to drift.

Re-resolution, not a fallback: an `X-Org` this token's principal holds no role
over resolves to `None` exactly as it does at every other door, and `None`
joins no branch group. The fix aligns the two credentials; it widens neither.
"""

from __future__ import annotations

import functools
from typing import Any
from urllib.parse import parse_qs

from apps.accounts.services import authenticate_token
from apps.core import context
from apps.core.actor import TOKEN_ATTR, TOKEN_AUTH_ATTR
from apps.core.asgi_middleware import ORG_SCOPE_KEY
from apps.core.asgi_middleware import SCOPE_KEY as TENANT_SCOPE_KEY
from apps.core.asyncdb import run_db
from apps.core.middleware import (
    AUTHORIZATION_HEADER,
    ORG_HEADER,
    TENANT_HEADER,
    addressing_refusal,
    resolve_org,
    was_sent,
)
from apps.realtime.schemas import CLOSE_NO_TENANT, CLOSE_UNAUTHENTICATED

__all__ = ["TokenAuthMiddlewareASGI", "token_auth"]

BEARER = "bearer"
TOKEN_QUERY_PARAM = "token"
TENANT_QUERY_PARAM = "tenant"
ORG_QUERY_PARAM = "org"


def _query(scope: dict[str, Any]) -> dict[str, list[str]]:
    return parse_qs(scope.get("query_string", b"").decode("latin-1"))


def _header(scope: dict[str, Any], name: str) -> str | None:
    wanted = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == wanted:
            return str(value.decode("latin-1"))
    return None


def _bearer_token(scope: dict[str, Any]) -> str | None:
    """The token this handshake presented, header first, query second.

    The query parameter exists for the same reason `?tenant=` does: the browser
    WebSocket API cannot set request headers, so a browser client has no other
    way to present one. It is second, not first, because a URL ends up in
    access logs and browser history and a header does not — a client that can
    send the header should.
    """
    header = _header(scope, AUTHORIZATION_HEADER) or ""
    scheme, _, value = header.partition(" ")
    if scheme.lower() == BEARER and value.strip():
        return value.strip()
    from_query = _query(scope).get(TOKEN_QUERY_PARAM)
    if from_query and from_query[0].strip():
        return from_query[0].strip()
    return None


def _requested_slug(scope: dict[str, Any], header_name: str, parameter: str) -> str | None:
    """Which tenant — or which hat — this handshake asked for, if it named one.

    Deliberately a second reading of the same two places
    `apps.core.asgi_middleware` reads, rather than a call into it: that one's
    reader is private to `core`, and `core` sits below this app. Six lines
    duplicated with the twin named beats an import that reaches into another
    app's internals.

    Header first and query parameter second, for both values and for the reason
    `_bearer_token` gives: a URL reaches access logs and browser history, so the
    query form exists only because a browser's `WebSocket` constructor cannot
    set a request header, and a client that can send the header should.

    **Sent means sent, empty included** (`core.middleware.was_sent`). This
    used to fall through to the query parameter on an EMPTY header, so a
    handshake that set `X-Org` to a template value that did not interpolate was
    answered as though it had named nothing — the quiet default, under a header
    the caller had explicitly set. A header that is present has been sent; only
    its absence reaches the query form.
    """
    header = _header(scope, header_name)
    if was_sent(header):
        return header
    values = _query(scope).get(parameter)
    return values[0] if values else None


async def _refuse(receive: Any, send: Any, code: int) -> None:
    """Close the handshake before the consumer is ever built.

    The `websocket.connect` message is consumed first because that is the
    ASGI exchange: the server has offered a connection and this is the reply to
    it. Nothing further is read, so nothing the client sent after the handshake
    is ever looked at.
    """
    message = await receive()
    if message.get("type") == "websocket.connect":
        await send({"type": "websocket.close", "code": code})


class TokenAuthMiddlewareASGI:
    """Resolves `Authorization: Bearer <token>` (or `?token=`) onto the scope.

    What it leaves behind is exactly what the session stack leaves behind —
    `scope["user"]`, `scope["tenant"]` **and `scope["org"]`** — plus the two
    attributes `core.actor` declares for the REST door, so a consumer reads one
    principal however it was authenticated and can still tell a machine from a
    person.

    "Exactly what the session stack leaves behind" is the whole contract, and
    the third key is in it: the consumer derives its branch groups from
    `scope["org"]` and cannot tell which middleware put it there. Leaving one
    of the three to the loser of the override is how the earlier defect happened.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        # Wear the wrapped consumer's identity. `manage.py introspect` reports
        # `consumer` from the pattern's callback, and the useful answer there is
        # the consumer the socket ends at, not the wrapper it passes through.
        # `AsyncConsumer.as_asgi()` does the same thing for the same reason.
        functools.update_wrapper(self, app, updated=())

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "websocket":
            await self.app(scope, receive, send)
            return

        plaintext = _bearer_token(scope)
        if plaintext is None:
            # No token presented: whatever the session stack concluded stands.
            await self.app(scope, receive, send)
            return

        requested_tenant = _requested_slug(scope, TENANT_HEADER, TENANT_QUERY_PARAM)
        resolved = await run_db(
            authenticate_token,
            plaintext=plaintext,
            requested_slug=requested_tenant,
        )
        if resolved is None:
            # A token was offered and it is not good. Refused here rather than
            # left to the consumer to notice, so that "bad credential" and
            # "no credential" are not the same code path.
            await _refuse(receive, send, CLOSE_UNAUTHENTICATED)
            return

        user, tenant, token_row = resolved

        # The hat, after the tenant and never before it, from the one function
        # every door calls. `resolve_org` fails closed at every step —
        # no tenant, an unknown slug, or a slug this principal holds no role
        # over all answer `None` — so this cannot widen what the token reaches;
        # it can only stop the socket wearing somebody else's hat, or none.
        requested_org = _requested_slug(scope, ORG_HEADER, ORG_QUERY_PARAM)
        org = await run_db(
            resolve_org,
            user=user,
            tenant=tenant,
            requested_slug=requested_org,
        )

        # The addressing-header law, from the one function every door asks (ADR
        # core-20). `authenticate_token` now returns a PINNED token's own
        # tenant whatever `X-Tenant` asked for — it answers who, never
        # where-you-may-act — so this is where a handshake that asked for
        # somewhere else is refused. Without it a bearer socket would silently
        # be answered as its pin, which is the "quietly answered as the pinned
        # tenant" the module docstring above has always said this door refuses.
        #
        # Closed rather than composed: a websocket handshake has no body to
        # carry a refusal in, so `CLOSE_NO_TENANT` — "this handshake resolved
        # nowhere it may act" — is the law said in the only vocabulary the wire
        # has here. It is the same code `EventConsumer.connect` closes with for
        # the session half of this door, so the two credentials answer alike.
        if (
            addressing_refusal(
                requested_tenant=requested_tenant,
                tenant=tenant,
                requested_org=requested_org,
                org=org,
            )
            is not None
        ):
            await _refuse(receive, send, CLOSE_NO_TENANT)
            return

        scope = dict(scope)
        scope["user"] = user
        scope[TENANT_SCOPE_KEY] = tenant
        scope[ORG_SCOPE_KEY] = org
        scope[TOKEN_AUTH_ATTR] = True
        scope[TOKEN_ATTR] = token_row

        # `TenantMiddlewareASGI` bound the context a moment ago and saw an
        # anonymous user, so what it bound says nobody. Correct it — this is the
        # machine door, and `actor_kind="agent"` is what makes an audit row
        # true. The `door` it bound (`socket`) is right either way, and clearing
        # is left to the middleware that bound first.
        #
        # **Unbinding is half the correction.** `context.bind` drops `None`
        # rather than storing it, so binding alone would leave whatever the
        # session stack concluded standing — and a handshake may legitimately
        # carry both credentials, in which case the session's tenant and hat
        # belong to a *different person* than the one this scope now names. A
        # log or audit line that named the loser's branch would be worse than
        # one that named none, so what did not resolve is taken back.
        bound = {
            "tenant_id": str(tenant.pk) if tenant is not None else None,
            "org_id": str(org.pk) if org is not None else None,
            "user_id": str(user.pk),
            "actor_kind": "agent",
        }
        context.bind(**bound)
        context.unbind(*[key for key, value in bound.items() if value is None])
        await self.app(scope, receive, send)


def token_auth(app: Any) -> TokenAuthMiddlewareASGI:
    """Wrap one consumer in bearer-token authentication.

    Read at the point of use — `path("ws/events/", token_auth(Consumer.as_asgi()))`
    — this says what it does without the reader having to know a class name.
    """
    return TokenAuthMiddlewareASGI(app)
