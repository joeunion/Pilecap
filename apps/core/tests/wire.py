"""The over-the-wire test client, one copy: the app, its lifespan, JSON-RPC and a bearer.

A door test drives the real ASGI application — the object `uvicorn` serves —
through an in-process transport, and every app's door-parity module used to
carry its own copy of the same five pieces: the MCP path, the protocol
version, a JSON-RPC body, a bearer token and the handshake. They are here, once,
and a door test imports them.

* `wire()` — an `httpx.AsyncClient` speaking to the real application with its
  lifespan running (the MCP transport starts its session manager there), so
  REST and MCP are driven through one client exactly as a caller drives them.
* `rpc()` — one JSON-RPC request body, spelled the way an MCP client spells it.
* `bearer()` — a real token's plaintext for a person in a tenant: the one
  credential both the REST and the MCP doors accept.
* `initialize()` — the MCP handshake every `tools/call` on this transport needs
  first; it asserts the door answered.

Nothing here is a fixture: an app's fixtures decide WHO and WHERE, and call
these to say HOW. The per-app copies retire in their own apps' rungs.

DOES NOT COVER — declared: the socket door (`apps/realtime/tests/websocket.py`
is that client), and a transport other than Streamable HTTP.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.models import Tenant
from apps.core.roads import road

#: Where the machine door is mounted.
MCP_URL = "/mcp"
#: The protocol version the template's MCP door speaks.
PROTOCOL_VERSION = "2025-06-18"
#: What a Streamable HTTP client sends with every JSON-RPC body.
MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}
#: The origin the in-process transport answers as.
BASE_URL = "http://testserver"

#: **What any authenticated, tenant-resolved REST request pays before its own
#: read** — the one fixed cost every door test in the tree can import instead of
#: re-measuring it. Measured on this tree's organizations, memberships and
#: invitations lists (each 8 statements, of which the page is one) and
#: itemised once, so a change to it is a change to one of these and says which:
#: the session row and the user row (Django's session and auth middleware); the
#: membership read that resolves the tenant and the one that resolves the hat
#: (`core.middleware`); and, with no request transaction (ADR perf-2), the
#: three reads `<kind>.read` costs at the hat — the memberships on the chain,
#: their grants, and the delta rows for the role keys they name (paid once per
#: actor, `authz`'s memo). A product's list pin is this plus its own reads.
REQUEST_FIXED_QUERIES = 2 + 2 + 3


@asynccontextmanager
async def running(app: Any) -> AsyncIterator[None]:
    """Run an ASGI app's lifespan, exactly as a server would, for the block."""
    to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def receive() -> dict[str, Any]:
        return await to_app.get()

    async def send(message: dict[str, Any]) -> None:
        await from_app.put(message)

    scope = {"type": "lifespan", "asgi": {"version": "3.0", "spec_version": "2.0"}}
    task = asyncio.create_task(app(scope, receive, send))
    await to_app.put({"type": "lifespan.startup"})
    started = await from_app.get()
    assert started["type"] == "lifespan.startup.complete", started
    try:
        yield
    finally:
        await to_app.put({"type": "lifespan.shutdown"})
        await from_app.get()
        await task


@road(
    "wire_client",
    example="apps/core/tests/test_idempotency_over_the_wire.py::test_the_single_tenant_client_that_never_sends_the_header_still_replays",
)
@asynccontextmanager
async def wire() -> AsyncIterator[httpx.AsyncClient]:
    """An HTTP client speaking to the real application, lifespan running, nothing off."""
    from config.asgi import build_application

    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            yield client


def rpc(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict[str, Any]:
    """One JSON-RPC request body, spelled the way a real MCP client spells it."""
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def bearer(*, user: User, tenant: Tenant | None, name: str = "over-the-wire") -> str:
    """A real token's plaintext for `user` in `tenant` — the credential both doors accept."""
    _, plaintext = issue_token(
        user=user, tenant=tenant, name=name, actor=actor_for(user=user, tenant=tenant)
    )
    return plaintext


def socket_bearer(plaintext: str) -> list[tuple[bytes, bytes]]:
    """The ASGI header list a socket handshake sends `plaintext` as its bearer credential."""
    return [(b"authorization", f"Bearer {plaintext}".encode())]


async def initialize(
    client: httpx.AsyncClient, headers: dict[str, str], who: str = "over-the-wire"
) -> httpx.Response:
    """The MCP handshake every `tools/call` needs first; the door must answer 200."""
    response = await client.post(
        MCP_URL,
        headers={**MCP_HEADERS, **headers},
        json=rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": who, "version": "1"},
            },
        ),
    )
    assert response.status_code == 200, response.text
    return response


async def session(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    """Complete the MCP handshake so later calls are accepted."""
    await client.post(
        MCP_URL,
        headers=headers,
        json=rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        ),
    )
    await client.post(
        MCP_URL, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
    )


async def call(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call one tool.

    The arguments have to VALIDATE even when the call is going to be refused:
    the transport parses a tool's arguments before it runs the tool body, and
    therefore before the frame the ceiling is checked in — so a call with a
    missing argument is answered about the argument rather than about the
    credential.
    """
    response = await client.post(
        MCP_URL,
        headers=headers,
        json=rpc("tools/call", {"name": name, "arguments": arguments or {}}, request_id=2),
    )
    payload = response.json()
    assert "error" not in payload, payload
    result: dict[str, Any] = payload["result"]
    return result
