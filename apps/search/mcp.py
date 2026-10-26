"""The machine door onto search: the REST door's two capabilities, same selector and schemas."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api.docs import contract_of
from apps.core.api.pagination import cursor_page
from apps.core.mcp import acting_tenant, tool_call
from apps.search.api import kind_catalogue, list_search_kinds_route, search_route
from apps.search.schemas import SearchKindPage, SearchPage
from apps.search.selectors import get_search_page


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(
        name="search_query",
        description=contract_of(search_route),
    )
    def search_query_tool(
        ctx: Context[Any],
        q: str = "",
        kinds: str = "",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> SearchPage:
        with tool_call(ctx) as acting:
            requested = tuple(part.strip() for part in kinds.split(",") if part.strip())
            return get_search_page(
                tenant=acting_tenant(acting),
                actor=acting.actor(),
                q=q,
                kinds=requested or None,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )

    @server.tool(
        name="list_search_kinds",
        description=contract_of(list_search_kinds_route),
    )
    def list_search_kinds_tool(
        ctx: Context[Any],
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> SearchKindPage:
        """The vocabulary `kinds` speaks — the route's own catalogue, never a second derivation."""
        with tool_call(ctx) as acting:
            page = cursor_page(
                kind_catalogue(),
                tenant=acting_tenant(acting),
                cursor=cursor,
                limit=limit,
                include_count=include_count,
                ordering=("kind",),
            )
            return SearchKindPage(
                items=list(page.items),
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )
