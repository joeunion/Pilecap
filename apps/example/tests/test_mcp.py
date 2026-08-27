"""The machine door onto widgets, and the parity it owes the human one.

Two kinds of test here, and they answer different questions.

**Parity** (`test_every_rest_capability_...`) reads the *real* registries out of
`manage.py introspect` — the ninja routes and the MCP tools the server actually
holds — and refuses a REST capability that has no tool. It is house rule 17 with
teeth: adding a route to `api.py` and forgetting `mcp.py` fails here, in a test
that names the missing tool.

**Behaviour** calls the tool functions directly, with a fake `Context` carrying a
`Principal` on its scope — exactly what `config.mcp`'s token middleware leaves
there. Calling the function rather than driving JSON-RPC is deliberate: the
transport runs a tool body on a worker thread with its own database connection,
which cannot see a test's uncommitted rows, and the thing under test here is the
tool, not the transport. The transport has its own tests
(`apps/core/tests/test_mcp.py`).
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

import pytest
from django.core.management import call_command
from django.test import Client
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.core import context
from apps.core.actor import Actor
from apps.core.audit import AuditEntry
from apps.core.mcp import SCOPE_KEY, Principal
from apps.core.models import Organization, Tenant
from apps.core.services import root_organization
from apps.example.mcp import register
from apps.example.models import Widget
from apps.example.schemas import WidgetOut
from apps.example.services import create_widget
from apps.workflows.models import WorkflowRun
from apps.workflows.services import finish_run, workflow_id
from config.api import as_the_door_renders

pytestmark = pytest.mark.django_db

# The whole point of the file: for every REST capability, the tool that is its
# twin. A new route with no entry here fails the parity test, and an entry with
# no tool fails it too.
# Measured at ten rows, not guessed: the page and its COUNT. There is no session
# row, no middleware and no savepoint out here — a tool call is not a request —
# which is why this budget is smaller than the HTTP list's rather than the same
# number written twice.
# ADR core-18 took one statement OFF this pin: the default list issues no
# COUNT any more — `has_more` comes from fetching one row more than asked
# for. `?include_count=true` puts it back, and costs exactly one more.
LIST_QUERY_BUDGET = 1

# The two doors this file compares, spelled once.
JSON = "application/json"
APPROVE_URL = "/api/v1/widgets/{}/approve/"

TOOL_FOR_ROUTE: dict[str, str] = {
    "widget-list": "list_widgets",
    "widget-detail": "get_widget",
    "widget-create": "create_widget",
    "widget-update": "update_widget",
    "widget-approve": "approve_widget",
    "widget-delete": "delete_widget",
    # The hierarchy's own capabilities. `governing_widget_policy-detail` is the
    # one whose twin matters most: an agent that cannot ask what governs it can
    # only guess, and guessing is what a policy exists to stop.
    "widget_stats-detail": "get_widget_stats",
    "widget_policies-list": "list_widget_policies",
    "widget_policy-create": "create_widget_policy",
    "governing_widget_policy-detail": "get_governing_widget_policy",
    "widget_entries-list": "list_widget_entries",
    # There is deliberately no update or delete twin for an entry, on either
    # door: `WidgetEntry` is append-only, so the capability does not exist to
    # be mirrored.
    "widget_entry-record": "record_widget_entry",
}


# --- A tool call, without a transport ----------------------------------------


@dataclass
class _FakeRequest:
    """Just enough of a Starlette request: the ASGI scope, and nothing else."""

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


def example_server() -> MCPServer[Any]:
    """A server holding this app's tools and nothing else."""
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    return server


def tool(name: str) -> Callable[..., Any]:
    """The function behind a registered tool.

    The manager is private API, and reaching into it is still better than the
    alternative: keeping a second reference to every tool function just so a test
    can call it would be a copy of the registry that can disagree with the
    registry.
    """
    registered = example_server()._tool_manager.get_tool(name)
    assert registered is not None, f"{name} is not registered"
    return registered.fn


def introspected() -> dict[str, Any]:
    """What `manage.py introspect` reports — the real registries, as JSON."""
    out = io.StringIO()
    call_command("introspect", stdout=out)
    payload: dict[str, Any] = json.loads(out.getvalue())
    return payload


