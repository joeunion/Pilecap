"""The machine half, and house rule 17 with teeth.

Two kinds of test, answering different questions.

**Parity** reads the *real* registries out of `manage.py introspect` — the ninja
routes and the MCP tools the server actually holds — and refuses a REST capability
that has no tool. Adding a route to `api.py` and forgetting `mcp.py` fails here, in
a test that names the missing tool.

**Behaviour** calls the tool functions directly, with a fake `Context` carrying the
`Principal` the token middleware would have left on the ASGI scope. Calling the
function rather than driving JSON-RPC is deliberate: the transport runs a tool body
on a worker thread with its own database connection, which cannot see a test's
uncommitted rows, and what is under test here is the tool. The wire is
`test_doors_over_the_wire.py`'s subject.

**This app takes no rule-17 exemption**, and the table below is where that is
visible: nine routes, nine tools, nothing recorded in `rules.yaml`. The asymmetry
a reader expects — bytes, which cannot travel as a tool result — is not an
asymmetry at all: they do not travel through the HTTP door either. Both doors hand
out a signed place and neither hands out a stream.

The **audit** half of the module is what `test_api.py` cannot say. It asks that an
issuance be recorded with the door it came through, and a row saying `door=rest`
proves only half of that: a machine door that recorded nothing, or recorded itself
as `rest`, would leave "which door handed this link out" unanswerable in exactly
the population this platform is being built for.
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

from apps.core.actor import actor_for
from apps.core.audit import AuditEntry
from apps.core.mcp import SCOPE_KEY, Principal
from apps.core.services import root_organization
from apps.files.mcp import register
from apps.files.models import FileVersion, StoredFile
from apps.files.services import create_file, record_stored

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User
    from apps.core.models import Organization, Tenant

    from .conftest import World

pytestmark = pytest.mark.django_db

DIGEST = "beadbead" * 8

#: For every REST capability, the tool that is its twin. A new route with no entry
#: here fails the parity test, and an entry with no tool fails it too.
TOOL_FOR_ROUTE: dict[str, str] = {
    "file-list": "list_files",
    "file-detail": "get_file",
    "file-create": "create_file",
    "file-archive": "archive_file",
    "file-restore": "restore_file",
    "download_url-issue": "issue_download_url",
    "version-list": "list_versions",
    "version-add": "add_version",
    "upload-confirm": "confirm_upload",
}


@dataclass
class _FakeRequest:
    scope: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeRequestContext:
    request: _FakeRequest


def context_for(user: User, tenant: Tenant | None, org: Organization | None = None) -> Context[Any]:
    """The context a tool sees, with the principal the middleware would have left.

    The hat defaults to the tenant's root, which is what `config.mcp` resolves for a
    token whose user holds the ordinary flat membership. A test that means to prove
    a narrower hat names it.
    """
    resolved = org if org is not None else (root_organization(tenant=tenant) if tenant else None)
    scope = {SCOPE_KEY: Principal(user=user, tenant=tenant, org=resolved)}
    return Context(
        request_context=cast(Any, _FakeRequestContext(request=_FakeRequest(scope=scope)))
    )


def files_server() -> MCPServer[Any]:
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    return server


def tool(name: str) -> Callable[..., Any]:
    """The function behind a registered tool, off the registry rather than a copy."""
    registered = files_server()._tool_manager.get_tool(name)
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
        if str(route["view"]).startswith("apps.files.api.")
    }
    assert routes == set(TOOL_FOR_ROUTE), (
        "A files route has no entry in TOOL_FOR_ROUTE: either the machine door is "
        "missing a capability the human door has, or this table is stale."
    )
    tools = {str(one["name"]) for one in payload["tools"]}
    assert set(TOOL_FOR_ROUTE.values()) <= tools


def test_the_app_registers_those_tools_and_no_others() -> None:
    """The reverse direction: a tool with no route is a door disagreement too."""
    registered = {one.name for one in files_server()._tool_manager.list_tools()}
    assert registered == set(TOOL_FOR_ROUTE.values())


def test_every_tool_says_what_its_route_says() -> None:
    """One docstring, two doors (rule 41). Prose drifts long before behaviour does."""
    from apps.core.api.docs import contract_of
    from apps.files import api

    contracts = {
        "list_files": contract_of(api.list_files_route),
        "get_file": contract_of(api.retrieve_file),
        "create_file": contract_of(api.create_file_route),
        "archive_file": contract_of(api.archive_file_route),
        "restore_file": contract_of(api.restore_file_route),
        "issue_download_url": contract_of(api.issue_download_url_route),
        "list_versions": contract_of(api.list_versions_route),
        "add_version": contract_of(api.add_version_route),
        "confirm_upload": contract_of(api.confirm_upload_route),
    }
    registered = {
        one.name: str(one.description or "") for one in files_server()._tool_manager.list_tools()
    }
    for name, contract in contracts.items():
        assert contract, f"{name}'s route has no contract docstring"
        assert contract in registered[name], (
            f"{name}'s description is not its route's contract — the two doors are "
            "free to describe one capability differently"
        )


# --- behaviour, and the audit row that names the door ---------------------------


@pytest.fixture
def a_measured_document(
    world: World, named_bucket: str, recorded_workflow_starts: None
) -> tuple[StoredFile, FileVersion]:
    """A document whose first version has been measured — the only kind with a link."""
    acting = actor_for(user=world.owner, tenant=world.tenant, org=world.root)
    ticket = create_file(
        tenant=world.tenant,
        actor=acting,
        filename="invoice-2026-08.pdf",
        content_type="application/pdf",
        size_bytes=1024,
        purpose="invoice",
    )
    stored = record_stored(
        tenant=world.tenant, actor=acting, version=ticket.version, sha256=DIGEST, size_bytes=1024
    )
    return ticket.file, stored


def test_issuing_over_the_machine_door_audits_the_version_it_signed_for(
    world: World, a_measured_document: tuple[StoredFile, FileVersion]
) -> None:
    """At the machine door: one row, naming the version rather than the document.

    The version is named in `input` rather than in `object_id` because the service
    returns a ticket rather than a model — the app's declared answer to
    `UploadTicket`'s blind spot.

    **What this test cannot say, and where it is said instead.** `door` is bound by
    the ASGI middleware (`config/mcp.py`), not by `tool_call`, so a tool called as a
    function here records an empty door — correctly: nothing came through a door.
    `test_doors_over_the_wire.py::test_issuing_over_the_wire_is_audited_as_the_machine_door`
    drives the same call over the real transport and is what proves `door=mcp`.
    """
    document, version = a_measured_document

    answered = tool("issue_download_url")(
        context_for(world.owner, world.tenant), file_id=document.pk
    )

    assert answered.version == 1
    assert answered.version_id == version.pk
    assert "X-Amz-Signature=" in answered.download_url

    rows = list(
        AuditEntry.objects.for_tenant(world.tenant).filter(action="files.issue_download_url")
    )
    assert len(rows) == 1
    assert rows[0].input["version"] == f"files.FileVersion:{version.pk}"
    assert rows[0].input["file"] == f"files.StoredFile:{document.pk}"


def test_the_machine_door_refuses_another_tenants_document_as_not_found(
    world: World, neighbour: Any, a_measured_document: tuple[StoredFile, FileVersion]
) -> None:
    """At the machine door, and nothing audited for a link nobody got."""
    document, _version = a_measured_document

    with pytest.raises(ToolError) as refused:
        tool("issue_download_url")(
            context_for(neighbour.user, neighbour.tenant), file_id=document.pk
        )

    assert "not_found" in str(refused.value)
    assert "forbidden" not in str(refused.value)
    assert (
        not AuditEntry.objects.for_tenant(neighbour.tenant)
        .filter(action="files.issue_download_url")
        .exists()
    )


def test_the_machine_door_files_a_document_at_the_acting_hat(
    world: World, named_bucket: str
) -> None:
    """ADR core-20's placement law, through the door that has no `X-Org` header.

    The hat rides on the principal the mount resolved, and there is no argument for
    a caller to send instead — which is the whole reason the tool takes no
    `organization`. Driven at a NON-root hat, because a test at the root would pass
    whether the placement law held or not.
    """
    answered = tool("create_file")(
        context_for(world.region_admin, world.tenant, world.region),
        filename="region.pdf",
        content_type="application/pdf",
        size_bytes=10,
    )

    assert answered.file.organization_id == world.region.pk
    assert answered.version.organization_id == world.region.pk
    assert answered.expires_in == 900
