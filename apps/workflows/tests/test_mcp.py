"""The machine door onto the run ledger, and the parity it owes the human one.

Three questions, and they are not the same question.

**Existence** — house rule 17, read out of the real registries (`manage.py
introspect`) rather than asserted by hand: a route in `api.py` with no tool in
`mcp.py` fails here, naming the tool that is missing.

**Shape** — the same run through both doors, field for field, so a tool that
returns "the same thing, roughly" fails rather than reviews.

**Refusals, byte-identical.** Every one of
`start_replay`'s five refusals is driven over both doors and the machine door's
rendering is string-compared against the REST body: one composer
(`wire_refusal`), two renderings (`config/api.py` as JSON, `core.mcp.tool_call`
through `refusal_message`), and never a route or a tool shaping a body of its
own. The two `not_found`s matter most: a colleague's run and another tenant's
run must be indistinguishable, and comparing the whole body is what proves it
rather than comparing a status code.

Tools are called as functions with a fake `Context` carrying the `Principal`
the transport's middleware would have left on the scope. The transport has its
own tests (`apps/core/tests/test_mcp.py`); what is under test here is the tool.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.core import context
from apps.core.audit import AuditEntry
from apps.core.exceptions import Conflict, NotFound, refusal_message, wire_refusal
from apps.core.models import Tenant
from apps.core.services import root_organization
from apps.core.tests.mcp_context import context_for
from apps.workflows.mcp import register
from apps.workflows.models import WorkflowRun
from apps.workflows.services import HISTORY_RETENTION, _starter_actor, record_run, workflow_id
from config.api import as_the_door_renders

pytestmark = pytest.mark.django_db

JSON = "application/json"
RUNS_URL = "/api/v1/runs/"

# The whole point of the file: for every REST capability, the tool that is its
# twin. A new route with no entry here fails the parity test, and an entry with
# no tool fails it too.
TOOL_FOR_ROUTE: dict[str, str] = {
    "run-list": "list_runs",
    "run-detail": "get_run",
    "run-replay": "replay_run",
    "run-cancel": "cancel_run",
    # There is deliberately no `signal_run` and no `retry_run` on either door:
    # signalling needs the domain service that owns the wait in front of it, so
    # the capability does not exist here to be mirrored.
}

# The body of a `not_found`, composed once. Both doors render this object;
# neither is allowed to build its own.
NOT_FOUND = wire_refusal(NotFound())


# --- A tool call, without a transport ----------------------------------------


def workflows_server() -> MCPServer[Any]:
    """A server holding this app's tools and nothing else."""
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    return server


def tool(name: str) -> Callable[..., Any]:
    """The function behind a registered tool."""
    registered = workflows_server()._tool_manager.get_tool(name)
    assert registered is not None, f"{name} is not registered"
    return registered.fn


def introspected() -> dict[str, Any]:
    """What `manage.py introspect` reports — the real registries, as JSON."""
    out = io.StringIO()
    call_command("introspect", stdout=out)
    payload: dict[str, Any] = json.loads(out.getvalue())
    return payload


def _failed_run(
    *, tenant: Tenant, user: User | None, key: str, started_at: Any = None
) -> WorkflowRun:
    run = record_run(
        tenant=tenant,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key=key),
        workflow_type="WidgetOnboardingWorkflow",
        input_digest="d" * 64,
        actor=_starter_actor(tenant=tenant, user=user),
    )
    run.status = WorkflowRun.Status.FAILED
    run.error = "the activity said no"
    run.run_id = f"execution-{key}"
    run.finished_at = timezone.now()
    if started_at is not None:
        run.started_at = started_at
    run.save()
    return run


# --- Door parity: existence ---------------------------------------------------


def test_every_rest_capability_is_on_the_machine_door_too() -> None:
    """House rule 17, read out of the two registries rather than asserted by hand."""
    payload = introspected()
    routes = {
        str(route["name"]).removeprefix("api:")
        for route in payload["routes"]
        if str(route["view"]).startswith("apps.workflows.api.")
    }
    assert routes == set(TOOL_FOR_ROUTE), (
        "A run route has no entry in TOOL_FOR_ROUTE: either the machine door is "
        "missing a capability the human door has, or this table is stale."
    )

    tools = {str(one["name"]) for one in payload["tools"]}
    assert set(TOOL_FOR_ROUTE.values()) <= tools


