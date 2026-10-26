"""The census is the wall: for the customer role, what it answers is what both viewer doors do.

The population is derived: every key of a family the customer host exposes with a mounted door.
Census `false` is a `403` with the key's own sentence and nothing done; `true` is never a `403`.
# does-not-cover: virtual or kindless keys; the face's own proxy (the verifier's live drive).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from django.test import Client

from apps.example.models import Widget
from apps.example.services import create_widget_policy
from apps.example_portal.services import submit_portal_request
from apps.example_portal.tests.conftest import CUSTOMER_HOST, CUSTOMER_ROLE
from config.api import api as the_api
from pilecap import Actor, AuditEntry
from pilecap.accounts import User
from pilecap.surfaces import Surface, exposes
from pilecap.tenancy import Tenant
from pilecap.testing import (
    MCP_HEADERS,
    census,
    door_url_name,
    example_for,
    families_of_app,
    kind_registry,
    list_forms,
    mcp_call,
    mcp_session,
    mounted_operations,
    mounted_url_names,
    refusal_sentence,
    run_db,
    running,
    verb_tools,
    version_of,
    vocabulary,
)

pytestmark = pytest.mark.django_db(transaction=True)

#: The population floor: at least this many keys are driven at the customer host.
#: A floor, never the count — the population is printed on every run.
DRIVEN_FLOOR = 3

READ = "read"
JSON = "application/json"


@dataclass(frozen=True)
class Cell:
    """One key the customer's surface exposes a door for, and what the census says."""

    key: str
    subject: str
    url_name: str
    tool: str | None
    census: bool
    #: The sentences a refusal of this cell may carry: the key's own, and — when
    #: the role cannot read the kind either — the read's, because a door names
    #: the row before it asks the verb.
    walls: tuple[str, ...]


def _exposed_kinds(surface: Surface) -> dict[str, type[Any]]:
    """The kinds whose app owns a family the surface exposes. Derived, never listed."""
    return {
        kind: model
        for kind, model in kind_registry().items()
        if hasattr(model, "_meta")
        and any(exposes(surface, family) for family in families_of_app(model._meta.app_label))
    }


def _door(kind: str, verb: str, model: type[Any], mounted: frozenset[str]) -> str | None:
    """The mounted REST door that serves `<kind>.<verb>`: a read's is the kind's list."""
    if verb == READ:
        return next((name for name in list_forms(kind) if name in mounted), None)
    name = door_url_name(model, verb, kind)
    return name if name in mounted else None


def _twin(url_name: str, tools: set[str]) -> str | None:
    """The door's MCP tool by rule 17's derivation (`core.checks`), or none."""
    noun, _, verb = url_name.rpartition("-")
    candidates = [form.format(noun=noun) for form in verb_tools.get(verb, ())] or [
        f"{verb}_{noun}",
        f"{noun}_{verb}",
    ]
    return next((name for name in candidates if name in tools), None)


def _population(surface: Surface, actor: Actor) -> tuple[list[Cell], list[str]]:
    """Every exposed key with a door, its twin and its census cell; and the doorless keys."""
    from config.mcp import server

    tools = {tool.name for tool in server._tool_manager.list_tools()}
    mounted = mounted_url_names()
    kinds = _exposed_kinds(surface)
    driven: list[Cell] = []
    doorless: list[str] = []
    for key, word in sorted(vocabulary().items()):
        if word.kind not in kinds:
            continue
        verb = key.partition(".")[2]
        door = _door(word.kind, verb, kinds[word.kind], mounted)
        if door is None:
            doorless.append(key)
            continue
        read = f"{word.kind}.{READ}"
        cells = census([key, read], {CUSTOMER_ROLE: actor})
        walls: tuple[str, ...] = (refusal_sentence(key),)
        if verb != READ and not cells[read][CUSTOMER_ROLE]:
            walls += (refusal_sentence(read),)
        cell = cells[key][CUSTOMER_ROLE]
        driven.append(Cell(key, word.kind, door, _twin(door, tools), cell, walls))
    return driven, doorless


# --- the world's own ids, put where the published example put a shape ----------


