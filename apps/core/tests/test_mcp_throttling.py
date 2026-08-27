"""Rate limiting on the machine door — and the fact that it is not a second one.

`architecture.md`: *ninja throttling per token and per tenant, defaults in
settings; **MCP tools share the same limiter***. Sharing is the claim these tests
exist to hold: not "the same numbers", which drift, but the same throttle objects
counting into the same cache keys, so a tenant that has used its allowance over
HTTP has used it at `/mcp` as well. A limit a client can double by switching
doors is not a limit, and nothing but a test that drives both doors can tell the
difference.

Everything here is the real thing: the real ASGI application, the real token
middleware, the real throttles. Only the rate is lowered, so a burst is three
requests rather than several hundred.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from django.core.cache import cache
from ninja.throttling import SimpleRateThrottle

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.models import Tenant
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.core.throttling import default_throttles

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

LIST_URL = "/api/v1/widgets/"

# Two requests a minute. Low enough that a test can reach it, and applied to both
# doors at once, which is the point.
TINY = "2/min"


def _rpc(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


INITIALIZE = _rpc(
    "initialize",
    {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
)


@pytest.fixture(autouse=True)
def _empty_bucket() -> Iterator[None]:
    """Counters live in the cache, so a test that inherits one is a flake."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def tiny_limit() -> Iterator[None]:
    """Both doors, at a rate a test can reach.

    ninja resolves `NINJA_DEFAULT_THROTTLE_RATES` into its own settings object
    once, at import, and every route's throttle objects were constructed then —
    so the rate is lowered in the resolved table *and* the routes are given
    freshly built throttles that read it. The MCP door builds its throttles per
    request and needs neither.
    """
    from config.api import api

    rates = SimpleRateThrottle.THROTTLE_RATES
    original = dict(rates)
    rates.update({"auth": TINY, "tenant": TINY})

    swapped: list[tuple[Any, list[Any]]] = []
    for bound in api._get_bound_routers():
        for _path, view in bound.path_operations.items():
            for operation in view.operations:
                swapped.append((operation, operation.throttle_objects))
                operation.throttle_objects = default_throttles()
    yield
    for operation, throttles in swapped:
        operation.throttle_objects = throttles
    rates.clear()
    rates.update(original)


@pytest.fixture
def token(tenant: Tenant, owner: User) -> str:
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="mcp", actor=actor_for(user=owner, tenant=tenant)
    )
    return plaintext


@pytest.fixture
def another_token(tenant: Tenant, member: User) -> str:
    """A second credential, same tenant. The per-credential bucket is its own."""
    _, plaintext = issue_token(
        user=member, tenant=tenant, name="second", actor=actor_for(user=member, tenant=tenant)
    )
    return plaintext


def _client(application: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    )


async def test_a_burst_through_the_machine_door_is_refused_with_retry_information(
    tenant: Tenant, token: str, tiny_limit: None
) -> None:
    from config.asgi import build_application

    application = build_application()
    headers = {**MCP_HEADERS, "authorization": f"Bearer {token}"}

    async with running(application):
        async with _client(application) as client:
            first = await client.post("/mcp", headers=headers, json=INITIALIZE)
            assert first.status_code == 200, first.text
            second = await client.post("/mcp", headers=headers, json=_rpc("tools/list", {}, 2))
            assert second.status_code == 200, second.text
            refused = await client.post("/mcp", headers=headers, json=_rpc("tools/list", {}, 3))

    assert refused.status_code == 429
    body = json.loads(refused.content)
    # The same code and the same shape a REST client gets from `config.api`, so a
    # client that handles one handles both.
    assert body["code"] == "rate_limited"
    assert body["detail"]
    # A client that is told when to come back stops hammering — in the header for
    # the transport, and in the body for a JSON-RPC client that only reads results.
    assert int(refused.headers["Retry-After"]) >= 1
    assert int(body["retry_after"]) >= 1


async def test_the_api_and_the_machine_door_share_the_tenants_bucket(
    tenant: Tenant, token: str, another_token: str, tiny_limit: None
) -> None:
    """One tenant, two credentials, two doors — and one allowance between them."""
    from config.asgi import build_application

    application = build_application()
    over_http = {"authorization": f"Bearer {token}"}
    over_mcp = {**MCP_HEADERS, "authorization": f"Bearer {another_token}"}

    async with running(application):
        async with _client(application) as client:
            for _ in range(2):
                spent = await client.get(LIST_URL, headers=over_http)
                assert spent.status_code == 200, spent.text

            # A different credential, so its own bucket is empty — but the same
            # tenant, and that bucket was emptied by the HTTP calls above.
            refused = await client.post("/mcp", headers=over_mcp, json=INITIALIZE)
            assert refused.status_code == 429, refused.text
            assert json.loads(refused.content)["code"] == "rate_limited"

            # And in the other direction: the HTTP door sees the same exhausted
            # bucket for that second credential.
            also_refused = await client.get(LIST_URL, headers=over_mcp)
            assert also_refused.status_code == 429, also_refused.text


async def test_within_the_limit_the_machine_door_is_untouched(
    tenant: Tenant, token: str, tiny_limit: None
) -> None:
    """The limiter refuses a burst and nothing else — a tool still answers."""
    from config.asgi import build_application

    application = build_application()
    headers = {**MCP_HEADERS, "authorization": f"Bearer {token}"}

    async with running(application):
        async with _client(application) as client:
            called = await client.post(
                "/mcp",
                headers=headers,
                json=_rpc("tools/call", {"name": "ping", "arguments": {}}, 1),
            )

    assert called.status_code == 200, called.text
    assert json.loads(called.content)["result"]["structuredContent"]["tenant"] == tenant.slug


async def test_a_call_that_never_authenticated_is_not_counted_against_anybody(
    tenant: Tenant, token: str, tiny_limit: None
) -> None:
    """The throttle sits inside the token door: a bad token costs a 401, not a slot.

    Otherwise anybody who could reach `/mcp` could spend a tenant's allowance
    without holding one of its tokens.
    """
    from config.asgi import build_application

    application = build_application()
    headers = {**MCP_HEADERS, "authorization": f"Bearer {token}"}

    async with running(application):
        async with _client(application) as client:
            for _ in range(4):
                nonsense = await client.post(
                    "/mcp",
                    headers={**MCP_HEADERS, "authorization": "Bearer nonsense"},
                    json=INITIALIZE,
                )
                assert nonsense.status_code == 401

            allowed = await client.post("/mcp", headers=headers, json=INITIALIZE)

    assert allowed.status_code == 200, allowed.text
