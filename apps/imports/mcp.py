"""The machine door onto imports — the same six capabilities, over the same seams.

Every tool calls the selector or service its REST twin calls, answers the same
schema, and says the same thing: each `description=` is `contract_of(<the
route>)` (house rule 41). Who is calling comes from the principal, never an
argument; refusals are mapped once, by `tool_call`.
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
from apps.imports.api import (
    ORDERING,
    apply_import_route,
    cancel_import_route,
    create_import_route,
    list_import_rows_route,
    list_imports_route,
    retrieve_import,
    staged_out,
)
from apps.imports.models import Import, ImportRow
from apps.imports.schemas import (
    ImportFilter,
    ImportOut,
    ImportPage,
    ImportRowOut,
    ImportRowPage,
    ImportStagedOut,
)
from apps.imports.selectors import get_import, get_import_source, list_import_rows, list_imports
from apps.imports.services import apply_import, cancel_import, create_import


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(name="list_imports", description=contract_of(list_imports_route))
    def list_imports_tool(
        ctx: Context[Any],
        status: str | None = None,
        kind: str | None = None,
        ordering: str = "-created_at",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> ImportPage:
        with tool_call(ctx) as acting:
            runs: QuerySet[Import] = ImportFilter(status=status, kind=kind).filter(
                list_imports(tenant=acting.tenant, org=acting.org, actor=acting.actor())
            )
            runs = ordered_by(runs, ordering, allowed=ORDERING, default="-created_at")
            page = cursor_page(
                runs, tenant=acting.tenant, cursor=cursor, limit=limit, include_count=include_count
            )
            return ImportPage(
                items=[ImportOut.from_orm(run) for run in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="create_import", description=contract_of(create_import_route))
    def create_import_tool(
        ctx: Context[Any], kind: str, file_id: UUID, idempotency_key: str = ""
    ) -> ImportStagedOut:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            version = get_import_source(
                tenant=acting.tenant, file_id=file_id, org=acting.org, actor=actor
            )
            run, created = create_import(
                tenant=acting_tenant(acting),
                actor=actor,
                kind=kind,
                file_version=version,
                idempotency_key=idempotency_key,
            )
            return staged_out(run, created)

    @server.tool(name="get_import", description=contract_of(retrieve_import))
    def get_import_tool(ctx: Context[Any], import_id: UUID) -> ImportOut:
        with tool_call(ctx) as acting:
            return ImportOut.from_orm(
                get_import(
                    tenant=acting.tenant, import_id=import_id, org=acting.org, actor=acting.actor()
                )
            )

    @server.tool(name="list_import_rows", description=contract_of(list_import_rows_route))
    def list_import_rows_tool(
        ctx: Context[Any],
        import_id: UUID,
        outcome: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> ImportRowPage:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            run = get_import(tenant=acting.tenant, import_id=import_id, org=acting.org, actor=actor)
            rows: QuerySet[ImportRow] = list_import_rows(
                tenant=acting.tenant, import_=run, org=acting.org, actor=actor, outcome=outcome
            )
            page = cursor_page(
                rows, tenant=acting.tenant, cursor=cursor, limit=limit, include_count=include_count
            )
            return ImportRowPage(
                items=[ImportRowOut.from_orm(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="apply_import", description=contract_of(apply_import_route))
    def apply_import_tool(ctx: Context[Any], import_id: UUID) -> ImportOut:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            run = get_import(tenant=acting.tenant, import_id=import_id, org=acting.org, actor=actor)
            return ImportOut.from_orm(
                apply_import(tenant=acting_tenant(acting), actor=actor, import_=run)
            )

    @server.tool(name="cancel_import", description=contract_of(cancel_import_route))
    def cancel_import_tool(ctx: Context[Any], import_id: UUID) -> ImportOut:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            run = get_import(tenant=acting.tenant, import_id=import_id, org=acting.org, actor=actor)
            return ImportOut.from_orm(
                cancel_import(tenant=acting_tenant(acting), actor=actor, import_=run)
            )
