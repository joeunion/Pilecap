"""Bulk is one contract on both doors: a refusal is per item; a crash is the whole batch.

`core.bulk.run_bulk` opens ONE `transaction.atomic()` around its loop. Before it
did, the REST door (under `ATOMIC_REQUESTS`) rolled a crashed batch back whole,
while the MCP door — under no request transaction — kept every item before the
crash: one batch, two outcomes, depending on the door.

Driven over the wire, both doors, on the worked example's bulk archive: a
REFUSAL at item 2 of 3 (an id this hat cannot reach) leaves items 1 and 3
archived with their events; a CRASH at item 2 (the per-item service planted to
raise) leaves NO row changed and NO event, on either door.

`transaction=True`: the MCP transport runs a tool on a worker thread with its
own connection, which cannot see an uncommitted row.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from asgiref.sync import sync_to_async

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.models import Organization, Tenant
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.events.models import Event
from apps.example import api as example_api
from apps.example.models import Widget
from apps.example.services import create_widget

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

BULK = "/api/v1/widgets/bulk/"
ARCHIVED = "example.widget.archived"


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def _world(tenant: Tenant, owner: User, root: Organization) -> tuple[str, list[Widget]]:
    actor = actor_for(user=owner, tenant=tenant, org=root)
    _, bearer = issue_token(user=owner, tenant=tenant, name="bulk-atomicity", actor=actor)
    rows = [create_widget(tenant=tenant, actor=actor, name=f"crate {n}") for n in (1, 2, 3)]
    return bearer, rows


def _state(tenant: Tenant, pks: list[Any]) -> tuple[list[bool], int]:
    every = Widget.objects.for_tenant(tenant).including_archived()
    archived = [every.get(pk=pk).archived_at is not None for pk in pks]
    return archived, Event.objects.for_tenant(tenant).filter(name=ARCHIVED).count()


async def _press(door: str, bearer: str, ids: list[str]) -> httpx.Response | dict[str, Any]:
    from config.asgi import build_application

    application = build_application()
    headers = {"authorization": f"Bearer {bearer}"}
    async with running(application):
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            if door == "rest":
                return await client.post(
                    BULK,
                    headers={**headers, "accept": "application/json"},
                    json={"verb": "archive", "ids": ids},
                )
            mcp = {**MCP_HEADERS, **headers}
            await client.post(
                "/mcp",
                headers=mcp,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "bulk-atomicity", "version": "1"},
                    },
                    1,
                ),
            )
            called = await client.post(
                "/mcp",
                headers=mcp,
                json=_rpc(
                    "tools/call",
                    {"name": "bulk_widgets", "arguments": {"verb": "archive", "ids": ids}},
                    2,
                ),
            )
            answered: dict[str, Any] = called.json()
            return answered


@pytest.mark.parametrize("door", ["rest", "mcp"])
async def test_a_refusal_at_item_two_leaves_items_one_and_three_done(
    door: str, tenant: Tenant, owner: User, root_org: Organization
) -> None:
    bearer, rows = await sync_to_async(_world)(tenant, owner, root_org)
    stranger = str(uuid.uuid4())
    ids = [str(rows[0].pk), stranger, str(rows[2].pk)]

    await _press(door, bearer, ids)

    archived, events = await sync_to_async(_state)(tenant, [rows[0].pk, rows[1].pk, rows[2].pk])
    assert archived == [True, False, True], (door, archived)
    assert events == 2, (door, events)


@pytest.mark.parametrize("door", ["rest", "mcp"])
async def test_a_crash_at_item_two_leaves_nothing_changed_on_either_door(
    door: str,
    tenant: Tenant,
    owner: User,
    root_org: Organization,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bearer, rows = await sync_to_async(_world)(tenant, owner, root_org)
    crash_at = rows[1].pk
    real = example_api.archive_widget  # type: ignore[attr-defined]  # the door's own binding

    def planted(**kwargs: Any) -> Widget:
        if kwargs["widget"].pk == crash_at:
            raise RuntimeError("planted crash at item two")
        return real(**kwargs)

    monkeypatch.setattr(example_api, "archive_widget", planted)

    answered = await _press(door, bearer, [str(row.pk) for row in rows])

    if isinstance(answered, httpx.Response):
        assert answered.status_code == 500, answered.text
    else:
        assert answered.get("error") or answered["result"].get("isError"), answered
    archived, events = await sync_to_async(_state)(tenant, [row.pk for row in rows])
    assert archived == [False, False, False], (door, archived)
    assert events == 0, (door, events)
