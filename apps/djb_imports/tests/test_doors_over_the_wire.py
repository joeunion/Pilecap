"""Imports on both doors, compared on the wire and held to the outbox (rule 46).

`transaction=True`: the transport runs a tool body on a worker thread with its own connection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from apps.accounts.models import User
from apps.core.exceptions import refusal_message
from apps.core.services import root_organization
from apps.core.tests.doors import assert_four_doors, assert_refused_at_every_door
from apps.core.tests.wire import MCP_HEADERS, MCP_URL, initialize, rpc, wire
from apps.core.tests.wire import bearer as issue_bearer
from apps.djb_imports.events import IMPORT_STAGED
from apps.djb_imports.models import Import
from apps.djb_imports.tests.conftest import FIVE_ROWS_ONE_BAD
from apps.djb_imports.tests.store import stored_csv
from apps.events.models import Event

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.actor import Actor
    from apps.core.models import Tenant

#: House rule 46: the door pair this module answers for `apps/djb_imports`.
DOOR_PAIR = ("rest", "mcp")

DETAIL_URL = "/api/v1/djb_imports/{}/"
STAGE_URL = "/api/v1/djb_imports/"
JSON = "application/json"

#: `DjbImportOut`'s wire contract, written out rather than derived from the schema.
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


async def _tool(
    client: httpx.AsyncClient, auth: dict[str, str], name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    await initialize(client, auth, who="imports-door-parity")
    called = await client.post(
        MCP_URL,
        headers={**MCP_HEADERS, **auth},
        json=rpc("tools/call", {"name": name, "arguments": arguments}, 2),
    )
    assert called.status_code == 200, called.text
    answered = called.json()
    assert "error" not in answered, answered
    assert not answered["result"].get("isError"), answered
    structured: dict[str, Any] = answered["result"]["structuredContent"]
    return structured


@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    return issue_bearer(user=owner, tenant=tenant, name="imports-door-parity")


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
    auth = {"authorization": f"Bearer {bearer}"}

    async with wire() as client:
        over_http = await client.get(
            DETAIL_URL.format(previewed.pk), headers={**auth, "accept": JSON}
        )
        assert over_http.status_code == 200, over_http.text
        over_mcp = await _tool(client, auth, "get_djb_import", {"import_id": str(previewed.pk)})

    rest_body = over_http.json()

    assert set(rest_body) == IMPORT_KEYS
    assert set(over_mcp) == set(rest_body), (
        f"only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}"
    )
    assert over_mcp == rest_body
    assert rest_body["counts"] == {"create": 4, "update": 0, "unchanged": 0, "refused": 1}
    assert rest_body["apply_writes"] == 4
    assert rest_body["failure"] == {}, "a run that has not failed carries no refusal"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_stage_is_one_shape_on_both_doors_and_the_outbox(
    bearer: str,
    owner_actor: Actor,
    tenant: Tenant,
    memory_store: dict[str, bytes],
    planted_importer: None,
    recorded_workflow_starts: None,
) -> None:
    """A stage on REST, then the same bytes on MCP: one run, one event, the doors agreeing."""
    from asgiref.sync import sync_to_async

    version = await sync_to_async(stored_csv)(owner_actor, FIVE_ROWS_ONE_BAD)
    auth = {"authorization": f"Bearer {bearer}"}
    body = {"kind": "widget", "file_id": str(version.file_id)}

    async with wire() as client:
        staged = await client.post(STAGE_URL, headers={**auth, "accept": JSON}, json=body)
        assert staged.status_code == 201, staged.text
        over_mcp = await _tool(client, auth, "create_djb_import", body)

    def _payload() -> dict[str, Any]:
        return dict(Event.objects.for_tenant(tenant).get(name=IMPORT_STAGED).payload)

    rest_body = staged.json()
    assert set(rest_body) == IMPORT_KEYS | {"created"}
    assert (rest_body.pop("created"), over_mcp.pop("created")) == (True, False)
    assert_four_doors(rest=rest_body, mcp=over_mcp, event_payload=await sync_to_async(_payload)())


#: Every route of this app beside its tool: (method, path, query, body, tool, arguments).
NO_TENANT_PAIRS = [
    ("GET", "/api/v1/djb_imports/", None, None, "list_djb_imports", {}),
    (
        "GET",
        "/api/v1/djb_imports/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/",
        None,
        None,
        "get_djb_import",
        {"import_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
    ),
    (
        "GET",
        "/api/v1/djb_imports/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/rows/",
        None,
        None,
        "list_djb_import_rows",
        {"import_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
    ),
    (
        "POST",
        "/api/v1/djb_imports/",
        None,
        {"kind": "widget", "file_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
        "create_djb_import",
        {"kind": "widget", "file_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
    ),
    (
        "POST",
        "/api/v1/djb_imports/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/apply/",
        None,
        None,
        "apply_djb_import",
        {"import_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
    ),
    (
        "POST",
        "/api/v1/djb_imports/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/cancel/",
        None,
        None,
        "cancel_djb_import",
        {"import_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
    ),
]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path", "query", "body", "tool", "arguments"), NO_TENANT_PAIRS)
async def test_a_caller_with_no_tenant_is_refused_alike_on_both_doors(
    nomad: User,
    method: str,
    path: str,
    query: dict[str, str] | None,
    body: dict[str, str] | None,
    tool: str,
    arguments: dict[str, str],
) -> None:
    """A person in no tenant, a token naming none: `no_acting_scope` from each route and tool."""
    from asgiref.sync import sync_to_async

    token = await sync_to_async(issue_bearer)(user=nomad, tenant=None, name="no-tenant")
    auth = {"authorization": f"Bearer {token}"}
    async with wire() as client:
        over_http = await client.request(
            method, path, params=query, json=body, headers={**auth, "accept": JSON}
        )
        await initialize(client, auth, who="no-tenant")
        called = await client.post(
            MCP_URL,
            headers={**MCP_HEADERS, **auth},
            json=rpc("tools/call", {"name": tool, "arguments": arguments}, 2),
        )
    assert over_http.status_code == 403, over_http.text
    refused = over_http.json()
    result = called.json()["result"]
    assert_refused_at_every_door(
        code="no_acting_scope", rest=refused, mcp=result, socket_heard=False
    )
    assert str(result["content"][0]["text"]).endswith(refusal_message(refused)), result
