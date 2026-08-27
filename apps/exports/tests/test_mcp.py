"""The machine door meets house rule 17 with teeth.

Two kinds of test, answering different questions.

**Parity** reads the *real* registries out of `manage.py introspect` — the ninja
routes and the MCP tools the server actually holds — and refuses a REST
capability that has no tool. Adding a route to `api.py` and forgetting `mcp.py`
fails here, in a test that names the missing tool.

**Behaviour** calls the tool functions directly, with a fake `Context` carrying
the `Principal` the token middleware would have left on the ASGI scope. Calling
the function rather than driving JSON-RPC is deliberate: the transport runs a
tool body on a worker thread with its own database connection, which cannot see
a test's uncommitted rows, and what is under test here is the tool. The wire is
`test_doors_over_the_wire.py`'s subject.

**This app takes no rule-17 exemption**, and the table below is where that is
visible: four routes, four tools, nothing recorded in `rules.yaml`. The
asymmetry the plan expected — a download that cannot travel as a tool result —
is answered by the tool saying WHERE the archive is rather than by the
capability being missing, which is the same move `delete_widget` makes when HTTP
answers `204`.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import pytest
from django.core.management import call_command
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from apps.core.mcp import SCOPE_KEY, Principal
from apps.core.services import root_organization
from apps.exports.mcp import register
from apps.exports.models import Export
from apps.exports.services import create_export

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User
    from apps.core.models import Organization, Tenant

    from .conftest import World

pytestmark = pytest.mark.django_db

#: For every REST capability, the tool that is its twin. A new route with no
#: entry here fails the parity test, and an entry with no tool fails it too.
TOOL_FOR_ROUTE: dict[str, str] = {
    "export-list": "list_exports",
    "export-detail": "get_export",
    "export-create": "create_export",
    "export-download": "download_export",
}


@dataclass
class _FakeRequest:
    scope: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeRequestContext:
    request: _FakeRequest


def context_for(user: User, tenant: Tenant | None, org: Organization | None = None) -> Context[Any]:
    """The context a tool sees, with the principal the middleware would have left.

    The hat defaults to the tenant's root, which is what `config.mcp` resolves
    for a token whose user holds the ordinary flat membership. A test that means
    to prove a narrower hat names it.
    """
    resolved = org if org is not None else (root_organization(tenant=tenant) if tenant else None)
    scope = {SCOPE_KEY: Principal(user=user, tenant=tenant, org=resolved)}
    return Context(
        request_context=cast(Any, _FakeRequestContext(request=_FakeRequest(scope=scope)))
    )


def exports_server() -> MCPServer[Any]:
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    return server


def tool(name: str) -> Callable[..., Any]:
    """The function behind a registered tool, off the registry rather than a copy."""
    registered = exports_server()._tool_manager.get_tool(name)
    assert registered is not None, f"{name} is not registered"
    return registered.fn


def introspected() -> dict[str, Any]:
    out = io.StringIO()
    call_command("introspect", stdout=out)
    payload: dict[str, Any] = json.loads(out.getvalue())
    return payload


# --- door parity ----------------------------------------------------------------


def test_every_rest_capability_is_on_the_machine_door_too() -> None:
    """House rule 17, read out of the two registries rather than asserted by hand."""
    payload = introspected()
    routes = {
        str(route["name"]).removeprefix("api:")
        for route in payload["routes"]
        if str(route["view"]).startswith("apps.exports.api.")
    }
    assert routes == set(TOOL_FOR_ROUTE), (
        "An export route has no entry in TOOL_FOR_ROUTE: either the machine door "
        "is missing a capability the human door has, or this table is stale."
    )
    tools = {str(one["name"]) for one in payload["tools"]}
    assert set(TOOL_FOR_ROUTE.values()) <= tools


def test_the_app_registers_those_tools_and_no_others() -> None:
    """The reverse direction: a tool with no route is a door disagreement too."""
    registered = {one.name for one in exports_server()._tool_manager.list_tools()}
    assert registered == set(TOOL_FOR_ROUTE.values())


def test_every_tool_says_what_its_route_says() -> None:
    """One docstring, two doors (rule 41). Prose drifts long before behaviour does."""
    from apps.core.api.docs import contract_of
    from apps.exports import api

    contracts = {
        "list_exports": contract_of(api.list_exports_route),
        "get_export": contract_of(api.retrieve_export),
        "create_export": contract_of(api.create_export_route),
        "download_export": contract_of(api.download_export_route),
    }
    for one in exports_server()._tool_manager.list_tools():
        assert one.description, f"{one.name} has no description"
        assert one.description == contracts[one.name]


# --- behaviour -------------------------------------------------------------------


def test_a_tool_and_its_route_answer_with_the_same_row(
    world: World, recorded_workflow_starts: None
) -> None:
    """Same selector, same schema, same row — the value half of parity."""
    export = create_export(tenant=world.tenant, actor=world.owner_actor)

    answered = tool("get_export")(context_for(world.owner, world.tenant), export_id=export.pk)

    assert answered.id == export.pk
    assert answered.organization_slug == world.root.slug
    assert answered.status == Export.Status.PENDING


def test_the_list_tool_answers_in_the_same_envelope(
    world: World, recorded_workflow_starts: None
) -> None:
    """`ExportPage` inherits `core.schemas.ListPage`, so there is one envelope."""
    create_export(tenant=world.tenant, actor=world.owner_actor)

    page = tool("list_exports")(context_for(world.owner, world.tenant))

    assert page.count is None
    assert page.has_more is False
    assert len(page.items) == 1


def test_the_list_tool_is_scoped_to_the_hat_on_the_principal(
    world: World, recorded_workflow_starts: None
) -> None:
    """The hat comes from the principal, never from an argument.

    There is no parameter a caller could send to widen this, which is the whole
    difference between the machine door and a query string.
    """
    create_export(tenant=world.tenant, actor=world.owner_actor)
    create_export(tenant=world.tenant, actor=world.region_actor)

    at_region = tool("list_exports")(context_for(world.region_admin, world.tenant, world.region))

    assert {one.organization_slug for one in at_region.items} == {"region"}


def test_a_branch_admin_is_refused_a_tenant_wide_export_on_this_door_too(
    world: World, recorded_workflow_starts: None
) -> None:
    """The same bar as the HTTP door, because it is the same service under both."""
    with pytest.raises(ToolError):
        tool("create_export")(
            context_for(world.region_admin, world.tenant, world.region), scope="tenant"
        )

    assert not Export.objects.for_tenant(world.tenant).exists()


def test_the_download_tool_says_where_rather_than_what(
    world: World, recorded_workflow_starts: None, archive_bucket: str
) -> None:
    """The one asymmetry, and it is a grammar difference rather than a missing capability.

    A tool result cannot stream a gigabyte, so it answers with the location and
    the size; the HTTP route answers with the bytes. Both go through
    `api.downloadable_export`, so the three refusals — no such row, no
    permission, no archive behind it — cannot come apart.
    """
    from apps.exports.activities import _write_the_archive
    from apps.exports.services import finish_export

    export = create_export(tenant=world.tenant, actor=world.owner_actor, scope=Export.Scope.TENANT)
    with pytest.raises(ToolError):
        # Not finished: there is no archive, and "no file" is `not_found`.
        tool("download_export")(context_for(world.owner, world.tenant), export_id=export.pk)

    version, manifest = _write_the_archive(export=export, hat=world.root, actor=world.owner_actor)
    finish_export(
        tenant=world.tenant,
        actor=world.owner_actor,
        export=export,
        version=version,
        manifest=manifest,
    )

    answered = tool("download_export")(context_for(world.owner, world.tenant), export_id=export.pk)

    assert answered.id == export.pk
    assert answered.artifact_bytes == version.size_bytes
    assert answered.download_path == f"/api/v1/exports/{export.pk}/download/"
    # `download_url` used to be `None` here, with the note "this deployment's
    # storage does not sign URLs". XPr retired that world: the archive lives in
    # the files seam, which refuses a deployment that has named no bucket, so
    # every deployment that HAS an export artifact signs for it. The tool's whole
    # point — say WHERE rather than hand over bytes — is now answered by a link
    # a client can actually fetch, which is what makes it the machine door's
    # equal of the HTTP redirect rather than a consolation prize.
    assert answered.download_url is not None
    assert str(version.key) in answered.download_url, "the link points at THIS archive"
    assert "X-Amz-Signature=" in answered.download_url, "and it carries its own credential"


def test_a_tool_with_no_tenant_refuses(world: World, nomad: User) -> None:
    """Fails closed: a principal with no tenant reads nothing and writes nothing."""
    with pytest.raises(ToolError):
        tool("create_export")(context_for(nomad, None))


def test_an_export_in_another_tenant_is_not_found_on_this_door_either(
    world: World, neighbour: Tenant, stranger: User, recorded_workflow_starts: None
) -> None:
    from apps.core.actor import actor_for

    theirs = create_export(
        tenant=neighbour,
        actor=actor_for(user=stranger, tenant=neighbour, org=root_organization(tenant=neighbour)),
    )

    with pytest.raises(ToolError):
        tool("get_export")(context_for(world.owner, world.tenant), export_id=theirs.pk)
