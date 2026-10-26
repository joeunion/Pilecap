"""The machine door, driven the way a machine drives it.

This builds the real ASGI application — the same object `uvicorn` serves — and
speaks JSON-RPC over Streamable HTTP to `/mcp` through an in-process transport.
Nothing is stubbed: the token is a real `ApiToken`, the tenant comes from it,
and `ping` answers with the slug it was actually acting for.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.models import Tenant
from apps.core.tests.wire import MCP_HEADERS as MCP_HEADERS
from apps.core.tests.wire import PROTOCOL_VERSION as PROTOCOL_VERSION
from apps.core.tests.wire import running as running

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


# The wire's pieces live in `apps.core.tests.wire`; the names stay importable
# from here for the door tests that already import them.
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
