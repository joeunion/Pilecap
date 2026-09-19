"""The machine door onto exports — the same four capabilities the REST door has.

Door parity (house rule 17): every capability `api.py` offers a person, this
offers a machine, over the *same* selectors, the *same* services and the *same*
schemas. And it **says** the same thing out of one docstring (house rule 41):
every `description=` below is `contract_of(<the REST route>)`, so the two doors
cannot come to describe one capability differently — prose drifts long before
behaviour does.

**This app takes no door-parity exemption, and that is worth saying because the
plan expected one.** The obvious asymmetry is the download: a tool result has no
equivalent of a response body streaming a gigabyte, so `download_export` answers
with *where* the archive is rather than *what* it is. That is the same move
`delete_widget` already makes — the HTTP door answers `204` because HTTP has a
way to say "gone", and the tool answers with the row that went, because a tool
result does not. One capability, two grammars, and the refusals are the same
three because both doors ask `api.downloadable_export`.

What a tool is allowed to be is thin: it takes **who is calling** from the
principal the token middleware left on the ASGI scope (never from an argument),
it calls services and selectors, and it maps no refusals of its own —
`tool_call` turns a domain exception into a `ToolError` once, the way
`config/api.py` turns one into a status code once.

The bodies are plain `def` rather than `async def`: the transport runs a
synchronous tool on a worker thread, which is where the synchronous ORM belongs,
and `tool_call` closes the connection that thread borrowed.
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
    downloadable_export,
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
from apps.exports.selectors import get_export, list_exports
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
            # Scoped first and only narrowed after — the type widens from
            # `ScopedQuerySet` to `QuerySet` for the same reason it does in
            # `api.py`: filtering returns the plain one, and narrowing a
            # queryset cannot widen its tenant.
            exports: QuerySet[Export] = ExportFilter(status=status).filter(
                list_exports(tenant=acting.tenant, org=acting.org, actor=acting.actor())
            )
            exports = ordered_by(exports, ordering, allowed=ORDERING, default="-created_at")
            page = cursor_page(
                exports,
                tenant=acting.tenant,
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
            # An export in another tenant, or in a branch this hat cannot see,
            # is `not_found` exactly as it is over HTTP: a refusal that
            # distinguished the two would tell the caller the row exists.
            return ExportOut.from_orm(
                get_export(
                    tenant=acting.tenant,
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
            # The same gate the HTTP route goes through, imported rather than
            # restated, so the three refusals cannot come apart: no such row, no
            # permission, no archive behind it.
            return ExportDownloadOut.from_orm(
                downloadable_export(
                    tenant=acting_tenant(acting),
                    actor=acting.actor(),
                    export_id=export_id,
                )
            )
