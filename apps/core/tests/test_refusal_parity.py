"""The family's refusals say the same facts on both doors — `wire_extra` included.

REST's refusal body carries, beside `detail`/`code`/`errors`/`remedies`, what a
particular refusal declared in `wire_extra`: a stale save's `current_version`, a
blocked verb's `noun` and `blocking`. The MCP door answers a refusal as one line
of text (`core.exceptions.refusal_message`), and until that line carried the
same keys a machine client had to re-read the row to learn what REST had
simply told its caller — a door disagreement.

Driven OVER THE WIRE on the worked example's `Widget` (versioned, movable,
archivable, its policy blocking and blocked), one family refusal per code:
`stale_version`, `archive_blocked`, `restore_blocked`, `move_blocked`. For each,
every key REST's body carries beyond the common four is in the MCP refusal,
equal value for value.

It is `transaction=True` because the MCP transport runs a tool body on a worker
thread with its own connection, which cannot see an uncommitted row.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from asgiref.sync import sync_to_async

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import Actor, actor_for
from apps.core.exceptions import WIRE_COMMON_KEYS, refusal_extra, refusal_message
from apps.core.models import Organization, Tenant
from apps.core.services import create_organization
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.example.models import Widget, WidgetPolicy
from apps.example.services import (
    archive_widget,
    archive_widget_policy,
    create_widget,
    create_widget_policy,
    record_widget_entry,
)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

JSON = "application/json"
WIDGETS = "/api/v1/widgets"


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


async def _mcp_refusal(
    client: httpx.AsyncClient, headers: dict[str, str], name: str, arguments: dict[str, Any]
) -> str:
    """`initialize`, then one `tools/call` that must refuse; the refusal's text."""
    initialize = await client.post(
        "/mcp",
        headers=headers,
        json=_rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "refusal-parity", "version": "1"},
            },
            1,
        ),
    )
    assert initialize.status_code == 200, initialize.text
    called = await client.post(
        "/mcp", headers=headers, json=_rpc("tools/call", {"name": name, "arguments": arguments}, 2)
    )
    assert called.status_code == 200, called.text
    result = called.json()["result"]
    assert result.get("isError"), result
    return str(result["content"][0]["text"])


def _extras(body: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in body.items() if key not in WIRE_COMMON_KEYS}


def _world(tenant: Tenant, owner: User, root: Organization) -> tuple[str, Actor, Organization]:
    actor = actor_for(user=owner, tenant=tenant, org=root)
    branch = create_organization(
        tenant=tenant, parent=root, name="Branch A", slug="branch-a", actor=actor
    )
    _, bearer = issue_token(user=owner, tenant=tenant, name="refusal-parity", actor=actor)
    return bearer, actor, branch


