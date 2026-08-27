"""Tenant **and organization** resolution for sockets.

The same rules as `TenantMiddleware`, against an ASGI scope instead of an
`HttpRequest`: the acting user comes from `AuthMiddlewareStack`, the requested
tenant from an `X-Tenant` header or a `?tenant=` query parameter (a browser
cannot set headers on a websocket handshake, which is the only reason the query
parameter exists), and `scope["tenant"]` is the answer. No membership, no
tenant, no rows.

`scope["org"]` is the acting hat, resolved the same way from `X-Org` or
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
    addressing_refusal,
    resolve_org,
    resolve_tenant,
)

SCOPE_KEY = "tenant"
ORG_SCOPE_KEY = "org"


def _connection_id(scope: dict[str, Any]) -> str:
    """A stable identifier for this socket connection.

    A websocket has no session key of its own, so the client's address and the
    path it opened stand in: one connection is one session, and everything
    pushed down it for the next hour joins on this id.
    """
    client = scope.get("client") or ("", "")
    return f"{client[0]}:{client[1]}:{scope.get('path', '')}"


def _requested_slug(scope: dict[str, Any], header: str, parameter: str) -> str | None:
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
        requested_tenant = _requested_slug(scope, TENANT_HEADER, "tenant")
        tenant = await run_db(
            resolve_tenant,
            user=user,
            requested_slug=requested_tenant,
        )
        requested_org = _requested_slug(scope, ORG_HEADER, "org")
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
            )
            is not None
        ):
            tenant = None
            org = None
        scope[SCOPE_KEY] = tenant
        scope[ORG_SCOPE_KEY] = org

        signed_in = user is not None and bool(getattr(user, "is_authenticated", False))
        context.clear()
        context.bind(
            request_id=context.new_id(),
            correlation_id=context.new_correlation_id(),
            session_id=context.hash_session(_connection_id(scope)),
            tenant_id=str(tenant.pk) if tenant is not None else None,
            org_id=str(org.pk) if org is not None else None,
            user_id=str(user.pk) if user is not None and signed_in else None,
            actor_kind="human" if signed_in else None,
            door="socket",
        )
        try:
            await self.app(scope, receive, send)
        finally:
            context.clear()
