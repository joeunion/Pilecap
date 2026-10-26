"""The machine door: an MCP server on Streamable HTTP, mounted at `/mcp`.

Same services as the REST API, same tenancy, same token. A disagreement between
the two doors is a finding, not a feature — which is why the bearer token here
is the one `apps.accounts` issues, resolved by the same
`authenticate_token` service the API's `ApiTokenAuth` uses.

Discovery: an app contributes tools by exposing `register(server)` in its
`mcp.py`. Nothing here is edited when an app is added.

Stateless transport: every request carries its own session, so there is no
server-side session state to lose when a process restarts or a second replica
answers.

Rate limiting is the API's, not a copy of it: `ThrottleMiddleware` runs the same
throttle objects `config/api.py` applies to every route, against the principal
this module resolved, so REST and MCP share one bucket per tenant and one per
credential.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from django.conf import settings
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent

from apps.accounts import oauth
from apps.accounts.auth import BEARER_NOT_VALID, Unauthenticated
from apps.accounts.services import authenticate_token
from apps.core import context
from apps.core.api.docs import RETRY_AFTER_HEADER
from apps.core.asyncdb import run_db
from apps.core.discovery import declared
from apps.core.exceptions import REFUSALS, DomainError, Remedy, wire_refusal

# Where the machine door answers, declared down in `apps.core.mcp` so that
# something under `apps/` — the door index at `/` — can name it without an app
# importing `config` (house rule 7's one-way street). Re-exported explicitly
# (`as`, not a bare import) because `config.asgi` routes on it and mypy
# --strict does not re-export implicitly.
from apps.core.mcp import MCP_PATH as MCP_PATH
from apps.core.mcp import SCOPE_KEY, Principal, rate_limit_refusal, refuse_unstructured_results
from apps.core.middleware import (
    AUTHORIZATION_HEADER,
    CORRELATION_ID_HEADER,
    ORG_HEADER,
    REQUEST_ID_HEADER,
    TENANT_HEADER,
    addressing_refusal,
    resolve_org,
)
from apps.core.surfaces import SurfaceUnknownHost, request_host, resolve_surface
from config.api import DOOR_ENCODER, as_the_door_renders

#: The transport's own session id, and the one header in this file with no home
#: below: `Mcp-Session-Id` belongs to the MCP streamable-HTTP transport and to
#: nothing else in the product, so it is declared where it is read (rule 40 reads
#: `*_HEADER` module-level assignments anywhere under `apps/` or `config/`).
#: The spelling is the specification's; the wire is case-insensitive and the
#: read lowercases, as every read in this file does.
MCP_SESSION_ID_HEADER = "Mcp-Session-Id"


def _transport_security() -> TransportSecuritySettings:
    """Host validation for the MCP mount, taken from Django's own ALLOWED_HOSTS.

    Django's host check does not run here — `/mcp` never reaches a Django view —
    so the same list is applied by the transport instead of being quietly
    dropped.
    """
    hosts = [host for host in settings.ALLOWED_HOSTS if host and host != "*"]
    if not hosts or len(hosts) != len(settings.ALLOWED_HOSTS):
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    allowed_hosts = [pattern for host in hosts for pattern in (host, f"{host}:*")]
    allowed_origins = [
        f"{scheme}://{pattern}"
        for scheme in ("http", "https")
        for host in hosts
        for pattern in (host, f"{host}:*")
    ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def _discover_tool_modules() -> list[Any]:
    """Every installed `apps.*.mcp` module that exposes `register`, in app order."""
    return [
        sys.modules[f"{config.name}.mcp"]
        for config, _register in declared("mcp", "register", predicate=callable)
    ]


#: Set on a server whose answers already go out through the door encoder, so a
#: second install is a no-op rather than a second round trip. The shape every
#: other wrap in this tree uses (`apps/core/mcp.py`'s three).
DOOR_RENDERING_ATTR = "djb_door_rendering_installed"


def install_door_rendering(server: MCPServer[Any]) -> None:
    """Put every machine-door answer out through the HTTP door's encoder.

    **The whole of the one-encoder fix, in one wrap.** `config/api.py` owns the
    encoder — it is the class ninja renders every HTTP response with — and this
    is the only other place a client-visible body is produced, so this is where
    the second door consumes it. The direction was already ruled: the REST door's
    millisecond rendering is the truth, and everything truncates to match.

    **Why here and not in `apps/core/mcp.py` beside its three siblings.** The
    encoder lives in `config/api.py`, and `apps/` may not import `config` — the
    import-linter contract this repository is shaped around. That is not an
    obstacle routed around; it is the reason the seam belongs to the mount: the
    two doors are what `config/` is for, and a truncation rule that lived in an
    app would be a third opinion about a thing the mounts already agree on.

    **Both halves of the answer, because they are one answer.** `content` is
    what a human-facing client shows and `structured_content` is what a machine
    parses, and the SDK builds them from the same return value by two different
    paths. Truncating one and not the other would replace a divergence between
    two doors with a divergence inside one of them, which is worse: nobody
    diffs a tool's text block against its own structured block.

    Byte-identical when there is nothing to do. A body already carrying
    millisecond timestamps comes back as the same object, and a text block whose
    parsed value did not change keeps its original string rather than being
    re-serialised into an equivalent one — so this wrap cannot quietly reformat
    an answer it had no business touching.

    Installed after every app has registered, so it covers whatever the
    discovery found without naming any of it. Idempotent.
    """
    if getattr(server, DOOR_RENDERING_ATTR, False):
        return
    dispatch = server.call_tool

    async def call_tool_rendered_as_the_door_does(
        name: str, arguments: dict[str, Any], context: Any = None
    ) -> Any:
        result = await dispatch(name, arguments, context)
        if not isinstance(result, CallToolResult):
            # An `InputRequiredResult` — a question, not an answer, and it
            # carries no rendered row to put through an encoder.
            return result
        if result.structured_content is not None:
            result.structured_content = as_the_door_renders(result.structured_content)
        for block in result.content:
            # `TextContent` is the only block that carries a rendered row; an
            # image, an audio clip, a resource link and an embedded resource
            # have no JSON for an encoder to have an opinion about.
            if isinstance(block, TextContent):
                block.text = _text_as_the_door_renders(block.text)
        return result

    server.call_tool = call_tool_rendered_as_the_door_does  # type: ignore[method-assign]
    setattr(server, DOOR_RENDERING_ATTR, True)


def _text_as_the_door_renders(text: str) -> str:
    """A text block re-rendered, or handed back UNTOUCHED.

    Untouched twice over: a block that is not JSON at all (a refusal sentence, a
    plain string a tool returned) is not this function's business, and a block
    whose parsed value the encoder would not change keeps its exact original
    bytes rather than a re-serialisation that merely means the same. The second
    is the one worth writing down — `json.dumps` picks its own separators, and
    quietly restyling every tool's text output while fixing timestamps would be
    a change nobody asked for hiding inside one they did.
    """
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return text
    rendered = as_the_door_renders(parsed)
    if rendered == parsed:
        return text
    return json.dumps(rendered, cls=DOOR_ENCODER)


def build_server() -> MCPServer[Any]:
    """Assemble the server and let every app contribute its tools."""
    server: MCPServer[Any] = MCPServer(
        name="pilecap",
        version="1",
        instructions=(
            "Tools act as the user and tenant the bearer token names. "
            "Every tool calls the same services the HTTP API does."
        ),
    )
    for module in _discover_tool_modules():
        module.register(server)
    refuse_unstructured_results(server)
    # LAST, and outside the loop on purpose: it wraps the server's own dispatch
    # rather than any tool, so it covers every tool every app contributed —
    # including the ones this module will never know the names of.
    install_door_rendering(server)
    return server


server = build_server()


def _header(scope: dict[str, Any], name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return str(value.decode("latin-1"))
    return None


#: The remedy destination this door cannot honour, and the one thing about the
#: `unauthenticated` refusal that is THIS DOOR'S rather than the refusal's.
#:
#: `/mcp` reads `Authorization` and nothing else: a caller who follows "sign in,
#: and let the browser send the session it gives you" arrives back here with a
#: perfectly good session and is answered 401 "A bearer token is required." So
#: the registry's first remedy was, on this door, an instruction that cannot
#: work — and a remedy is the half of the grammar that says what the caller can
#: DO, which makes an unhonourable one worse than none: a dead end with a label
#: on it. It is the only remedy on the code this door cannot act on; the header
#: remedy and the mint remedy are both true here and both survive.
SESSION_REMEDY = "self:session"


def _honoured_remedies() -> tuple[Remedy, ...]:
    """The `unauthenticated` remedies this door can actually honour.

    **Derived from the registry, never re-typed.** The remedies are composed
    once, beside the refusal, in `apps/accounts/auth.py`; a copy here would be a
    second list to keep in step and the first thing the two doors would drift
    on — which is the whole argument for one composer. So this filters what is
    registered rather than declaring its own set, and a remedy added to the code
    tomorrow reaches this door without anybody remembering to add it.

    Read at refusal time rather than frozen at import, for the reason
    `CODE_STATUS` is a live view (ADR core-23): this module is imported while
    the app registry is still being walked, and a snapshot would depend on which
    module got imported first.

    The registry is consulted through `REFUSALS`, so an unregistered code — which
    `DomainError.__init_subclass__` makes impossible for this one — would yield
    an empty tuple and the refusal would fall back to the registered remedies
    rather than shipping a body with none.
    """
    registered = REFUSALS.get(Unauthenticated.code)
    if registered is None:  # pragma: no cover — the class cannot exist unregistered
        return ()
    return tuple(remedy for remedy in registered.remedies if remedy.destination != SESSION_REMEDY)


async def _unauthorized(send: Any, detail: str, *, error: str = "") -> None:
    """401, carrying the discovery chain the MCP specification depends on.

    `WWW-Authenticate` names `resource_metadata` (RFC 9728), so a third-party
    client that has never seen this deployment can follow the 401 to the
    document, learn which authorization server to ask, and come back with a
    token. Without that parameter the refusal is a dead end and DCR-less
    bootstrapping is impossible.

    `error` is only set when there was a token to reject; a call carrying no
    credential at all has nothing to report but the door.

    **The body is composed, not written.** It used to be
    a hand-built `{"detail": ...}` — a human sentence with no `code` and no
    `remedies`, which is the same hole already closed one door over — so an agent
    meeting the machine door's first refusal had nothing to branch on but the
    wording. It now goes through `wire_refusal`, the one composer, on the
    `unauthenticated` code `apps/accounts/auth.py` already registers: the same
    code, the same fact and the same remedies a REST caller gets — every one of
    them this door can honour — because one refusal answered two ways is the
    drift the composer exists against. The
    `detail` this door passes in is kept — it is the more specific sentence (a
    bearer is required / that bearer is not valid) — and a second twin code was
    NOT minted, deliberately: `unauthenticated` is what this is.

    **The remedies are the DOOR'S.** The code, the fact and the sentence are the
    refusal's and are shared; what a caller can do about it depends on which
    door they are standing at, and this one accepts exactly one kind of
    credential. `_honoured_remedies` above is that filter, and it is the only
    thing this door changes about the body.
    """
    body = json.dumps(wire_refusal(Unauthenticated(detail, remedies=_honoured_remedies()))).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (
                    b"www-authenticate",
                    oauth.challenge(error=error, description=detail if error else "").encode(),
                ),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _refused(send: Any, refusal: DomainError) -> None:
    """A refusal the mount decides before any tool is reached, in the REST door's body.

    Three refusals arrive here: the addressing-header law (ADR core-21), a host
    no surface answers at (`surface_unknown_host`) — both facts about where the
    call was sent, decided before anything parsed it as a request — and the
    shared rate limit (`rate_limited`), which also names when to come back in
    the `Retry-After` header, as the REST door's handler does for the same
    refusal. The MCP Streamable HTTP transport specifies exactly that — an
    HTTP status with `Retry-After` — for a server refusing to take work.

    **The body is the REST door's body, byte for byte.** It is `wire_refusal` on
    the same exception class the HTTP seam raises, so "the two doors said the
    same thing" is true by construction rather than by two modules agreeing —
    which is the property rule 17 asks for and the one a hand-written twin here
    would lose on its first wording change.

    The status is read from `config.api.CODE_STATUS`, the one table that decides
    what a code IS as a number (house rule 14 keeps that above the doors). The
    import is deferred for `ContextMiddleware`'s reason and not a preference:
    `config.api` builds the whole mounted API at import, and this module is
    reached from `config.asgi` — read it inside the call, where both are long
    since loaded.

    Answered at the transport rather than as a JSON-RPC error object, exactly as
    the 401 above is and for the same reason: the call was refused before
    anything parsed it as a request, so there is no id to answer and nothing has
    been dispatched to a tool.
    """
    from config.api import CODE_STATUS

    body = json.dumps(wire_refusal(refusal)).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
    ]
    retry_after = getattr(refusal, "retry_after", None)
    if retry_after is not None:
        headers.append((RETRY_AFTER_HEADER.lower().encode(), str(int(retry_after)).encode()))
    await send(
        {
            "type": "http.response.start",
            "status": CODE_STATUS[refusal.code],
            "headers": headers,
        }
    )
    await send({"type": "http.response.body", "body": body})


class ThrottleMiddleware:
    """The API's rate limits, on the machine door. **The same buckets.**

    `architecture.md`: *ninja throttling per token and per tenant, defaults in
    settings; MCP tools share the same limiter.* Sharing it is the whole point —
    `apps.core.throttling` runs the very throttle objects `config/api.py` applies
    to every route, keyed the same way, so a tenant has one allowance across both
    doors instead of one each. A limit a client can double by switching to `/mcp`
    is not a limit.

    It sits **inside** the token middleware, so the principal it counts against
    has already been resolved: an unauthenticated call never gets this far, and a
    bad token costs a 401 rather than a slot in somebody's bucket.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        refused = await rate_limit_refusal(scope)
        if refused is not None:
            await _refused(send, refused)
            return
        await self.app(scope, receive, send)


