"""The machine door, driven the way a machine drives it.

This builds the real ASGI application — the same object `uvicorn` serves — and
speaks JSON-RPC over Streamable HTTP to `/mcp` through an in-process transport.
Nothing is stubbed: the token is a real `ApiToken`, the tenant comes from it,
and `ping` answers with the slug it was actually acting for.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.models import Tenant

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

PROTOCOL_VERSION = "2025-06-18"
MCP_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
}


@asynccontextmanager
async def running(app: Any) -> AsyncIterator[None]:
    """Run an ASGI app's lifespan.

    `httpx.ASGITransport` speaks only HTTP, and the MCP transport starts its
    session manager in the lifespan — so the test runs the lifespan itself,
    exactly as a server would.
    """
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


def _rpc(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def _result(response: httpx.Response) -> dict[str, Any]:
    payload = response.json()
    assert "error" not in payload, payload
    result: dict[str, Any] = payload["result"]
    return result


@pytest.fixture
def token(tenant: Tenant, owner: User) -> str:
    """A real token for a real user with a real membership."""
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="mcp", actor=actor_for(user=owner, tenant=tenant)
    )
    return plaintext


async def test_the_mcp_mount_answers_a_token_holder(tenant: Tenant, token: str) -> None:
    from config.asgi import build_application

    application = build_application()
    headers = {**MCP_HEADERS, "authorization": f"Bearer {token}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            initialize = await client.post(
                "/mcp",
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "1"},
                    },
                ),
            )
            assert initialize.status_code == 200, initialize.text
            assert _result(initialize)["serverInfo"]["name"] == "pilecap"

            listing = await client.post(
                "/mcp",
                headers=headers,
                json=_rpc("tools/list", {}, request_id=2),
            )
            assert listing.status_code == 200, listing.text
            assert "ping" in {tool["name"] for tool in _result(listing)["tools"]}

            called = await client.post(
                "/mcp",
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "ping", "arguments": {}},
                    request_id=3,
                ),
            )
            assert called.status_code == 200, called.text
            result = _result(called)
            assert result["structuredContent"]["ok"] is True
            assert result["structuredContent"]["tenant"] == tenant.slug


async def test_the_mcp_mount_refuses_a_request_with_no_token() -> None:
    from config.asgi import build_application

    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/mcp",
                headers=MCP_HEADERS,
                json=_rpc("tools/list", {}),
            )
    assert response.status_code == 401, response.text
    assert response.headers["www-authenticate"].startswith("Bearer")


async def test_the_mcp_mount_refuses_a_bad_token() -> None:
    from config.asgi import build_application

    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/mcp",
                headers={**MCP_HEADERS, "authorization": "Bearer nonsense"},
                json=_rpc("tools/list", {}),
            )
    assert response.status_code == 401, response.text