async def _both(
    bearer: str,
    rest: tuple[str, str, dict[str, Any] | None],
    tool: tuple[str, dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    from config.asgi import build_application

    application = build_application()
    headers = {"authorization": f"Bearer {bearer}"}
    method, path, body = rest
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            answered = await client.request(
                method, path, headers={**headers, "accept": JSON}, json=body
            )
            over_mcp = await _mcp_refusal(client, {**MCP_HEADERS, **headers}, *tool)
    assert answered.status_code == 409, answered.text
    return answered.json(), over_mcp


def _assert_parity(code: str, rest_body: dict[str, Any], over_mcp: str) -> None:
    assert rest_body["code"] == code, rest_body
    carried = _extras(rest_body)
    assert carried, f"{code}: REST carried no wire_extra to compare"
    assert refusal_extra(over_mcp) == carried, (code, over_mcp, carried)
    # And the line is the one composer's rendering of REST's body (the transport
    # prefixes which tool refused).
    assert over_mcp.endswith(refusal_message(rest_body)), (over_mcp, rest_body)


async def test_stale_version_carries_current_version_on_both_doors(
    tenant: Tenant, owner: User, root_org: Organization
) -> None:
    bearer, actor, _ = await sync_to_async(_world)(tenant, owner, root_org)
    widget: Widget = await sync_to_async(create_widget)(tenant=tenant, actor=actor, name="spares")
    rest_body, over_mcp = await _both(
        bearer,
        ("PATCH", f"{WIDGETS}/{widget.pk}/", {"version": 1, "name": "renamed"}),
        ("update_widget", {"widget_id": str(widget.pk), "version": 1, "name": "renamed"}),
    )
    _assert_parity("stale_version", rest_body, over_mcp)
    assert isinstance(rest_body["current_version"], int)


async def test_archive_blocked_carries_its_noun_and_blockers_on_both_doors(
    tenant: Tenant, owner: User, root_org: Organization
) -> None:
    bearer, actor, _ = await sync_to_async(_world)(tenant, owner, root_org)
    policy: WidgetPolicy = await sync_to_async(create_widget_policy)(
        tenant=tenant, actor=actor, name="House rules"
    )
    await sync_to_async(create_widget)(tenant=tenant, actor=actor, name="held", policy=policy)
    rest_body, over_mcp = await _both(
        bearer,
        ("POST", f"{WIDGETS}/policies/{policy.pk}/archive/", None),
        ("archive_widget_policy", {"policy_id": str(policy.pk)}),
    )
    _assert_parity("archive_blocked", rest_body, over_mcp)
    assert set(_extras(rest_body)) == {"noun", "blocking"}


async def test_restore_blocked_carries_its_noun_and_blockers_on_both_doors(
    tenant: Tenant, owner: User, root_org: Organization
) -> None:
    bearer, actor, _ = await sync_to_async(_world)(tenant, owner, root_org)

    def plant() -> Widget:
        policy = create_widget_policy(tenant=tenant, actor=actor, name="House rules")
        widget = create_widget(tenant=tenant, actor=actor, name="held", policy=policy)
        widget = archive_widget(tenant=tenant, actor=actor, widget=widget)
        archive_widget_policy(tenant=tenant, actor=actor, policy=policy)
        return widget

    widget = await sync_to_async(plant)()
    rest_body, over_mcp = await _both(
        bearer,
        ("POST", f"{WIDGETS}/{widget.pk}/restore/", None),
        ("restore_widget", {"widget_id": str(widget.pk)}),
    )
    _assert_parity("restore_blocked", rest_body, over_mcp)


async def test_move_blocked_carries_its_noun_and_blockers_on_both_doors(
    tenant: Tenant, owner: User, root_org: Organization
) -> None:
    bearer, actor, branch = await sync_to_async(_world)(tenant, owner, root_org)

    def plant() -> tuple[Widget, int]:
        widget = create_widget(tenant=tenant, actor=actor, name="ledgered")
        record_widget_entry(tenant=tenant, actor=actor, widget=widget, note="written here")
        widget.refresh_from_db()
        return widget, widget.version

    widget, version = await sync_to_async(plant)()
    rest_body, over_mcp = await _both(
        bearer,
        (
            "POST",
            f"{WIDGETS}/{widget.pk}/move/",
            {"version": version, "organization_id": str(branch.pk)},
        ),
        (
            "move_widget",
            {"widget_id": str(widget.pk), "version": version, "organization_id": str(branch.pk)},
        ),
    )
    _assert_parity("move_blocked", rest_body, over_mcp)


async def test_deleting_a_merge_survivor_is_one_typed_refusal_on_both_doors(
    tenant: Tenant, owner: User, root_org: Organization
) -> None:
    """A survivor others were merged into is held by their tombstones: `merge_survivor`.

    Never the database's PROTECT surfacing as a generic `conflict` that says
    "a row that already exists" — which is not what happened — and the same
    typed body on both doors, the MCP line being the one composer's rendering
    of REST's.
    """
    from apps.example.services import merge_widget

    bearer, actor, _ = await sync_to_async(_world)(tenant, owner, root_org)

    def plant() -> Widget:
        loser = create_widget(tenant=tenant, actor=actor, name="dup")
        survivor = create_widget(tenant=tenant, actor=actor, name="keep")
        merge_widget(
            tenant=tenant,
            actor=actor,
            widget=loser,
            into=survivor,
            version=loser.version,
            into_version=survivor.version,
        )
        return survivor

    survivor = await sync_to_async(plant)()
    rest_body, over_mcp = await _both(
        bearer,
        ("DELETE", f"{WIDGETS}/{survivor.pk}/", None),
        ("delete_widget", {"widget_id": str(survivor.pk)}),
    )
    _assert_parity("merge_survivor", rest_body, over_mcp)
    assert _extras(rest_body) == {"noun": "widget"}
    assert rest_body["remedies"][0]["destination"] == "route:widget-archive"
    assert "already exists" not in rest_body["detail"]
