"""The machine door onto the run ledger — every capability the REST door has.

Door parity (house rule 17): the four tools here run over the *same* selectors,
the *same* service and the *same* schemas as `api.py`, so an agent asking "did
that sync finish, and can you run it again" gets the answer a person gets.

**And the same words** (ADR api-1, house rule 41): every `description=` below is
`contract_of(<the REST route>)` — the contract half of the very docstring the
OpenAPI document describes that route with — so one capability cannot be
explained two ways. A description typed here would be the first place the doors
drift, and prose drifts long before behaviour does.

Two shapes are worth reading for, because they are what an agent will try to go
around:

* **`replay_run` is the actor's own failed runs and nothing else.** A run
  somebody else started answers `not_found`, exactly as another tenant's does —
  the same string, from the same composer, so an agent cannot learn from the
  wording that the row exists.
* **`cancel_run` is the actor's own running ones, and it answers with the row
  UNCHANGED.** Stopping a job is a request; the row says `cancelled` only when
  the execution has actually stopped and something witnessed it (ADR
  workflows-7). An agent that treats this tool's answer as the stop having
  happened has misread it in exactly the way a person misreads the same answer,
  which is why the sentence saying so is in the one docstring both doors render
  rather than in a note here.
* **there is no `signal_run` and no `retry_run`.** An agent is exactly the
  caller that will end a wait to make a task look finished; a signal needs the
  domain service that owns the wait in front of it, and that service has its own
  door with its own check (`example.approve_widget` is the worked one).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api import ordered_by
from apps.core.api.docs import contract_of
from apps.core.api.pagination import cursor_page
from apps.core.mcp import acting_tenant, tool_call
from apps.workflows.api import (
    ORDERING,
    cancel_run_route,
    list_runs_route,
    replay_run_route,
    retrieve_run,
)
from apps.workflows.models import WorkflowRun
from apps.workflows.schemas import WorkflowRunFilter, WorkflowRunOut, WorkflowRunPage
from apps.workflows.selectors import get_run, list_runs
from apps.workflows.services import cancel_run, start_replay


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(name="list_runs", description=contract_of(list_runs_route))
    def list_runs_tool(
        ctx: Context[Any],
        status: str | None = None,
        type: str | None = None,
        mine: bool = True,
        ordering: str = "-started_at",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> WorkflowRunPage:
        with tool_call(ctx) as acting:
            # Scoped and authorized first, narrowed only after — the type widens
            # from `ScopedQuerySet` to `QuerySet` because filtering returns the
            # plain one, and narrowing a queryset cannot widen its tenant.
            runs: QuerySet[WorkflowRun] = WorkflowRunFilter(status=status, type=type).filter(
                list_runs(tenant=acting.tenant, actor=acting.actor(), mine=mine)
            )
            runs = ordered_by(runs, ordering, allowed=ORDERING, default="-started_at")
            page = cursor_page(
                runs,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return WorkflowRunPage(
                items=[WorkflowRunOut.from_orm(run) for run in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="get_run", description=contract_of(retrieve_run))
    def get_run_tool(ctx: Context[Any], run_id: UUID) -> WorkflowRunOut:
        with tool_call(ctx) as acting:
            # A run in another tenant is `not_found`, exactly as it is over
            # HTTP: a refusal that distinguished the two would tell the caller
            # the row exists, which is the fact the scoping was hiding.
            return WorkflowRunOut.from_orm(
                get_run(tenant=acting.tenant, actor=acting.actor(), run_id=run_id)
            )

    @server.tool(name="replay_run", description=contract_of(replay_run_route))
    def replay_run_tool(ctx: Context[Any], run_id: UUID) -> WorkflowRunOut:
        with tool_call(ctx) as acting:
            return WorkflowRunOut.from_orm(
                start_replay(
                    tenant=acting_tenant(acting),
                    actor=acting.actor(),
                    run_id=run_id,
                )
            )

    @server.tool(name="cancel_run", description=contract_of(cancel_run_route))
    def cancel_run_tool(ctx: Context[Any], run_id: UUID) -> WorkflowRunOut:
        with tool_call(ctx) as acting:
            # The row comes back UNCHANGED — still `running` — because the
            # service stamps nothing and the ledger's third word is witnessed
            # rather than asserted (ADR workflows-7). An agent that reads this
            # answer as "it stopped" has read the same answer a person reads,
            # which is what door parity is for; the contract sentence both doors
            # render says to poll.
            return WorkflowRunOut.from_orm(
                cancel_run(
                    tenant=acting_tenant(acting),
                    actor=acting.actor(),
                    run_id=run_id,
                )
            )