def _rows(*, tenant: Tenant, owner_actor: Actor, customer_actor: Actor, widget: Widget) -> Any:
    """One row of each subject kind a door's address can name, made by services."""
    policy = create_widget_policy(tenant=tenant, actor=owner_actor, name="Returns")
    request = submit_portal_request(
        tenant=tenant, actor=customer_actor, widget=widget, note="Is it in stock?"
    )
    return {"widget": widget, "widget_policy": policy, "portal_request": request}


def _seeded(name: str, value: Any, *, subject: Any, rows: dict[str, Any]) -> Any:
    """A field's value: a row of the kind it names, the subject's version, or as published."""
    if name == "version" or name.endswith("_version"):
        return version_of(subject)
    if name.endswith("_id") and value is not None:
        named = rows.get(name.removesuffix("_id"), subject)
        return str(named.pk)
    return value


@dataclass(frozen=True)
class Request:
    """What the REST door is sent for one cell: the method, the address, the body."""

    method: str
    path: str
    body: dict[str, Any] | None


def _rest_request(cell: Cell, rows: dict[str, Any]) -> Request:
    """The cell's REST request, off the live document: its path and its published body."""
    document: dict[str, Any] = the_api.get_openapi_schema()
    components: dict[str, Any] = document["components"]["schemas"]
    wanted = the_api.get_openapi_operation_id(mounted_operations()[cell.url_name])
    subject = rows.get(cell.subject)
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            if not isinstance(operation, dict) or operation.get("operationId") != wanted:
                continue
            for parameter in operation.get("parameters", []):
                if parameter.get("in") == "path":
                    assert subject is not None, f"{cell.key}: no {cell.subject} row to address"
                    value = _seeded(parameter["name"], "", subject=subject, rows=rows)
                    path = path.replace("{" + parameter["name"] + "}", str(value))
            schema = operation.get("requestBody", {}).get("content", {}).get(JSON, {})
            reference = schema.get("schema", {}).get("$ref")
            if reference is None:
                return Request(method, path, None)
            node = components[reference.rsplit("/", 1)[-1]]
            published = node.get("example") or example_for(node, components)
            return Request(
                method,
                path,
                {
                    name: _seeded(name, published.get(name), subject=subject, rows=rows)
                    for name in node.get("required", [])
                },
            )
    raise AssertionError(f"{cell.url_name} is mounted and absent from the document")


def _mcp_arguments(cell: Cell, rows: dict[str, Any]) -> dict[str, Any]:
    """The twin's required arguments: its published shape, with the world's ids in it."""
    from config.mcp import server

    (tool,) = [one for one in server._tool_manager.list_tools() if one.name == cell.tool]
    parameters: dict[str, Any] = tool.parameters
    properties: dict[str, Any] = parameters.get("properties", {})
    subject = rows.get(cell.subject)
    return {
        name: _seeded(
            name,
            example_for(properties[name], parameters.get("$defs", {}), name=name),
            subject=subject,
            rows=rows,
        )
        for name in parameters.get("required", [])
    }


def _done(tenant: Tenant, user: User, action: str) -> list[str]:
    """The `ok` audit rows `user` left for `action` — a refusal leaves none."""
    rows = AuditEntry.objects.for_tenant(tenant).filter(
        action=action, actor_user_id=user.pk, outcome="ok"
    )
    return [f"{row.action} door={row.door} surface={row.surface} ok" for row in rows]


def _refused(answer: dict[str, Any]) -> str:
    """An MCP tool error's text, or `""` when the tool answered."""
    if answer.get("isError") is not True:
        return ""
    return " ".join(
        str(block.get("text", "")) for block in answer.get("content", []) if isinstance(block, dict)
    )