class TokenAuthMiddleware:
    """`Authorization: Bearer <token>` or nothing gets through.

    The principal is resolved once here and left on the ASGI scope, where
    `apps.core.mcp.principal(ctx)` picks it up. Tools therefore never see a
    token, and a tool that forgets to check who is calling cannot exist: there
    is no unauthenticated call to forget about.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # The host, read ONCE for the call and nowhere else, before the
        # credential: which surface this address is decides which tools it
        # offers, and a host no surface answers at is refused here exactly as
        # the HTTP door's middleware refuses it — `/mcp` never passes through
        # that middleware (`config.asgi` routes it straight to this mount), so
        # this is the machine door's one resolution, by the same road — and the
        # host is read by the one road the socket reads it by, so all three
        # doors answer the host the HTTP door's `get_host()` answers.
        surface = resolve_surface(request_host(scope.get("headers", [])))
        if surface is None:
            await _refused(send, SurfaceUnknownHost())
            return

        header = _header(scope, AUTHORIZATION_HEADER.lower().encode()) or ""
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            await _unauthorized(send, "A bearer token is required.")
            return

        presented = token.strip()
        requested_tenant = _header(scope, TENANT_HEADER.lower().encode())

        # **Two credentials, one door** (ADR ident-3). `ApiToken` is tried first
        # and survives: it is the first-party machine caller — `manage.py seed`,
        # `issue_token`, the wire tests, CI probes — and retiring it would put a
        # browser consent dance inside every one of them.
        #
        # An OAuth access token is a JWT and an `ApiToken` never is, so the two
        # paths cannot shadow each other: a first-party token is never sent to
        # the JWT verifier, and a JWT is never hashed and looked up as an API
        # token. A bearer that is neither is the 401 it always was.
        resolved = await run_db(
            authenticate_token,
            plaintext=presented,
            requested_slug=requested_tenant,
            surface=surface,
        )
        token_row: Any = None
        if resolved is not None:
            user, tenant, token_row = resolved
        elif oauth.looks_like_jwt(presented) and oauth.configured():
            try:
                principal = await run_db(
                    oauth.authenticate_bearer,
                    token=presented,
                    requested_slug=requested_tenant,
                    surface=surface,
                )
            except oauth.OAuthRefused as refused:
                await _unauthorized(send, refused.description, error=refused.error)
                return
            user, tenant = principal.user, principal.tenant
        else:
            await _unauthorized(send, BEARER_NOT_VALID, error="invalid_token")
            return
        # The hat, resolved by the SAME function the HTTP door calls, from the
        # same header. A tool never receives an organization as an argument, so
        # this is the only place a machine call can name one — and it is
        # revalidated against the token's memberships on every request.
        requested_org = _header(scope, ORG_HEADER.lower().encode())
        org = await run_db(
            resolve_org,
            user=user,
            tenant=tenant,
            requested_slug=requested_org,
        )
        # The addressing-header law, from the one function every door asks (ADR
        # core-20). Resolution above answers `None` for anything it cannot
        # honour; this is the half that says so out loud, and it is asked here —
        # after the credential, before the transport — so no tool can be reached
        # by a call that named somewhere it may not act.
        not_honoured = addressing_refusal(
            requested_tenant=requested_tenant,
            tenant=tenant,
            requested_org=requested_org,
            org=org,
            surface=surface,
        )
        if not_honoured is not None:
            await _refused(send, not_honoured)
            return
        scope = dict(scope)
        scope[SCOPE_KEY] = Principal(
            user=user, tenant=tenant, token=token_row, org=org, surface=surface.key
        )

        # The same context the HTTP door binds, so a tool call and a REST call
        # for the same work are one chain in the sink. The session id is the
        # transport's own `Mcp-Session-Id` when the client sent one; a stateless
        # call has none, which is honest rather than invented. What was bound on
        # the way in is put back on the way out — `ContextMiddleware`'s shape —
        # so an in-process caller keeps its chain across a tool call.
        previous = context.get()
        context.clear()
        context.bind(
            **context.from_headers(
                {
                    REQUEST_ID_HEADER: _header(scope, REQUEST_ID_HEADER.lower().encode()) or "",
                    CORRELATION_ID_HEADER: _header(scope, CORRELATION_ID_HEADER.lower().encode())
                    or "",
                }
            ),
            session_id=context.hash_session(_header(scope, MCP_SESSION_ID_HEADER.lower().encode())),
            tenant_id=str(tenant.pk) if tenant is not None else None,
            org_id=str(org.pk) if org is not None else None,
            user_id=str(user.pk),
            actor_kind="agent",
            surface=surface.key,
            door="mcp",
        )
        try:
            await self.app(scope, receive, send)
        finally:
            context.clear()
            context.bind(**previous)


def build_http_app() -> Any:
    """The ASGI app mounted at `/mcp`, token-gated.

    Its lifespan starts the transport's session manager, so `config.asgi` routes
    the lifespan scope here as well as the HTTP one.
    """
    return TokenAuthMiddleware(
        ThrottleMiddleware(
            server.streamable_http_app(
                streamable_http_path=MCP_PATH,
                stateless_http=True,
                json_response=True,
                transport_security=_transport_security(),
            )
        )
    )
