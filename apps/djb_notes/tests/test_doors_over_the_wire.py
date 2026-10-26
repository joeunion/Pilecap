"""The note doors on the wire, held to the outbox by `assert_four_doors` (rule 46).

`transaction=True`: the transport runs a tool body on a worker thread with its own connection.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from apps.accounts.models import User
from apps.core.actor import Actor
from apps.core.exceptions import refusal_message
from apps.core.models import Tenant
from apps.core.tests.doors import assert_four_doors, assert_refused_at_every_door
from apps.core.tests.wire import MCP_HEADERS, MCP_URL, bearer, initialize, rpc, wire
from apps.djb_notes.events import NOTE_ARCHIVED, NOTE_CREATED
from apps.djb_notes.schemas import DjbNoteOut
from apps.events.models import Event
from apps.example.models import Widget
from apps.example.services import create_widget

#: House rule 46. The door pair this module answers for `apps/djb_notes`.
DOOR_PAIR = ("rest", "mcp")

NOTES_URL = "/api/v1/djb_notes/"
NOTE_URL = "/api/v1/djb_notes/{}/"
JSON = "application/json"

# The note read shape, written out rather than derived from the schema — a pin
# derived from the thing it pins cannot fail.
NOTE_KEYS = frozenset(
    {
        "id",
        "subject",
        "body",
        "author_id",
        "author_email",
        "tenant_id",
        "organization_id",
        "created_at",
        "updated_at",
        "archived_at",
        "archived_by",
    }
)

# What a note event carries: the row less `author_email`, which `DjbNoteOut` marks personal.
EVENT_KEYS = NOTE_KEYS - {"author_email"}


@pytest.fixture
def declares_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The widget declares notes for this module, ADDED to whatever it declares.

    Additive and undone by `monkeypatch`, never a replacement and never a hand
    `del`: the day the worked example declares its own attachments, this plant
    keeps them and leaves them exactly as it found them.
    """
    monkeypatch.setattr(
        Widget, "attachments", (*getattr(Widget, "attachments", ()), "notes"), raising=False
    )


@pytest.fixture
def widget(tenant: Tenant, owner_actor: Actor, recorded_workflow_starts: None) -> Widget:
    return create_widget(tenant=tenant, actor=owner_actor, name="Subject")


class _Mcp:
    """One initialized MCP session over the shared client."""

    def __init__(self, client: httpx.AsyncClient, headers: dict[str, str]) -> None:
        self.client = client
        self.headers = headers
        self.next_id = 1

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.next_id += 1
        answer = await self.client.post(
            MCP_URL,
            headers={**MCP_HEADERS, **self.headers},
            json=rpc("tools/call", {"name": name, "arguments": arguments}, self.next_id),
        )
        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert "error" not in body, body
        result = body["result"]
        assert not result.get("isError"), result
        structured: dict[str, Any] = result["structuredContent"]
        return structured


