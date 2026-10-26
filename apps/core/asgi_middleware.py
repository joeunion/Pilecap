"""Tenant **and organization** resolution for sockets.

The same rules as `TenantMiddleware`, against an ASGI scope instead of an
`HttpRequest`: the acting user comes from `AuthMiddlewareStack`, the requested
tenant from an `X-Tenant` header or a `?tenant=` query parameter (a browser
cannot set headers on a websocket handshake, which is the only reason the query
parameter exists), and `scope["tenant"]` is the answer. No membership, no
tenant, no rows.

`scope["surface"]` is which surface the handshake's host is, resolved first by
the same `resolve_surface` the HTTP door calls; a host no surface is bound to
resolves nowhere, and so does a person a `membership` surface cannot place.

`scope["org"]` is the hat, resolved the same way from `X-Org` or
`?org=`, and — as at the HTTP door — strictly after the tenant, by the same
`resolve_org` the HTTP door calls. One rule, two transports: a hat a socket
could put on and a request could not would be the disagreement between doors
that `architecture.md` calls a finding.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

from apps.core import context
from apps.core.asyncdb import run_db
from apps.core.middleware import (
    ORG_HEADER,
    TENANT_HEADER,
    AmbiguousTenant,
    addressing_refusal,
    resolve_org,
    resolve_tenant,
)
from apps.core.surfaces import request_host, resolve_surface

SCOPE_KEY = "tenant"
ORG_SCOPE_KEY = "org"
SURFACE_SCOPE_KEY = "surface"


def _connection_id(scope: dict[str, Any]) -> str:
    """A stable identifier for this socket connection.

    A websocket has no session key of its own, so the client's address and the
    path it opened stand in: one connection is one session, and everything
    pushed down it for the next hour joins on this id.
    """
    client = scope.get("client") or ("", "")
    return f"{client[0]}:{client[1]}:{scope.get('path', '')}"


def requested_slug(scope: dict[str, Any], header: str, parameter: str) -> str | None:
    """The slug a handshake named in `header`, else in the `parameter` query, else `None`.

    A header that is present wins, empty included: sent means sent (`core.middleware.was_sent`).
    """
    wanted = header.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == wanted:
            return str(value.decode("latin-1"))
    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    values = query.get(parameter)
    return values[0] if values else None


class TenantMiddlewareASGI:
    """Sets `scope["tenant"]` and `scope["org"]` before a consumer sees it."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        scope = dict(scope)
        user = scope.get("user")
        # The host, and ONLY from the handshake's headers — never a query
        # parameter, which would let a client choose its own audience — read
        # by the one road the machine door reads it by, so the socket answers
        # the host the HTTP door's `get_host()` answers.
        host = request_host(scope.get("headers", []))
        surface = resolve_surface(host)
        requested_tenant = requested_slug(scope, TENANT_HEADER, "tenant")
        # A handshake has no body to carry a refusal in, so an unbound host and
        # a person a `membership` surface cannot place resolve NOWHERE — the
        # same answer the addressing law gets below, in the same vocabulary.
        try:
            tenant = (
                await run_db(
                    resolve_tenant,
                    user=user,
                    requested_slug=requested_tenant,
                    surface=surface,
                    host=host,
                )
                if surface is not None
                else None
            )
        except AmbiguousTenant:
            tenant = None
        requested_org = requested_slug(scope, ORG_HEADER, "org")
        org = await run_db(
            resolve_org,
            user=user,
            tenant=tenant,
            requested_slug=requested_org,
        )
        # The addressing-header law, from the one function every door asks (ADR
        # core-20). **A websocket handshake has no body to carry a refusal in**,
        # so this door says it the only way that transport can: it resolves
        # NOWHERE, and `EventConsumer.connect` closes with `CLOSE_NO_TENANT`. It
        # is the same law and the same trigger — a sent header this handshake
        # cannot be given — said in the vocabulary the wire has. Forcing BOTH to
        # `None` is the point: an unwearable `X-Org` used to leave the tenant
        # standing, so the socket joined the tenant's group under a hat it had
        # been refused, which is the quiet half of the same defect.
        if (
            addressing_refusal(
                requested_tenant=requested_tenant,
                tenant=tenant,
                requested_org=requested_org,
                org=org,
                surface=surface,
            )
            is not None
        ):
            tenant = None
            org = None
        scope[SCOPE_KEY] = tenant
        scope[ORG_SCOPE_KEY] = org
        scope[SURFACE_SCOPE_KEY] = surface

        signed_in = user is not None and bool(getattr(user, "is_authenticated", False))
        # Put back on the way out exactly what was there on the way in —
        # `ContextMiddleware`'s shape: a connection's task starts empty and leaves
        # empty, and an in-process caller (a test, a harness driving the
        # application directly) keeps the chain it had rather than losing it.
        previous = context.get()
        context.clear()
        context.bind(
            request_id=context.new_id(),
            correlation_id=context.new_correlation_id(),
            session_id=context.hash_session(_connection_id(scope)),
            tenant_id=str(tenant.pk) if tenant is not None else None,
            org_id=str(org.pk) if org is not None else None,
            user_id=str(user.pk) if user is not None and signed_in else None,
            actor_kind="human" if signed_in else None,
            surface=surface.key if surface is not None else None,
            door="socket",
        )
        try:
            await self.app(scope, receive, send)
        finally:
            context.clear()
            context.bind(**previous)
