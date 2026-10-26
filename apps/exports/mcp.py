"""The machine door onto exports — each tool calls the selector or service its REST twin calls.

`download_export` answers where the archive is, never its bytes: a tool result cannot stream one.
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
from apps.exports.api import (
    ORDERING,
    create_export_route,
    download_export_route,
    list_exports_route,
    retrieve_export,
)
from apps.exports.models import Export
from apps.exports.schemas import (
    ExportDownloadOut,
    ExportFilter,
    ExportOut,
    ExportPage,
)
from apps.exports.selectors import get_downloadable_export, get_export, list_exports
from apps.exports.services import create_export


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(
        name="list_exports",
        description=contract_of(list_exports_route),
    )
    def list_exports_tool(
        ctx: Context[Any],
        status: str | None = None,
        ordering: str = "-created_at",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> ExportPage:
        with tool_call(ctx) as acting:
            # Scoped first, narrowed after: narrowing a queryset cannot widen its tenant.
            exports: QuerySet[Export] = ExportFilter(status=status).filter(
                list_exports(tenant=acting_tenant(acting), org=acting.org, actor=acting.actor())
            )
            exports = ordered_by(exports, ordering, allowed=ORDERING, default="-created_at")
            page = cursor_page(
                exports,
                tenant=acting_tenant(acting),
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return ExportPage(
                items=[ExportOut.from_orm(export) for export in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="get_export",
        description=contract_of(retrieve_export),
    )
    def get_export_tool(ctx: Context[Any], export_id: UUID) -> ExportOut:
        with tool_call(ctx) as acting:
            return ExportOut.from_orm(
                get_export(
                    tenant=acting_tenant(acting),
                    export_id=export_id,
                    org=acting.org,
                    actor=acting.actor(),
                )
            )

    @server.tool(
        name="create_export",
        description=contract_of(create_export_route),
    )
    def create_export_tool(
        ctx: Context[Any],
        scope: str = "organization",
        idempotency_key: str = "",
    ) -> ExportOut:
        with tool_call(ctx) as acting:
            return ExportOut.from_orm(
                create_export(
                    tenant=acting_tenant(acting),
                    actor=acting.actor(),
                    scope=scope,
                    idempotency_key=idempotency_key,
                )
            )

    @server.tool(
        name="download_export",
        description=contract_of(download_export_route),
    )
    def download_export_tool(ctx: Context[Any], export_id: UUID) -> ExportDownloadOut:
        with tool_call(ctx) as acting:
            return ExportDownloadOut.from_orm(
                get_downloadable_export(
                    tenant=acting_tenant(acting),
                    actor=acting.actor(),
                    export_id=export_id,
                )
            )