# --- Door parity -------------------------------------------------------------


def test_every_rest_capability_is_on_the_machine_door_too() -> None:
    """House rule 17, read out of the two registries rather than asserted by hand."""
    payload = introspected()
    routes = {
        str(route["name"]).removeprefix("api:")
        for route in payload["routes"]
        if str(route["view"]).startswith("apps.example.api.")
    }
    assert routes == set(TOOL_FOR_ROUTE), (
        "A widget route has no entry in TOOL_FOR_ROUTE: either the machine door "
        "is missing a capability the human door has, or this table is stale."
    )

    tools = {str(one["name"]) for one in payload["tools"]}
    assert set(TOOL_FOR_ROUTE.values()) <= tools


def test_the_app_registers_those_tools_and_no_others() -> None:
    """The reverse direction: a tool with no route is a door disagreement too."""
    registered = {one.name for one in example_server()._tool_manager.list_tools()}
    assert registered == set(TOOL_FOR_ROUTE.values())


def test_every_tool_describes_itself() -> None:
    """A tool with no description is one an agent has to guess at."""
    for one in example_server()._tool_manager.list_tools():
        assert one.description, f"{one.name} has no description"


def test_a_tool_and_its_route_answer_with_the_same_row(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The same widget, through both doors, byte for byte the same shape."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Twin", notes="hello")

    api.force_login(owner)
    over_http = api.get(f"/api/v1/widgets/{widget.pk}/")
    assert over_http.status_code == 200

    over_mcp = tool("get_widget")(ctx=context_for(owner, tenant), widget_id=widget.pk)
    assert isinstance(over_mcp, WidgetOut)
    assert as_the_door_renders(over_mcp.model_dump(mode="json")) == as_the_door_renders(
        json.loads(over_http.content)
    )


# --- What the tools do -------------------------------------------------------


def test_list_widgets_is_scoped_to_the_tokens_tenant(
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    stranger_actor: Actor,
) -> None:
    mine = create_widget(tenant=tenant, actor=owner_actor, name="Mine")
    create_widget(tenant=other_tenant, actor=stranger_actor, name="Theirs")

    page = tool("list_widgets")(ctx=context_for(owner, tenant))
    assert len(page.items) == 1
    assert [item.id for item in page.items] == [mine.pk]


