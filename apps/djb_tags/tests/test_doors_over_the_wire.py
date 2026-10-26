"""The tag doors on the wire, held to the outbox by `assert_four_doors` (rule 46).

`transaction=True`: the transport runs a tool body on a worker thread with its own connection.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from apps.accounts.models import User
from apps.core.exceptions import refusal_message
from apps.core.tests.doors import assert_four_doors, assert_refused_at_every_door
from apps.core.tests.wire import MCP_HEADERS, MCP_URL, initialize, rpc, wire
from apps.core.tests.wire import bearer as issue_bearer
from apps.djb_tags.events import TAG_LINK_CREATED
from apps.djb_tags.models import Tag
from apps.djb_tags.services import create_tag
from apps.djb_tags.tests.conftest import TagWorld
from apps.events.models import Event

#: House rule 46: the door pair this module answers for `apps/djb_tags`.
DOOR_PAIR = ("rest", "mcp")

LINKS_URL = "/api/v1/djb_tag_links/"
TAG_URL = "/api/v1/djb_tags/{}/"
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


async def _call_tool(
    client: httpx.AsyncClient, headers: dict[str, str], name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    await initialize(client, headers, who="tags-parity")
    called = await client.post(
        MCP_URL,
        headers={**MCP_HEADERS, **headers},
        json=rpc("tools/call", {"name": name, "arguments": arguments}, 2),
    )
    assert called.status_code == 200, called.text
    answered: dict[str, Any] = called.json()
    assert "error" not in answered, answered
    result: dict[str, Any] = answered["result"]
    return result


@pytest.fixture
def bearer(world: TagWorld) -> str:
    return issue_bearer(user=world.owner_membership.user, tenant=world.tenant, name="tags-parity")


@pytest.fixture
def tag(world: TagWorld) -> Tag:
    return create_tag(tenant=world.tenant, actor=world.owner, name="Urgent")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.usefixtures("widget_takes_tags")
async def test_one_link_is_one_shape_on_rest_mcp_and_the_outbox(
    bearer: str, world: TagWorld, tag: Tag
) -> None:
    from asgiref.sync import sync_to_async

    auth = {"authorization": f"Bearer {bearer}"}
    subject = f"widget:{world.widget_a.pk}"

    async with wire() as client:
        over_http = await client.post(
            LINKS_URL,
            headers={**auth, "accept": JSON},
            json={"tag_id": str(tag.pk), "subject": subject},
        )
        assert over_http.status_code == 201, over_http.text
        result = await _call_tool(
            client, auth, "create_djb_tag_link", {"tag_id": str(tag.pk), "subject": subject}
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
    assert len(outbox) == 1, "the second door's repeat changed nothing and said nothing"
    assert_four_doors(rest=rest_body, mcp=over_mcp, event_payload=outbox[0])
    assert rest_body["organization_id"] == str(world.a.pk)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_tag_reads_the_same_on_both_doors(bearer: str, tag: Tag) -> None:
    auth = {"authorization": f"Bearer {bearer}"}

    async with wire() as client:
        over_http = await client.get(TAG_URL.format(tag.pk), headers={**auth, "accept": JSON})
        assert over_http.status_code == 200, over_http.text
        result = await _call_tool(client, auth, "get_djb_tag", {"tag_id": str(tag.pk)})

    rest_body = over_http.json()
    assert set(rest_body) == TAG_KEYS
    assert result["structuredContent"] == rest_body


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_kind_that_does_not_take_tags_is_refused_alike_on_both_doors(
    bearer: str, world: TagWorld, tag: Tag, widget_takes_no_tags: None
) -> None:
    """`Widget` with `tags` taken out: both doors say `invalid` naming `subject`."""
    auth = {"authorization": f"Bearer {bearer}"}
    subject = f"widget:{world.widget_a.pk}"

    async with wire() as client:
        over_http = await client.get(
            LINKS_URL, params={"subject": subject}, headers={**auth, "accept": JSON}
        )
        result = await _call_tool(client, auth, "list_djb_tag_links", {"subject": subject})

    assert over_http.status_code == 400, over_http.text
    assert over_http.json()["code"] == "invalid"
    assert set(over_http.json()["errors"]) == {"subject"}
    # The machine door renders the same `wire_refusal` body as text (`refusal_message`).
    assert result.get("isError") is True, result
    over_mcp = result["content"][0]["text"]
    assert refusal_message(over_http.json()) in over_mcp, (over_mcp, over_http.json())
    assert "does not take tags" in over_mcp, over_mcp


#: Every route of this app beside its tool: (method, path, query, body, tool, arguments).
NO_TENANT_PAIRS = [
    ("GET", "/api/v1/djb_tags/", None, None, "list_djb_tags", {}),
    (
        "GET",
        "/api/v1/djb_tags/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/",
        None,
        None,
        "get_djb_tag",
        {"tag_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
    ),
    ("POST", "/api/v1/djb_tags/", None, {"name": "Urgent"}, "create_djb_tag", {"name": "Urgent"}),
    (
        "PATCH",
        "/api/v1/djb_tags/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/",
        None,
        {"name": "Urgent"},
        "rename_djb_tag",
        {"tag_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c", "name": "Urgent"},
    ),
    (
        "POST",
        "/api/v1/djb_tags/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/archive/",
        None,
        None,
        "archive_djb_tag",
        {"tag_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
    ),
    (
        "POST",
        "/api/v1/djb_tags/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/restore/",
        None,
        None,
        "restore_djb_tag",
        {"tag_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
    ),
    (
        "GET",
        "/api/v1/djb_tag_links/",
        {"subject": "widget:0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
        None,
        "list_djb_tag_links",
        {"subject": "widget:0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
    ),
    (
        "POST",
        "/api/v1/djb_tag_links/",
        None,
        {
            "tag_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c",
            "subject": "widget:0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c",
        },
        "create_djb_tag_link",
        {
            "tag_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c",
            "subject": "widget:0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c",
        },
    ),
    (
        "DELETE",
        "/api/v1/djb_tag_links/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/",
        None,
        None,
        "delete_djb_tag_link",
        {"link_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
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
