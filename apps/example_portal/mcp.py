"""The machine door onto portal requests: the REST door's three capabilities, one service.

The surface is the mount's: an unexposed family answers `surface_does_not_expose` before the body.
"""

from __future__ import annotations

# golden: portal begin
from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.example.selectors import get_widget
from apps.example_portal.api import (
    list_portal_requests_route,
    retrieve_portal_request,
    submit_portal_request_route,
)
from apps.example_portal.schemas import (
    PortalRequestFilter,
    PortalRequestOut,
    PortalRequestPage,
    Priority,
)
from apps.example_portal.selectors import get_portal_request, list_portal_requests
from apps.example_portal.services import submit_portal_request
from pilecap.api import contract_of, cursor_page
from pilecap.mcp import acting_tenant, tool_call


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(name="list_portal_requests", description=contract_of(list_portal_requests_route))
    def list_portal_requests_tool(
        ctx: Context[Any],
        widget_id: UUID | None = None,
        priority: Priority | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> PortalRequestPage:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            filters = PortalRequestFilter(widget_id=widget_id, priority=priority)
            rows = list_portal_requests(tenant=tenant, actor=acting.actor(), filters=filters)
            page = cursor_page(
                rows,
                tenant=tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return PortalRequestPage(
                items=[PortalRequestOut.model_validate(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="get_portal_request", description=contract_of(retrieve_portal_request))
    def get_portal_request_tool(ctx: Context[Any], request_id: UUID) -> PortalRequestOut:
        with tool_call(ctx) as acting:
            return PortalRequestOut.model_validate(
                get_portal_request(
                    tenant=acting_tenant(acting), actor=acting.actor(), request_id=request_id
                )
            )

    @server.tool(name="submit_portal_request", description=contract_of(submit_portal_request_route))
    def submit_portal_request_tool(
        ctx: Context[Any],
        widget_id: UUID,
        note: str,
        priority: Priority | None = None,
    ) -> PortalRequestOut:
        with tool_call(ctx) as acting:
            tenant, actor = acting_tenant(acting), acting.actor()
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=actor.org, actor=actor)
            return PortalRequestOut.model_validate(
                submit_portal_request(
                    tenant=tenant, actor=actor, widget=widget, note=note, priority=priority
                )
            )


# golden: portal end
