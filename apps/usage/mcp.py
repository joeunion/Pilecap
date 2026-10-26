"""The machine door onto usage: the report and the vocabulary, over the REST door's own builders.

# why-not a write tool: an agent that could record usage could mint or dispute its own bill.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api.docs import contract_of
from apps.core.mcp import acting_tenant, tool_call
from apps.usage.api import list_meters_route, meter_page, report, usage_report_route
from apps.usage.schemas import MeterPage, UsageReportOut
from apps.usage.types import PeriodKind


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(
        name="get_usage",
        description=contract_of(usage_report_route),
    )
    def get_usage_tool(
        ctx: Context[Any],
        period: PeriodKind = PeriodKind.MONTH,
        on: date | None = None,
        meters: list[str] | None = None,
    ) -> UsageReportOut:
        with tool_call(ctx) as acting:
            return report(
                tenant=acting_tenant(acting),
                actor=acting.actor(),
                period=period,
                on=on,
                meters=meters,
            )

    @server.tool(
        name="list_meters",
        description=contract_of(list_meters_route),
    )
    def list_meters_tool(
        ctx: Context[Any],
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> MeterPage:
        with tool_call(ctx) as acting:
            return meter_page(
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