@pytest.mark.asyncio
async def test_the_census_is_the_wall_on_both_doors_at_the_customer_host(
    two_hosts: Surface,
    tenant: Tenant,
    owner_actor: Actor,
    customer: User,
    customer_actor: Actor,
    widget: Widget,
    recorded_workflow_starts: None,
) -> None:
    """Every exposed key with a door: the census cell is what REST and MCP answer."""
    from config.asgi import build_application
    from pilecap.testing import a_token

    rows = await run_db(
        _rows, tenant=tenant, owner_actor=owner_actor, customer_actor=customer_actor, widget=widget
    )
    driven, doorless = await run_db(_population, two_hosts, customer_actor)
    print(f"wall population: {len(driven)} keys driven, {len(doorless)} with no door")
    for cell in driven:
        print(f"  driven   {cell.key} · {cell.url_name} · {cell.tool} · census {cell.census}")
    for key in doorless:
        print(f"  skipped  {key} · no mounted door")
    assert len(driven) >= DRIVEN_FLOOR, (len(driven), DRIVEN_FLOOR)

    requests = {cell.key: await run_db(_rest_request, cell, rows) for cell in driven}
    arguments = {cell.key: await run_db(_mcp_arguments, cell, rows) for cell in driven if cell.tool}
    bearer = {"authorization": f"Bearer {await a_token(user=customer, tenant=tenant)}"}
    application = build_application()
    rest: dict[str, httpx.Response] = {}
    mcp: dict[str, dict[str, Any]] = {}
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{CUSTOMER_HOST}"
        ) as client:
            for cell in driven:
                sent = requests[cell.key]
                rest[cell.key] = await client.request(
                    sent.method.upper(), sent.path, headers=bearer, json=sent.body
                )
            headers = {**MCP_HEADERS, **bearer}
            await mcp_session(client, headers)
            for cell in driven:
                if cell.tool:
                    mcp[cell.key] = await mcp_call(client, headers, cell.tool, arguments[cell.key])

    wrong: list[str] = []
    for cell in driven:
        answer = rest[cell.key]
        told = _refused(mcp[cell.key]) if cell.tool else None
        machine = "no twin" if told is None else ("refused" if told else "answered")
        print(
            f"  wire     {cell.key} · census {cell.census} · REST {answer.status_code} · MCP "
            f"{machine}"
        )
        if cell.census is False:
            if answer.status_code != 403 or answer.json().get("detail") not in cell.walls:
                wrong.append(f"REST {cell.key}: census false, answered {answer.status_code}")
            if told is not None and not any(sentence in told for sentence in cell.walls):
                wrong.append(f"MCP  {cell.tool}: census false, answered {mcp[cell.key]!r:.200}")
        else:
            if answer.status_code == 403 or answer.status_code >= 500:
                wrong.append(f"REST {cell.key}: census true, answered {answer.status_code}")
            if told and "forbidden" in told:
                wrong.append(f"MCP  {cell.tool}: census true, refused {told:.200}")
    assert wrong == [], "the wire disagrees with the census:\n  " + "\n  ".join(wrong)

    # The worked cells: the census the role declares, and the wire answering it.
    by_key = {cell.key: cell for cell in driven}
    assert by_key["widget.create"].census is False
    assert by_key["portal_request.submit"].census is True
    assert by_key["widget.read"].census is True
    assert rest["widget.create"].status_code == 403
    assert rest["widget.create"].json()["detail"] == (
        "You may not create widgets in this organization."
    )
    assert rest["portal_request.submit"].status_code == 201, rest["portal_request.submit"].text
    assert rest["widget.read"].status_code == 200, rest["widget.read"].text
    # REST and the MCP twin refused the create, and neither did it.
    assert await run_db(_done, tenant, customer, "example.create_widget") == []


def test_the_session_door_refuses_a_customer_widget_and_does_nothing(
    two_hosts: Surface, tenant: Tenant, customer: User, widget: Widget
) -> None:
    """The human door, straight at Django: the key's own sentence, nothing created."""
    client = Client()
    client.force_login(customer)
    before = Widget.objects.for_tenant(tenant).count()

    refused = client.post(
        "/api/v1/widgets/", {"name": "Mine now"}, content_type=JSON, HTTP_HOST=CUSTOMER_HOST
    )

    assert refused.status_code == 403, refused.content
    assert refused.json()["detail"] == refusal_sentence("widget.create")
    assert Widget.objects.for_tenant(tenant).count() == before
    done = AuditEntry.objects.for_tenant(tenant).filter(
        action="example.create_widget", actor_user_id=customer.pk, outcome="ok"
    )
    assert not done.exists(), list(done.values("surface", "outcome"))
