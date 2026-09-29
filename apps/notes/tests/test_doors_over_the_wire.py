"""The note doors as a real client meets them — and the outbox beside them.

Both doors are driven through the one real ASGI application over `httpx`, and
compared on the WIRE (`response.json()` against the tool's `structuredContent`),
never through the schema both sides share. The event each write emits is the
third witness: a webhook subscriber must read the note exactly as a REST client
does, byte for byte, for a create and for an archive.

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
from apps.core.models import Tenant
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.events.models import Event
from apps.example.models import Widget
from apps.example.services import create_widget
from apps.notes.events import NOTE_ARCHIVED, NOTE_CREATED

#: House rule 46. The door pair this module answers for `apps/notes`.
DOOR_PAIR = ("rest", "mcp")

NOTES_URL = "/api/v1/notes/"
NOTE_URL = "/api/v1/notes/{}/"
MCP_URL = "/mcp"
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
def bearer(tenant: Tenant, owner: User) -> str:
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="note-doors", actor=actor_for(user=owner, tenant=tenant)
    )
    return plaintext


@pytest.fixture
def widget(tenant: Tenant, owner_actor: Actor, recorded_workflow_starts: None) -> Widget:
    return create_widget(tenant=tenant, actor=owner_actor, name="Subject")


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


class _Mcp:
    """One initialized MCP session over the shared client."""

    def __init__(self, client: httpx.AsyncClient, headers: dict[str, str]) -> None:
        self.client = client
        self.headers = {**MCP_HEADERS, **headers}
        self.next_id = 1

    async def initialize(self) -> None:
        answer = await self.client.post(
            MCP_URL,
            headers=self.headers,
            json=_rpc(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "note-doors", "version": "1"},
                },
                self.next_id,
            ),
        )
        assert answer.status_code == 200, answer.text

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.next_id += 1
        answer = await self.client.post(
            MCP_URL,
            headers=self.headers,
            json=_rpc("tools/call", {"name": name, "arguments": arguments}, self.next_id),
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
    payload: dict[str, Any] = dict(event.payload)
    # The outbox stamps the payload's schema version beside the row it carries;
    # everything else is the row, and it is what is compared.
    assert payload.pop("v") == 1
    return payload


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_create_and_archive_say_the_same_bytes_on_rest_mcp_and_the_outbox(
    bearer: str,
    tenant: Tenant,
    widget: Widget,
    declares_notes: None,
    recorded_workflow_starts: None,
) -> None:
    """M4: one note, three witnesses, identical — for the create and the archive."""
    from asgiref.sync import sync_to_async

    from config.asgi import build_application

    application = build_application()
    auth = {"authorization": f"Bearer {bearer}"}
    subject = f"widget:{widget.pk}"
    event = sync_to_async(_event)

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            mcp = _Mcp(client, auth)
            await mcp.initialize()

            # --- create over REST: REST == outbox == MCP's read of it ---------
            created = await client.post(
                NOTES_URL,
                headers={**auth, "accept": JSON},
                json={"subject": subject, "body": "Written over REST."},
            )
            assert created.status_code == 201, created.text
            rest_created = created.json()
            assert set(rest_created) == NOTE_KEYS
            assert rest_created == await event(tenant, NOTE_CREATED, rest_created["id"])
            assert rest_created == await mcp.call("get_note", {"note_id": rest_created["id"]})

            # --- create over MCP: MCP == outbox == REST's read of it ----------
            mcp_created = await mcp.call("create_note", {"subject": subject, "body": "Over MCP."})
            assert set(mcp_created) == NOTE_KEYS
            assert mcp_created == await event(tenant, NOTE_CREATED, mcp_created["id"])
            read = await client.get(
                NOTE_URL.format(mcp_created["id"]), headers={**auth, "accept": JSON}
            )
            assert read.status_code == 200, read.text
            assert mcp_created == read.json()

            # --- archive over MCP: MCP == outbox == REST's read ---------------
            mcp_archived = await mcp.call("archive_note", {"note_id": rest_created["id"]})
            assert mcp_archived["archived_at"] is not None
            assert mcp_archived == await event(tenant, NOTE_ARCHIVED, rest_created["id"])
            read = await client.get(
                NOTE_URL.format(rest_created["id"]), headers={**auth, "accept": JSON}
            )
            assert mcp_archived == read.json()

            # --- archive over REST: REST == outbox == MCP's read --------------
            archived = await client.post(
                NOTE_URL.format(mcp_created["id"]) + "archive/",
                headers={**auth, "accept": JSON},
                json={},
            )
            assert archived.status_code == 200, archived.text
            rest_archived = archived.json()
            assert rest_archived == await event(tenant, NOTE_ARCHIVED, mcp_created["id"])
            assert rest_archived == await mcp.call("get_note", {"note_id": mcp_created["id"]})

            # --- the list, both doors, one page -------------------------------
            listed = await client.get(
                NOTES_URL, params={"subject": subject, "show": "all"}, headers=auth
            )
            assert listed.status_code == 200, listed.text
            tool_page = await mcp.call("list_notes", {"subject": subject, "show": "all"})
            assert listed.json()["items"] == tool_page["items"]
            assert len(tool_page["items"]) == 2
