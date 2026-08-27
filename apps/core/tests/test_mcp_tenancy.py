"""The machine door onto tenancy and hierarchy, and the parity it owes the human one.

Three questions, and they are different:

* **existence** — every REST capability here has a tool, except the one ADR
  core-16 exempts, and that exemption is in `quality/rules.yaml` rather than in
  this file's opinion;
* **words** — every tool's description is the contract half of its route's own
  docstring, so the two doors cannot come to describe one capability differently;
* **refusals, byte-identical** — the wall a branch admin meets refuses the same
  way through both doors. Not "both refuse": the MCP message is the REST body
  rendered, string-compared, so a second refusal grammar cannot grow on the
  machine door without this failing.

Bodies are called as functions with a fake `Context` carrying the `Principal`
that `config.mcp`'s token middleware would have left on the ASGI scope — the
transport runs a tool on a worker thread with its own connection, which cannot
see a test's uncommitted rows, and the thing under test is the tool.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4

import pytest
from django.test import Client
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import actor_for
from apps.core.api.docs import contract_of
from apps.core.audit import AuditEntry
from apps.core.exceptions import refusal_message
from apps.core.mcp import SCOPE_KEY, Principal, register
from apps.core.models import Invitation, Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization
from config.api import as_the_door_renders

pytestmark = pytest.mark.django_db

JSON = "application/json"

#: Every REST capability of this app, and the tool that is its twin. `accept` is
#: absent on purpose and is the ONE absence — ADR core-16, recorded as rule 17's
#: exemption. A new route with no entry here fails the parity test below.
TOOL_FOR_ROUTE: dict[str, str] = {
    "organization-list": "list_organizations",
    "organization-detail": "get_organization",
    "organization-create": "create_organization",
    "organization-update": "update_organization",
    "organization-move": "move_organization",
    "membership-list": "list_memberships",
    "membership-create": "create_membership",
    "membership-update": "update_membership",
    "membership-delete": "delete_membership",
    "invitation-list": "list_invitations",
    "invitation-create": "create_invitation",
    "invitation-delete": "delete_invitation",
    "settings-detail": "get_settings",
    "settings-update": "update_settings",
    "flags-detail": "get_flags",
    "flags-update": "set_flags",
}

EXEMPT_FROM_MCP = {"invitation-accept"}


@dataclass
class _FakeRequest:
    scope: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeRequestContext:
    request: _FakeRequest


def context_for(user: User, tenant: Tenant | None, org: Organization | None = None) -> Context[Any]:
    """The context a tool sees, with the principal the middleware would have left."""
    resolved = org if org is not None else (root_organization(tenant=tenant) if tenant else None)
    scope = {SCOPE_KEY: Principal(user=user, tenant=tenant, org=resolved)}
    return Context(
        request_context=cast(Any, _FakeRequestContext(request=_FakeRequest(scope=scope)))
    )


def core_server() -> MCPServer[Any]:
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    return server


def tool(name: str) -> Callable[..., Any]:
    found: Callable[..., Any] = cast(Any, core_server()._tool_manager._tools[name]).fn  # noqa: SLF001
    return found


@pytest.fixture
def tree(tenant: Tenant, owner: User) -> dict[str, Organization]:
    root = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=root)
    branch_a = create_organization(
        tenant=tenant, parent=root, name="Branch A", slug="branch-a", actor=acting
    )
    branch_b = create_organization(
        tenant=tenant, parent=root, name="Branch B", slug="branch-b", actor=acting
    )
    return {"root": root, "a": branch_a, "b": branch_b}


# --- existence ----------------------------------------------------------------


def test_every_core_rest_capability_has_a_tool_or_a_recorded_exemption() -> None:
    """House rule 17 with teeth, over the real registries."""
    from apps.core.checks import _bound_operations

    routes = {
        str(operation.url_name)
        for _prefix, operation in _bound_operations()
        if str(operation.view_func.__module__).startswith("apps.core.api")
    }
    tools = set(core_server()._tool_manager._tools)  # noqa: SLF001

    assert routes == set(TOOL_FOR_ROUTE) | EXEMPT_FROM_MCP
    for url_name, tool_name in TOOL_FOR_ROUTE.items():
        assert tool_name in tools, f"{url_name} has no twin"


def test_the_one_exemption_is_recorded_with_its_reason() -> None:
    """The absence above is a decision somebody wrote down, not a gap."""
    from pathlib import Path

    import yaml
    from django.conf import settings

    rules = yaml.safe_load((Path(settings.BASE_DIR) / "quality" / "rules.yaml").read_text())
    rule17 = next(entry for entry in rules["rules"] if str(entry["id"]) == "17")
    entry = next(
        one
        for one in rule17["scope"]["exemptions"]
        if one.get("url_name") == "api:invitation-accept"
    )

    assert "impersonation" in entry["reason"]
    assert "bootstrap circle" in entry["reason"]


# --- words --------------------------------------------------------------------


def test_every_tool_says_what_its_route_says() -> None:
    """One docstring, two doors. A description typed here would be the drift."""
    from apps.core.checks import _bound_operations

    views = {
        str(operation.url_name): operation.view_func
        for _prefix, operation in _bound_operations()
        if str(operation.view_func.__module__).startswith("apps.core.api")
    }
    tools = core_server()._tool_manager._tools  # noqa: SLF001

    for url_name, tool_name in TOOL_FOR_ROUTE.items():
        expected = contract_of(views[url_name])
        assert expected, url_name
        assert str(tools[tool_name].description) == expected, tool_name


# --- refusals, byte-identical (E9) -------------------------------------------


def test_the_escalation_wall_refuses_identically_through_both_doors(
    api: Client, tenant: Tenant, tree: dict[str, Organization], owner: User
) -> None:
    """B-CORE-2. The MCP message IS the REST body, rendered — string-compared.

    Two doors, one wall, one answer. If the machine door ever grew a refusal
    grammar of its own this fails, which is the drift house rule 17's
    `does_not_cover` says a registry diff cannot see.
    """
    branch_admin = create_user(email="wall-admin@example.com", password="pw-for-tests-only")
    at_root = actor_for(user=owner, tenant=tenant, org=tree["root"])
    add_membership(
        user=branch_admin,
        tenant=tenant,
        organization=tree["a"],
        role=Membership.Role.ADMIN,
        is_default=True,
        actor=at_root,
    )
    victim = create_user(email="wall-victim@example.com", password="pw-for-tests-only")
    membership = add_membership(
        user=victim,
        tenant=tenant,
        organization=tree["a"],
        role=Membership.Role.MEMBER,
        actor=at_root,
    )

    api.force_login(branch_admin)
    rest = api.patch(
        f"/api/v1/memberships/{membership.pk}/role/",
        data={"role": Membership.Role.OWNER},
        content_type=JSON,
    )
    assert rest.status_code == 403

    with pytest.raises(ToolError) as refused:
        tool("update_membership")(
            context_for(branch_admin, tenant, tree["a"]),
            membership_id=membership.pk,
            # `.value`, because the transport delivers a plain string and the
            # refusal interpolates what it was handed: an enum object here would
            # compare a message no real caller could ever provoke.
            role=Membership.Role.OWNER.value,
        )

    assert str(refused.value) == refusal_message(rest.json())
    assert Membership.objects.get(pk=membership.pk).role == Membership.Role.MEMBER


def test_a_sibling_branch_is_not_found_through_the_machine_door_too(
    tenant: Tenant, tree: dict[str, Organization], owner: User
) -> None:
    """Rule 24's downward-only read, on the door a registry diff cannot see."""
    branch_admin = create_user(email="sib-admin@example.com", password="pw-for-tests-only")
    add_membership(
        user=branch_admin,
        tenant=tenant,
        organization=tree["a"],
        role=Membership.Role.ADMIN,
        is_default=True,
        actor=actor_for(user=owner, tenant=tenant, org=tree["root"]),
    )
    ctx = context_for(branch_admin, tenant, tree["a"])

    with pytest.raises(ToolError) as sibling:
        tool("get_organization")(ctx, organization_id=tree["b"].pk)
    with pytest.raises(ToolError) as invented:
        tool("get_organization")(ctx, organization_id=uuid4())

    assert str(sibling.value) == str(invented.value)
    assert "not_found" in str(sibling.value)


