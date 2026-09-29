# collides: archive_widget — the self-case replays the example's fenced names on purpose
# collides: restore_widget — the self-case replays the example's fenced names on purpose
# collides: list_widgets — the self-case replays the example's fenced names on purpose
# collides: get_widget — the self-case replays the example's fenced names on purpose
"""The self-case's machine-door block: the four twins, over the same services."""

# golden: archive begin
from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api.docs import contract_of
from apps.core.api.pagination import cursor_page
from apps.core.mcp import acting_tenant, tool_call
from apps.example.api import (
    archive_widget_route,
    list_widgets_route,
    restore_widget_route,
    retrieve_widget,
)
from apps.example.schemas import WidgetOut, WidgetPage
from apps.example.selectors import Show, get_widget, list_widgets
from apps.example.services import archive_widget, restore_widget


def register(server: MCPServer[Any]) -> None:
    """Contribute the twins. `config.mcp` discovers and calls this."""

    @server.tool(name="list_widgets", description=contract_of(list_widgets_route))
    def list_widgets_tool(
        ctx: Context[Any], show: Show = "live", cursor: str | None = None, limit: int | None = None
    ) -> WidgetPage:
        with tool_call(ctx) as acting:
            rows = list_widgets(
                tenant=acting.tenant, org=acting.org, actor=acting.actor(), show=show
            )
            page = cursor_page(rows, tenant=acting.tenant, cursor=cursor, limit=limit)
            return WidgetPage(
                items=[WidgetOut.from_orm(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="get_widget", description=contract_of(retrieve_widget))
    def get_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            return WidgetOut.from_orm(
                get_widget(
                    tenant=acting.tenant, widget_id=widget_id, org=acting.org, actor=acting.actor()
                )
            )

    @server.tool(name="archive_widget", description=contract_of(archive_widget_route))
    def archive_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            widget = get_widget(
                tenant=tenant, widget_id=widget_id, org=acting.org, actor=acting.actor()
            )
            return WidgetOut.from_orm(
                archive_widget(tenant=tenant, actor=acting.actor(), widget=widget)
            )

    @server.tool(name="restore_widget", description=contract_of(restore_widget_route))
    def restore_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            widget = get_widget(
                tenant=tenant, widget_id=widget_id, org=acting.org, actor=acting.actor()
            )
            return WidgetOut.from_orm(
                restore_widget(tenant=tenant, actor=acting.actor(), widget=widget)
            )


# golden: archive end