def test_the_app_registers_those_tools_and_no_others() -> None:
    """The reverse direction: a tool with no route is a door disagreement too."""
    registered = {one.name for one in workflows_server()._tool_manager.list_tools()}
    assert registered == set(TOOL_FOR_ROUTE.values())


def test_every_tool_describes_itself_in_the_routes_own_words() -> None:
    """Rule 41: one capability, one docstring, rendered by both doors."""
    from apps.core.api.docs import contract_of
    from apps.workflows.api import (
        cancel_run_route,
        list_runs_route,
        replay_run_route,
        retrieve_run,
    )

    described = {one.name: one.description for one in workflows_server()._tool_manager.list_tools()}
    assert described["list_runs"] == contract_of(list_runs_route)
    assert described["get_run"] == contract_of(retrieve_run)
    assert described["replay_run"] == contract_of(replay_run_route)
    assert described["cancel_run"] == contract_of(cancel_run_route)
    assert all(described.values()), "a tool with no description is one an agent guesses at"


# --- Door parity: shape -------------------------------------------------------


def test_a_tool_and_its_route_answer_with_the_same_row(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The same run, through both doors, field for field."""
    run = _failed_run(tenant=tenant, user=owner, key="twin")

    api.force_login(owner)
    over_http = api.get(f"{RUNS_URL}{run.pk}/")
    assert over_http.status_code == 200, over_http.content

    over_mcp = tool("get_run")(
        ctx=context_for(owner, tenant, root_organization(tenant=tenant)), run_id=run.pk
    )
    assert as_the_door_renders(over_http.json()) == as_the_door_renders(
        json.loads(over_mcp.model_dump_json())
    )


def test_the_two_lists_agree_including_the_mine_default(
    api: Client, tenant: Tenant, owner: User, member: User
) -> None:
    """`mine` defaults the same way at both doors, and widens the same way."""
    mine = _failed_run(tenant=tenant, user=owner, key="list-mine")
    theirs = _failed_run(tenant=tenant, user=member, key="list-theirs")

    api.force_login(owner)
    ctx = context_for(owner, tenant, root_organization(tenant=tenant))

    assert [row["id"] for row in api.get(RUNS_URL).json()["items"]] == [str(mine.pk)]
    assert [str(row.id) for row in tool("list_runs")(ctx=ctx).items] == [str(mine.pk)]

    wide_http = {row["id"] for row in api.get(f"{RUNS_URL}?mine=false").json()["items"]}
    wide_mcp = {str(row.id) for row in tool("list_runs")(ctx=ctx, mine=False).items}
    assert wide_http == wide_mcp == {str(mine.pk), str(theirs.pk)}


def test_another_tenants_runs_are_absent_from_the_machine_door_too(
    tenant: Tenant, other_tenant: Tenant, owner: User, stranger: User
) -> None:
    """The sibling test the machine door owes: scoping is not a REST feature."""
    _failed_run(tenant=tenant, user=owner, key="ours")
    theirs = _failed_run(tenant=other_tenant, user=stranger, key="theirs")

    page = tool("list_runs")(
        ctx=context_for(owner, tenant, root_organization(tenant=tenant)), mine=False
    )
    assert str(theirs.pk) not in [str(row.id) for row in page.items]


# --- Byte-identical refusals ----------------------------------------------------


def _both_doors_refuse(
    api: Client,
    owner: User,
    tenant: Tenant,
    run_id: Any,
    *,
    status: int,
    body: dict[str, Any],
) -> None:
    """One refusal, two doors, one composer. The criterion, spelled once."""
    api.force_login(owner)
    over_http = api.post(f"{RUNS_URL}{run_id}/replay/", content_type=JSON)
    assert over_http.status_code == status, over_http.content
    assert over_http.json() == body

    with pytest.raises(ToolError) as refused:
        tool("replay_run")(
            ctx=context_for(owner, tenant, root_organization(tenant=tenant)), run_id=run_id
        )
    assert str(refused.value) == refusal_message(body), "one composer, two doors"


def test_a_colleagues_run_refuses_identically_on_both_doors(
    api: Client, tenant: Tenant, owner: User, member: User
) -> None:
    """Not-yours, at both doors, in the same words."""
    run = _failed_run(tenant=tenant, user=member, key="colleague")
    _both_doors_refuse(api, owner, tenant, run.pk, status=404, body=NOT_FOUND)


def test_another_tenants_run_refuses_identically_on_both_doors(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, stranger: User
) -> None:
    """Not-theirs, at both doors — and in the *same words as not-yours*.

    That equality is the point of running both: if these two bodies ever differ,
    the wording itself becomes an existence oracle.
    """
    theirs = _failed_run(tenant=other_tenant, user=stranger, key="elsewhere")
    _both_doors_refuse(api, owner, tenant, theirs.pk, status=404, body=NOT_FOUND)


def test_an_unknown_id_refuses_identically_on_both_doors(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """And a guessed id is the third member of that one answer."""
    _both_doors_refuse(api, owner, tenant, uuid4(), status=404, body=NOT_FOUND)


def test_a_running_run_refuses_identically_on_both_doors(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """RUNNING → conflict, both doors, same sentence."""
    run = record_run(
        tenant=tenant,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key="live"),
        workflow_type="WidgetOnboardingWorkflow",
        actor=_starter_actor(tenant=tenant, user=owner),
    )
    body = wire_refusal(Conflict("That run is still running; there is nothing to replay yet."))
    _both_doors_refuse(api, owner, tenant, run.pk, status=409, body=body)


def test_a_completed_run_refuses_identically_on_both_doors(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """COMPLETED → conflict, in `record_run`'s own words, at both doors."""
    run = _failed_run(tenant=tenant, user=owner, key="done")
    run.status = WorkflowRun.Status.COMPLETED
    run.error = ""
    run.save(update_fields=["status", "error", "updated_at"])

    body = wire_refusal(
        Conflict(
            f"That job has already {run.status}. Running the same work again is a "
            "new job, not a repeat of that one — start it where it was started "
            "before."
        )
    )
    _both_doors_refuse(api, owner, tenant, run.pk, status=409, body=body)


def test_an_expired_history_refuses_identically_on_both_doors(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """FAILED + past retention → conflict naming retention, at both doors."""
    run = _failed_run(
        tenant=tenant,
        user=owner,
        key="ancient",
        started_at=timezone.now() - HISTORY_RETENTION - timedelta(days=1),
    )
    body = wire_refusal(
        Conflict(
            f"That job started more than {HISTORY_RETENTION.days} days ago and the "
            "record of what it was asked to do is no longer kept, so it cannot be "
            "restarted. Start the work again where it was started before."
        )
    )
    _both_doors_refuse(api, owner, tenant, run.pk, status=409, body=body)


# --- Cancel, over both doors ------------------------------------------------------


def _running_run(*, tenant: Tenant, user: User | None, key: str) -> WorkflowRun:
    """A row in the one state a cancel is legal from. `record_run` leaves it there."""
    return record_run(
        tenant=tenant,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key=key),
        workflow_type="WidgetOnboardingWorkflow",
        input_digest="c" * 64,
        actor=_starter_actor(tenant=tenant, user=user),
    )


def _both_doors_cancel_refuse(
    api: Client,
    owner: User,
    tenant: Tenant,
    run_id: Any,
    *,
    status: int,
    body: dict[str, Any],
) -> None:
    """The same criterion as `_both_doors_refuse`, over the cancel capability."""
    api.force_login(owner)
    over_http = api.post(f"{RUNS_URL}{run_id}/cancel/", content_type=JSON)
    assert over_http.status_code == status, over_http.content
    assert over_http.json() == body

    with pytest.raises(ToolError) as refused:
        tool("cancel_run")(
            ctx=context_for(owner, tenant, root_organization(tenant=tenant)), run_id=run_id
        )
    assert str(refused.value) == refusal_message(body), "one composer, two doors"


def test_cancel_answers_with_the_same_unchanged_row_at_both_doors(
    api: Client, tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """Door parity over the accepted cancel, and the row is UNCHANGED at both.

    Two rows rather than one, because a second cancel of the same row would be
    answering a different question by then — and the point of the assertion is
    that neither door moved the row, so both have to be asked from the same
    state.
    """
    over_http = _running_run(tenant=tenant, user=owner, key="cancel-rest-shape")
    over_mcp = _running_run(tenant=tenant, user=owner, key="cancel-mcp-shape")

    api.force_login(owner)
    rest = api.post(f"{RUNS_URL}{over_http.pk}/cancel/", content_type=JSON)
    assert rest.status_code == 200, rest.content
    machine = tool("cancel_run")(
        ctx=context_for(owner, tenant, root_organization(tenant=tenant)), run_id=over_mcp.pk
    )

    # The row as it is: still running, never finished, nothing stamped.
    assert rest.json()["status"] == WorkflowRun.Status.RUNNING
    assert rest.json()["finished_at"] is None
    assert machine.status == WorkflowRun.Status.RUNNING
    assert machine.finished_at is None

    # And field for field, the id aside — two rows, one shape.
    from_rest = as_the_door_renders(rest.json())
    from_mcp = as_the_door_renders(json.loads(machine.model_dump_json()))
    ignored = {"id", "workflow_id", "created_at", "started_at"}
    assert {k: v for k, v in from_rest.items() if k not in ignored} == {
        k: v for k, v in from_mcp.items() if k not in ignored
    }


def test_cancelling_a_colleagues_run_refuses_identically_on_both_doors(
    api: Client, tenant: Tenant, owner: User, member: User
) -> None:
    """Not-yours, at both doors, in the same words — the ownership wall's 404-shape."""
    run = _running_run(tenant=tenant, user=member, key="cancel-colleague")
    _both_doors_cancel_refuse(api, owner, tenant, run.pk, status=404, body=NOT_FOUND)


def test_cancelling_another_tenants_run_refuses_identically_on_both_doors(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, stranger: User
) -> None:
    """Not-theirs, in the same words as not-yours: the wording is not an oracle."""
    theirs = _running_run(tenant=other_tenant, user=stranger, key="cancel-elsewhere")
    _both_doors_cancel_refuse(api, owner, tenant, theirs.pk, status=404, body=NOT_FOUND)


def test_cancelling_an_unknown_id_refuses_identically_on_both_doors(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """And a guessed id is the third member of that one answer."""
    _both_doors_cancel_refuse(api, owner, tenant, uuid4(), status=404, body=NOT_FOUND)


def test_cancelling_a_finished_run_refuses_identically_on_both_doors(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """Not RUNNING → conflict naming the status, both doors, same sentence."""
    run = _failed_run(tenant=tenant, user=owner, key="cancel-too-late")
    body = wire_refusal(
        Conflict(
            f"That job has already {run.status} and can no longer be stopped. "
            "There is nothing left to cancel."
        )
    )
    _both_doors_cancel_refuse(api, owner, tenant, run.pk, status=409, body=body)


def test_replaying_a_cancelled_run_refuses_identically_on_both_doors(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """Criterion 5: a deliberate stop is not a failure, so it does not replay."""
    run = _failed_run(tenant=tenant, user=owner, key="cancel-then-replay")
    run.status = WorkflowRun.Status.CANCELLED
    run.error = ""
    run.save(update_fields=["status", "error", "updated_at"])

    body = wire_refusal(
        Conflict(
            f"That job was {run.status} on purpose, and a deliberate stop is not a "
            "failure — there is nothing to restart. Start the work again where it "
            "was started before."
        )
    )
    _both_doors_refuse(api, owner, tenant, run.pk, status=409, body=body)


def test_both_cancel_doors_leave_audit_rows_that_differ_only_in_the_door(
    api: Client, tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """For `cancel_run`: one service, two doors, `door` the one difference."""
    over_http = _running_run(tenant=tenant, user=owner, key="cancel-audit-rest")
    over_mcp = _running_run(tenant=tenant, user=owner, key="cancel-audit-mcp")
    AuditEntry.objects.all().delete()

    api.force_login(owner)
    assert api.post(f"{RUNS_URL}{over_http.pk}/cancel/", content_type=JSON).status_code == 200

    context.bind(door="mcp", actor_kind="agent")
    tool("cancel_run")(
        ctx=context_for(owner, tenant, root_organization(tenant=tenant)), run_id=over_mcp.pk
    )

    rows = {
        entry.object_id: entry
        for entry in AuditEntry.objects.for_tenant(tenant).filter(action="workflows.cancel_run")
    }
    rest = rows[over_http.pk]
    machine = rows[over_mcp.pk]
    assert (rest.door, machine.door) == ("rest", "mcp")
    assert rest.outcome == machine.outcome == "ok"
    assert rest.actor_user_id == machine.actor_user_id == owner.pk
    assert (rest.actor_kind, machine.actor_kind) == ("human", "agent")


def test_a_refused_cancel_leaves_no_ok_audit_row(
    api: Client, tenant: Tenant, owner: User, member: User
) -> None:
    """Criterion 6's other half: none for refused. A 404 is not a cancellation."""
    run = _running_run(tenant=tenant, user=member, key="cancel-refused-audit")
    AuditEntry.objects.all().delete()

    api.force_login(owner)
    assert api.post(f"{RUNS_URL}{run.pk}/cancel/", content_type=JSON).status_code == 404

    outcomes = [
        entry.outcome
        for entry in AuditEntry.objects.for_tenant(tenant).filter(action="workflows.cancel_run")
    ]
    assert "ok" not in outcomes


# --- The audit rows --------------------------------------------------------------


def test_both_doors_leave_audit_rows_that_differ_only_in_the_door(
    api: Client, tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """One service, two doors, one difference — `door`, and the actor's kind.

    Two runs rather than one, because replaying the same row twice would make
    the second call's audit row a different fact: the row is RUNNING by then.
    """
    over_http = _failed_run(tenant=tenant, user=owner, key="audit-rest")
    over_mcp = _failed_run(tenant=tenant, user=owner, key="audit-mcp")
    AuditEntry.objects.all().delete()

    api.force_login(owner)
    assert api.post(f"{RUNS_URL}{over_http.pk}/replay/", content_type=JSON).status_code == 200

    # What the transport binds around a tool call (`config.mcp`), bound by hand
    # because this file calls the tool function rather than driving JSON-RPC.
    context.bind(door="mcp", actor_kind="agent")
    tool("replay_run")(
        ctx=context_for(owner, tenant, root_organization(tenant=tenant)), run_id=over_mcp.pk
    )

    rows = {
        entry.object_id: entry
        for entry in AuditEntry.objects.for_tenant(tenant).filter(action="workflows.start_replay")
    }
    rest = rows[over_http.pk]
    machine = rows[over_mcp.pk]
    assert (rest.door, machine.door) == ("rest", "mcp")
    assert rest.outcome == machine.outcome == "ok"
    assert rest.actor_user_id == machine.actor_user_id == owner.pk
    assert (rest.actor_kind, machine.actor_kind) == ("human", "agent")


def test_a_no_tenant_read_is_the_same_refusal_at_both_doors(api: Client, nomad: User) -> None:
    """A caller who resolved no tenant reads `no_acting_scope` over REST and over MCP alike."""
    api.force_login(nomad)
    response = api.get(RUNS_URL)
    assert response.status_code == 403, response.content
    assert response.json()["code"] == "no_acting_scope"
    with pytest.raises(ToolError) as refused:
        tool("list_runs")(ctx=context_for(nomad, None, None))
    assert str(refused.value).startswith("no_acting_scope"), str(refused.value)