def test_list_widgets_paginates_searches_and_orders(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    for index in range(3):
        create_widget(tenant=tenant, actor=owner_actor, name=f"Widget {index}", notes="prose")
    create_widget(tenant=tenant, actor=owner_actor, name="Other", notes="nothing")

    listing = tool("list_widgets")
    ctx = context_for(owner, tenant)

    page = listing(ctx=ctx, limit=2, include_count=True)
    assert page.count == 4
    assert len(page.items) == 2
    assert page.has_more is True

    second = listing(ctx=ctx, cursor=page.next_cursor, limit=2)
    assert [item.id for item in second.items] != [item.id for item in page.items]
    assert second.has_more is False

    found = listing(ctx=ctx, q="prose")
    assert len(found.items) == 3

    named = listing(ctx=ctx, name="Other")
    assert [item.name for item in named.items] == ["Other"]

    ordered = listing(ctx=ctx, ordering="name")
    assert [item.name for item in ordered.items][0] == "Other"


def test_an_ordering_the_route_did_not_offer_is_refused(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The same allow-list as the HTTP list, because it is literally the same one."""
    with pytest.raises(ToolError) as refused:
        tool("list_widgets")(ctx=context_for(owner, tenant), ordering="owner__password")
    assert "invalid" in str(refused.value)


def test_a_widget_in_another_tenant_is_not_found(
    tenant: Tenant, other_tenant: Tenant, owner: User, stranger_actor: Actor
) -> None:
    theirs = create_widget(tenant=other_tenant, actor=stranger_actor, name="Theirs")
    with pytest.raises(ToolError) as refused:
        tool("get_widget")(ctx=context_for(owner, tenant), widget_id=theirs.pk)
    # `not_found`, never `forbidden`: a 403 here would confirm the row exists.
    assert "not_found" in str(refused.value)


def test_create_widget_writes_the_row_and_owns_it(tenant: Tenant, owner: User) -> None:
    out = tool("create_widget")(ctx=context_for(owner, tenant), name="From a machine", notes="n")

    widget = Widget.objects.for_tenant(tenant).get(pk=out.id)
    assert widget.name == "From a machine"
    assert widget.owner_id == owner.pk
    assert widget.tenant_id == tenant.pk


def test_create_widget_is_recorded_as_an_agent(tenant: Tenant, owner: User) -> None:
    """A token is a machine acting as a person, and the audit row says so."""
    from apps.core.audit import AuditEntry

    AuditEntry.objects.all().delete()
    tool("create_widget")(ctx=context_for(owner, tenant), name="Machine made")

    entry = AuditEntry.objects.for_tenant(tenant).get(action="example.create_widget")
    assert entry.actor_kind == "agent"
    assert entry.actor_user_id == owner.pk


def test_update_widget_changes_only_what_it_was_given(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Before", notes="keep")

    out = tool("update_widget")(ctx=context_for(owner, tenant), widget_id=widget.pk, name="After")
    assert out.name == "After"
    assert out.notes == "keep"


def test_delete_widget_removes_the_row_and_says_which(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Doomed")

    out = tool("delete_widget")(ctx=context_for(owner, tenant), widget_id=widget.pk)
    assert out.id == widget.pk
    assert Widget.objects.for_tenant(tenant).count() == 0


def test_a_tool_authorizes_through_the_service_not_the_door(
    tenant: Tenant, owner: User, member: User, owner_actor: Actor
) -> None:
    """A plain member may not edit somebody else's widget — same answer as REST."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Not yours")

    with pytest.raises(ToolError) as refused:
        tool("update_widget")(ctx=context_for(member, tenant), widget_id=widget.pk, name="Mine now")
    assert "forbidden" in str(refused.value)


def test_a_token_with_no_tenant_cannot_write(nomad: User) -> None:
    """Fails closed, exactly as the HTTP door does with no tenant."""
    with pytest.raises(ToolError) as refused:
        tool("create_widget")(ctx=context_for(nomad, None), name="Nowhere")
    assert "no_tenant" in str(refused.value)


def test_a_token_with_no_tenant_reads_nothing(nomad: User) -> None:
    page = tool("list_widgets")(ctx=context_for(nomad, None))
    assert len(page.items) == 0
    assert page.items == []


def test_a_call_with_no_principal_is_refused(tenant: Tenant) -> None:
    """There is no unauthenticated tool call to forget to check."""
    empty = Context(request_context=cast(Any, _FakeRequestContext(request=_FakeRequest())))
    with pytest.raises(Exception) as refused:
        tool("list_widgets")(ctx=empty)
    assert "principal" in str(refused.value)


def test_the_id_a_tool_takes_is_a_uuid(tenant: Tenant, owner: User, owner_actor: Actor) -> None:
    """The schema is the contract on this door too: ids are UUIDs, not strings."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Typed")
    schema = example_server()._tool_manager.get_tool("get_widget")
    assert schema is not None
    assert schema.parameters["properties"]["widget_id"]["format"] == "uuid"
    assert isinstance(widget.pk, UUID)


def test_the_list_tool_has_a_query_budget(
    tenant: Tenant, owner: User, owner_actor: Actor, django_assert_num_queries: Any
) -> None:
    """The same pin the HTTP list carries, for the same failure.

    `WidgetOut.owner_email` walks a relation for every row, so without the
    selector's `select_related` a page of fifty is fifty-one queries. Measured at
    ten rows: one COUNT and one page.
    """
    for index in range(10):
        create_widget(tenant=tenant, actor=owner_actor, name=f"Widget {index}")

    listing = tool("list_widgets")
    ctx = context_for(owner, tenant)
    with django_assert_num_queries(LIST_QUERY_BUDGET):
        page = listing(ctx=ctx)
    assert len(page.items) == 10


# --- Approval, on the machine door -------------------------------------------


def test_approve_widget_ends_the_wait_and_answers_with_the_row(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The agent's version of the button. Same service, same shape as the route.

    No worker here and no Temporal server: the signal is registered on the
    transaction's commit, and what this asserts is the tool's half — it
    authorized, it found the run, and it answered with the widget. That the
    signal actually reaches a workflow and ends its week-long wait is
    `test_workflows.py`'s, against a real server.
    """
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Waiting")

    out = tool("approve_widget")(ctx=context_for(owner, tenant), widget_id=widget.pk)

    assert isinstance(out, WidgetOut)
    assert out.id == widget.pk


def test_approving_a_widget_in_another_tenant_is_not_found(
    tenant: Tenant, other_tenant: Tenant, owner: User, stranger_actor: Actor
) -> None:
    theirs = create_widget(tenant=other_tenant, actor=stranger_actor, name="Theirs")
    with pytest.raises(ToolError) as refused:
        tool("approve_widget")(ctx=context_for(owner, tenant), widget_id=theirs.pk)
    assert "not_found" in str(refused.value)


def test_a_member_may_not_approve(tenant: Tenant, member: User, owner_actor: Actor) -> None:
    """The same answer the HTTP door gives, because it is the same policy."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Not yours to approve")
    with pytest.raises(ToolError) as refused:
        tool("approve_widget")(ctx=context_for(member, tenant), widget_id=widget.pk)
    assert "forbidden" in str(refused.value)


def test_approving_a_run_that_has_already_ended_is_a_conflict(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Already done")
    finish_run(
        tenant=tenant,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key=str(widget.pk)),
        status=WorkflowRun.Status.COMPLETED,
    )
    with pytest.raises(ToolError) as refused:
        tool("approve_widget")(ctx=context_for(owner, tenant), widget_id=widget.pk)
    assert "conflict" in str(refused.value)


def test_both_doors_leave_audit_rows_that_differ_only_in_the_door(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """R5-2's honest form: two doors, one service, one difference.

    Two widgets rather than one, because approving the same run twice would
    make the second call's audit row a different fact. What is compared is
    everything the row says about *who did what*, and the field that is allowed
    to disagree is the door it came in by.
    """
    over_http_widget = create_widget(tenant=tenant, actor=owner_actor, name="Through the browser")
    over_mcp_widget = create_widget(tenant=tenant, actor=owner_actor, name="Through the agent")
    AuditEntry.objects.all().delete()

    api.force_login(owner)
    response = api.post(APPROVE_URL.format(over_http_widget.pk), content_type=JSON)
    assert response.status_code == 200, response.content

    # What the transport binds around a tool call (`config.mcp`), bound by hand
    # because this file calls the tool function rather than driving JSON-RPC.
    # The middleware that really binds it has its own test in
    # `apps/core/tests/test_mcp.py`; what is under test here is the row.
    context.bind(door="mcp", actor_kind="agent")
    tool("approve_widget")(ctx=context_for(owner, tenant), widget_id=over_mcp_widget.pk)

    rows = {
        entry.object_id: entry
        for entry in AuditEntry.objects.for_tenant(tenant).filter(action="example.approve_widget")
    }
    rest = rows[over_http_widget.pk]
    machine = rows[over_mcp_widget.pk]
    assert (rest.door, machine.door) == ("rest", "mcp")
    assert rest.outcome == machine.outcome == "ok"
    assert rest.actor_user_id == machine.actor_user_id == owner.pk
    assert rest.action == machine.action == "example.approve_widget"
    # The one honest difference beyond the door: a token is a machine acting as
    # a person, and the audit row has always said so.
    assert (rest.actor_kind, machine.actor_kind) == ("human", "agent")


def test_the_signal_and_the_approval_share_a_correlation_id(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """R5-3: two services, one request, one chain — findable months later."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Chained")
    AuditEntry.objects.all().delete()

    api.force_login(owner)
    response = api.post(APPROVE_URL.format(widget.pk), content_type=JSON)
    assert response.status_code == 200, response.content

    approval = AuditEntry.objects.for_tenant(tenant).get(action="example.approve_widget")
    signalled = AuditEntry.objects.for_tenant(tenant).get(action="workflows.signal_workflow")
    assert approval.outcome == signalled.outcome == "ok"
    assert approval.correlation_id
    assert approval.correlation_id == signalled.correlation_id
