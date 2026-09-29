"""One import run, answered by both doors, compared ON THE WIRE (house rule 46).

The capability under test is `retrieve an import` — `GET /api/v1/djb_imports/{id}/`
and the `get_import` tool. Both doors are driven through the one real ASGI
application over `httpx`, and the REST body is compared with the tool's
`structuredContent`: keys first, then every value. `counts`, `apply_writes`
and `expires_at` are model properties rather than schema aliases (ADR
example-3), so this is the test that would catch the two doors naming them
differently.

`transaction=True` because the MCP transport runs a tool body on a worker thread
with its own connection, which cannot see an uncommitted row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.services import root_organization
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.djb_imports.models import Import

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User
    from apps.core.models import Tenant

#: House rule 46: the door pair this module answers for `apps/djb_imports`.
DOOR_PAIR = ("rest", "mcp")

DETAIL_URL = "/api/v1/djb_imports/{}/"
MCP_URL = "/mcp"
JSON = "application/json"

#: `ImportOut`'s wire contract, written out rather than derived from the schema.
IMPORT_KEYS = frozenset(
    {
        "id",
        "kind",
        "status",
        "tenant_id",
        "organization_id",
        "file_version_id",
        "file_name",
        "digest",
        "requested_by_id",
        "applied_by_id",
        "idempotency_key",
        "counts",
        "apply_writes",
        "failure",
        "applied_at",
        "cancelled_at",
        "created_at",
        "updated_at",
        "expires_at",
    }
)


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    _, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name="imports-door-parity",
        actor=actor_for(user=owner, tenant=tenant),
    )
    return plaintext


@pytest.fixture
def previewed(tenant: Tenant, owner: User) -> Import:
    """One committed, previewed run with counts on it — so every computed field renders.

    Written through the manager rather than through `create_import`: the service
    starts a durable run on commit, and this test is about how a row is RENDERED.
    """
    return Import.objects.create(
        tenant=tenant,
        organization=root_organization(tenant=tenant),
        kind="widget",
        status=Import.Status.PREVIEWED,
        file_name="widgets.csv",
        digest="deadbeef" * 8,
        requested_by=owner,
        count_create=4,
        count_refused=1,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_put_the_same_import_on_the_wire(
    bearer: str, previewed: Import
) -> None:
    """IM.6 (M4): the run row over REST == the `get_import` tool's structured content."""
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(previewed.pk), headers={**bearer_header, "accept": JSON}
            )
            assert over_http.status_code == 200, over_http.text

            headers = {**MCP_HEADERS, **bearer_header}
            initialize = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "imports-door-parity", "version": "1"},
                    },
                    1,
                ),
            )
            assert initialize.status_code == 200, initialize.text

            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "get_djb_import", "arguments": {"import_id": str(previewed.pk)}},
                    2,
                ),
            )
            assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    assert set(rest_body) == IMPORT_KEYS
    assert set(over_mcp) == set(rest_body), (
        f"only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}"
    )
    assert over_mcp == rest_body
    assert rest_body["counts"] == {"create": 4, "update": 0, "unchanged": 0, "refused": 1}
    assert rest_body["apply_writes"] == 4
