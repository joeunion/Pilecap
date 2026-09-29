"""The two doors as a real client meets them, and the event beside them.

Both doors are driven through the one real ASGI application over `httpx` —
REST's `response.json()` against MCP's `structuredContent` — because a
serialization disagreement lives between the schema and the wire, where a test
that calls a tool function cannot see it.

**One link, three renderings, byte for byte.** A link is created over REST;
the SAME `(tag, subject)` pair is then sent over MCP, which answers the same
row (the service is idempotent on the pair); and the one outbox row the create
wrote carries the payload a webhook subscriber receives. All three are equal
— REST == MCP == outbox — and there is exactly one event, because the second
door's request changed nothing.

`transaction=True` because the transport runs a tool body on a worker thread
with its own connection, which cannot see an uncommitted row.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import Actor, actor_for
from apps.core.exceptions import refusal_message
from apps.core.models import Tenant

# The transport harness, from the module that owns it.
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.djb_tags.events import TAG_LINK_CREATED
from apps.djb_tags.models import Tag
from apps.djb_tags.services import create_tag
from apps.djb_tags.tests.conftest import World
from apps.events.models import Event

#: House rule 46: the door pair this module answers for `apps/djb_tags`.
DOOR_PAIR = ("rest", "mcp")

LINKS_URL = "/api/v1/djb_tag_links/"
TAG_URL = "/api/v1/djb_tags/{}/"
MCP_URL = "/mcp"
JSON = "application/json"

# The link's read shape, written out rather than derived from the schema — a
# pin derived from the thing it pins cannot fail.
LINK_KEYS = frozenset(
    {
        "id",
        "tag_id",
        "tag_name",
        "tag_slug",
        "subject",
        "subject_kind",
        "subject_id",
        "tenant_id",
        "organization_id",
        "created_at",
    }
)
TAG_KEYS = frozenset(
    {"id", "name", "slug", "tenant_id", "created_at", "updated_at", "archived_at", "archived_by"}
)


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


async def _call_tool(
    client: httpx.AsyncClient, headers: dict[str, str], name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    initialize = await client.post(
        MCP_URL,
        headers=headers,
        json=_rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "tags-parity", "version": "1"},
            },
            1,
        ),
    )
    assert initialize.status_code == 200, initialize.text
    called = await client.post(
        MCP_URL, headers=headers, json=_rpc("tools/call", {"name": name, "arguments": arguments}, 2)
    )
    assert called.status_code == 200, called.text
    answered: dict[str, Any] = called.json()
    assert "error" not in answered, answered
    result: dict[str, Any] = answered["result"]
    return result


@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="tags-parity", actor=actor_for(user=owner, tenant=tenant)
    )
    return plaintext


@pytest.fixture
def tag(tenant: Tenant, owner_actor: Actor) -> Tag:
    return create_tag(tenant=tenant, actor=owner_actor, name="Urgent")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.usefixtures("widget_takes_tags")
async def test_one_link_is_one_shape_on_rest_mcp_and_the_outbox(
    bearer: str, world: World, tag: Tag
) -> None:
    from asgiref.sync import sync_to_async

    from config.asgi import build_application

    application = build_application()
    auth = {"authorization": f"Bearer {bearer}"}
    subject = f"widget:{world.widget_a.pk}"

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.post(
                LINKS_URL,
                headers={**auth, "accept": JSON},
                json={"tag_id": str(tag.pk), "subject": subject},
            )
            assert over_http.status_code == 201, over_http.text
            result = await _call_tool(
                client,
                {**MCP_HEADERS, **auth},
                "create_djb_tag_link",
                {"tag_id": str(tag.pk), "subject": subject},
            )

    rest_body = over_http.json()
    over_mcp = result["structuredContent"]

    def _payloads() -> list[dict[str, Any]]:
        return [
            dict(event.payload)
            for event in Event.objects.for_tenant(world.tenant).filter(name=TAG_LINK_CREATED)
        ]

    outbox = await sync_to_async(_payloads)()

    assert set(rest_body) == LINK_KEYS
    assert over_mcp == rest_body, "the two doors answered the same link differently"
    # The envelope's own version key rides beside the row's shape (`events.emit`
    # stamps `v`); everything else is the door's answer, key for key.
    assert [payload.pop("v") for payload in outbox] == [1]
    assert outbox == [rest_body], "one event, carrying exactly what the doors answered"
    assert rest_body["organization_id"] == str(world.branch_a.pk)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_tag_reads_the_same_on_both_doors(bearer: str, tag: Tag) -> None:
    from config.asgi import build_application

    application = build_application()
    auth = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(TAG_URL.format(tag.pk), headers={**auth, "accept": JSON})
            assert over_http.status_code == 200, over_http.text
            result = await _call_tool(
                client, {**MCP_HEADERS, **auth}, "get_djb_tag", {"tag_id": str(tag.pk)}
            )

    rest_body = over_http.json()
    assert set(rest_body) == TAG_KEYS
    assert result["structuredContent"] == rest_body


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_kind_that_does_not_take_tags_is_refused_alike_on_both_doors(
    bearer: str, world: World, tag: Tag, widget_takes_no_tags: None
) -> None:
    """`Widget` with `tags` taken out: both doors say `invalid` naming `subject`."""
    from config.asgi import build_application

    application = build_application()
    auth = {"authorization": f"Bearer {bearer}"}
    subject = f"widget:{world.widget_a.pk}"

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                LINKS_URL, params={"subject": subject}, headers={**auth, "accept": JSON}
            )
            result = await _call_tool(
                client, {**MCP_HEADERS, **auth}, "list_djb_tag_links", {"subject": subject}
            )

    assert over_http.status_code == 400, over_http.text
    assert over_http.json()["code"] == "invalid"
    assert set(over_http.json()["errors"]) == {"subject"}
    # The MCP door renders a refusal as TEXT, built by `refusal_message` from the
    # same `wire_refusal` body REST serialises — so parity is that line, rebuilt
    # from the REST body, found string for string on the machine door.
    assert result.get("isError") is True, result
    over_mcp = result["content"][0]["text"]
    assert refusal_message(over_http.json()) in over_mcp, (over_mcp, over_http.json())
    assert "does not take tags" in over_mcp, over_mcp