def _event(tenant: Tenant, name: str, note_id: str) -> dict[str, Any]:
    event = Event.objects.for_tenant(tenant).get(name=name, payload__id=note_id)
    payload = dict(event.payload)
    assert set(payload) - {"v"} == EVENT_KEYS
    return payload


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_and_archive_say_the_same_bytes_on_rest_mcp_and_the_outbox(
    owner: User,
    tenant: Tenant,
    widget: Widget,
    declares_notes: None,
    recorded_workflow_starts: None,
) -> None:
    """M4: one note, three witnesses, identical — for the create and the archive."""
    from asgiref.sync import sync_to_async

    token = await sync_to_async(bearer)(user=owner, tenant=tenant, name="note-doors")
    auth = {"authorization": f"Bearer {token}"}
    subject = f"widget:{widget.pk}"
    event = sync_to_async(_event)

    async with wire() as client:
        await initialize(client, auth, who="note-doors")
        mcp = _Mcp(client, auth)

        # --- create over REST: REST == outbox == MCP's read of it ---------
        created = await client.post(
            NOTES_URL,
            headers={**auth, "accept": JSON},
            json={"subject": subject, "body": "Written over REST."},
        )
        assert created.status_code == 201, created.text
        rest_created = created.json()
        assert set(rest_created) == NOTE_KEYS
        assert_four_doors(
            rest=rest_created,
            mcp=await mcp.call("get_djb_note", {"note_id": rest_created["id"]}),
            event_payload=await event(tenant, NOTE_CREATED, rest_created["id"]),
            out=DjbNoteOut,
        )

        # --- create over MCP: MCP == outbox == REST's read of it ----------
        mcp_created = await mcp.call("create_djb_note", {"subject": subject, "body": "Over MCP."})
        assert set(mcp_created) == NOTE_KEYS
        read = await client.get(
            NOTE_URL.format(mcp_created["id"]), headers={**auth, "accept": JSON}
        )
        assert read.status_code == 200, read.text
        assert_four_doors(
            rest=read.json(),
            mcp=mcp_created,
            event_payload=await event(tenant, NOTE_CREATED, mcp_created["id"]),
            out=DjbNoteOut,
        )

        # --- archive over MCP: MCP == outbox == REST's read ---------------
        mcp_archived = await mcp.call("archive_djb_note", {"note_id": rest_created["id"]})
        assert mcp_archived["archived_at"] is not None
        read = await client.get(
            NOTE_URL.format(rest_created["id"]), headers={**auth, "accept": JSON}
        )
        assert_four_doors(
            rest=read.json(),
            mcp=mcp_archived,
            event_payload=await event(tenant, NOTE_ARCHIVED, rest_created["id"]),
            out=DjbNoteOut,
        )

        # --- archive over REST: REST == outbox == MCP's read --------------
        archived = await client.post(
            NOTE_URL.format(mcp_created["id"]) + "archive/",
            headers={**auth, "accept": JSON},
            json={},
        )
        assert archived.status_code == 200, archived.text
        assert_four_doors(
            rest=archived.json(),
            mcp=await mcp.call("get_djb_note", {"note_id": mcp_created["id"]}),
            event_payload=await event(tenant, NOTE_ARCHIVED, mcp_created["id"]),
            out=DjbNoteOut,
        )

        # --- the list, both doors, one page -------------------------------
        listed = await client.get(
            NOTES_URL, params={"subject": subject, "show": "all"}, headers=auth
        )
        assert listed.status_code == 200, listed.text
        tool_page = await mcp.call("list_djb_notes", {"subject": subject, "show": "all"})
        assert listed.json()["items"] == tool_page["items"]
        assert len(tool_page["items"]) == 2


#: Every route of this app beside its tool: (method, path, query, body, tool, arguments).
NO_TENANT_PAIRS = [
    (
        "GET",
        "/api/v1/djb_notes/",
        {"subject": "widget:0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
        None,
        "list_djb_notes",
        {"subject": "widget:0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
    ),
    (
        "GET",
        "/api/v1/djb_notes/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/",
        None,
        None,
        "get_djb_note",
        {"note_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
    ),
    (
        "POST",
        "/api/v1/djb_notes/",
        None,
        {"subject": "widget:0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c", "body": "x"},
        "create_djb_note",
        {"subject": "widget:0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c", "body": "x"},
    ),
    (
        "PATCH",
        "/api/v1/djb_notes/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/",
        None,
        {"body": "x"},
        "update_djb_note",
        {"note_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c", "body": "x"},
    ),
    (
        "POST",
        "/api/v1/djb_notes/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/archive/",
        None,
        None,
        "archive_djb_note",
        {"note_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
    ),
    (
        "POST",
        "/api/v1/djb_notes/0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c/restore/",
        None,
        None,
        "restore_djb_note",
        {"note_id": "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"},
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

    token = await sync_to_async(bearer)(user=nomad, tenant=None, name="no-tenant")
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