# --- the same row, the same shape (E1) ----------------------------------------


def test_a_tool_answers_with_the_same_row_the_route_does(
    api: Client, owner: User, tenant: Tenant, tree: dict[str, Organization]
) -> None:
    """Door parity as behaviour rather than existence: key for key, value for value."""
    api.force_login(owner)
    rest = api.get(f"/api/v1/organizations/{tree['a'].pk}/").json()

    tool_answer = tool("get_organization")(
        context_for(owner, tenant, tree["root"]), organization_id=tree["a"].pk
    )

    assert as_the_door_renders(tool_answer.model_dump(mode="json")) == as_the_door_renders(rest)


def test_the_two_lists_carry_the_same_envelope(
    api: Client, owner: User, tenant: Tenant, tree: dict[str, Organization]
) -> None:
    api.force_login(owner)
    rest = api.get("/api/v1/organizations/?include_count=true").json()

    page = tool("list_organizations")(context_for(owner, tenant, tree["root"]), include_count=True)

    # Rule 17: the whole envelope, not just the rows. `has_more` and
    # `next_cursor` are the two halves a machine client walks by, and a door
    # that answered one of them differently would be a second contract.
    assert page.count == rest["count"]
    assert page.has_more == rest["has_more"]
    assert page.next_cursor == rest["next_cursor"]
    assert [as_the_door_renders(row.model_dump(mode="json")) for row in page.items] == [
        as_the_door_renders(row) for row in rest["items"]
    ]


# --- G3: the audit row names the door it came through -------------------------


def test_a_write_through_the_machine_door_is_audited_as_mcp(
    owner: User, tenant: Tenant, tree: dict[str, Organization]
) -> None:
    """The same service, a different door, and the row says which."""
    from apps.core import context

    with context.bound(door="mcp"):
        tool("create_organization")(
            context_for(owner, tenant, tree["root"]),
            parent_id=tree["root"].pk,
            name="From MCP",
            slug="from-mcp",
        )

    row = (
        AuditEntry.objects.for_tenant(tenant)
        .filter(action="core.create_organization", outcome="ok")
        .order_by("-created_at")
        .first()
    )
    assert row is not None
    assert row.door == "mcp"


def test_an_invitation_issued_over_mcp_returns_its_token_once(
    owner: User, tenant: Tenant, tree: dict[str, Organization]
) -> None:
    """The machine door may invite; only the issue call ever carries the token."""
    issued = tool("create_invitation")(
        context_for(owner, tenant, tree["root"]), email="agent-invited@example.com"
    )

    assert issued.token
    assert issued.invitation.email == "agent-invited@example.com"

    listed = tool("list_invitations")(context_for(owner, tenant, tree["root"]), include_count=True)
    assert listed.count == 1
    assert not hasattr(listed.items[0], "token")
    assert Invitation.objects.for_tenant(tenant).count() == 1
