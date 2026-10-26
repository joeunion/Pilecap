"""The machine door onto imports — each tool calls the selector and service its REST twin calls."""

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
from apps.djb_imports.api import (
    ORDERING,
    apply_import_route,
    cancel_import_route,
    create_import_route,
    list_import_rows_route,
    list_imports_route,
    retrieve_import,
    staged_out,
)
from apps.djb_imports.models import Import, ImportRow
from apps.djb_imports.schemas import (
    DjbImportFilter,
    DjbImportOut,
    DjbImportPage,
    DjbImportRowOut,
    DjbImportRowPage,
    DjbImportStagedOut,
)
from apps.djb_imports.selectors import get_import, get_import_source, list_import_rows, list_imports
from apps.djb_imports.services import apply_import, cancel_import, create_import


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(name="list_djb_imports", description=contract_of(list_imports_route))
    def list_imports_tool(
        ctx: Context[Any],
        status: str | None = None,
        kind: str | None = None,
        ordering: str = "-created_at",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> DjbImportPage:
        with tool_call(ctx) as acting:
            runs: QuerySet[Import] = DjbImportFilter(status=status, kind=kind).filter(
                list_imports(tenant=acting_tenant(acting), org=acting.org, actor=acting.actor())
            )
            runs = ordered_by(runs, ordering, allowed=ORDERING, default="-created_at")
            page = cursor_page(
                runs,
                tenant=acting_tenant(acting),
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return DjbImportPage(
                items=[DjbImportOut.from_orm(run) for run in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="create_djb_import", description=contract_of(create_import_route))
    def create_import_tool(
        ctx: Context[Any], kind: str, file_id: UUID, idempotency_key: str = ""
    ) -> DjbImportStagedOut:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            version = get_import_source(
                tenant=acting_tenant(acting), file_id=file_id, org=acting.org, actor=actor
            )
            run, created = create_import(
                tenant=acting_tenant(acting),
                actor=actor,
                kind=kind,
                file_version=version,
                idempotency_key=idempotency_key,
            )
            return staged_out(run, created)

    @server.tool(name="get_djb_import", description=contract_of(retrieve_import))
    def get_import_tool(ctx: Context[Any], import_id: UUID) -> DjbImportOut:
        with tool_call(ctx) as acting:
            return DjbImportOut.from_orm(
                get_import(
                    tenant=acting_tenant(acting),
                    import_id=import_id,
                    org=acting.org,
                    actor=acting.actor(),
                )
            )

    @server.tool(name="list_djb_import_rows", description=contract_of(list_import_rows_route))
    def list_import_rows_tool(
        ctx: Context[Any],
        import_id: UUID,
        outcome: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> DjbImportRowPage:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            run = get_import(
                tenant=acting_tenant(acting), import_id=import_id, org=acting.org, actor=actor
            )
            rows: QuerySet[ImportRow] = list_import_rows(
                tenant=acting_tenant(acting),
                import_=run,
                org=acting.org,
                actor=actor,
                outcome=outcome,
            )
            page = cursor_page(
                rows,
                tenant=acting_tenant(acting),
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return DjbImportRowPage(
                items=[DjbImportRowOut.from_orm(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="apply_djb_import", description=contract_of(apply_import_route))
    def apply_import_tool(ctx: Context[Any], import_id: UUID) -> DjbImportOut:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            run = get_import(
                tenant=acting_tenant(acting), import_id=import_id, org=acting.org, actor=actor
            )
            return DjbImportOut.from_orm(
                apply_import(tenant=acting_tenant(acting), actor=actor, import_=run)
            )

    @server.tool(name="cancel_djb_import", description=contract_of(cancel_import_route))
    def cancel_import_tool(ctx: Context[Any], import_id: UUID) -> DjbImportOut:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            run = get_import(
                tenant=acting_tenant(acting), import_id=import_id, org=acting.org, actor=actor
            )
            return DjbImportOut.from_orm(
                cancel_import(tenant=acting_tenant(acting), actor=actor, import_=run)
            )
