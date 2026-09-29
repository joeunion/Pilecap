"""The machine door onto tags — the same selectors and services as the REST door.

Every tool is the twin of one route (house rule 17), described by that route's
own contract (`contract_of`), and answers the same schema, so a subject's tags
read the same over JSON-RPC as over HTTP. The principal comes from the bearer
token at the edge (`core.mcp.tool_call`); no tool sees a token.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api.docs import contract_of
from apps.core.api.pagination import cursor_page
from apps.core.mcp import acting_tenant, tool_call
from apps.tags.api import (
    archive_tag_route,
    create_tag_link_route,
    create_tag_route,
    delete_tag_link_route,
    list_tag_links_route,
    list_tags_route,
    rename_tag_route,
    restore_tag_route,
    retrieve_tag,
)
from apps.tags.schemas import TagLinkOut, TagLinkPage, TagOut, TagPage
from apps.tags.selectors import get_tag, get_tag_link, list_tag_links, list_tags
from apps.tags.services import (
    archive_tag,
    create_tag,
    create_tag_link,
    delete_tag_link,
    rename_tag,
    restore_tag,
)


def register(server: MCPServer[Any]) -> None:
    """Mount the tag tools on the one MCP server. Discovered by `config/mcp.py`."""

    @server.tool(name="list_tags", description=contract_of(list_tags_route))
    def list_tags_tool(
        ctx: Context[Any],
        show: Literal["live", "archived", "all"] = "live",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> TagPage:
        with tool_call(ctx) as acting:
            page = cursor_page(
                list_tags(tenant=acting.tenant, actor=acting.actor(), show=show),
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return TagPage(
                items=[TagOut.from_orm(tag) for tag in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="create_tag", description=contract_of(create_tag_route))
    def create_tag_tool(ctx: Context[Any], name: str) -> TagOut:
        with tool_call(ctx) as acting:
            return TagOut.from_orm(
                create_tag(tenant=acting_tenant(acting), actor=acting.actor(), name=name)
            )

    @server.tool(name="get_tag", description=contract_of(retrieve_tag))
    def get_tag_tool(ctx: Context[Any], tag_id: UUID) -> TagOut:
        with tool_call(ctx) as acting:
            return TagOut.from_orm(
                get_tag(tenant=acting.tenant, actor=acting.actor(), tag_id=tag_id)
            )

    @server.tool(name="rename_tag", description=contract_of(rename_tag_route))
    def rename_tag_tool(ctx: Context[Any], tag_id: UUID, name: str) -> TagOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
            return TagOut.from_orm(rename_tag(tenant=tenant, actor=actor, tag=tag, name=name))

    @server.tool(name="archive_tag", description=contract_of(archive_tag_route))
    def archive_tag_tool(ctx: Context[Any], tag_id: UUID) -> TagOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
            return TagOut.from_orm(archive_tag(tenant=tenant, actor=actor, tag=tag))

    @server.tool(name="restore_tag", description=contract_of(restore_tag_route))
    def restore_tag_tool(ctx: Context[Any], tag_id: UUID) -> TagOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
            return TagOut.from_orm(restore_tag(tenant=tenant, actor=actor, tag=tag))

    @server.tool(name="list_tag_links", description=contract_of(list_tag_links_route))
    def list_tag_links_tool(
        ctx: Context[Any],
        subject: str,
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> TagLinkPage:
        with tool_call(ctx) as acting:
            page = cursor_page(
                list_tag_links(tenant=acting.tenant, actor=acting.actor(), subject=subject),
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return TagLinkPage(
                items=[TagLinkOut.from_orm(link) for link in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="create_tag_link", description=contract_of(create_tag_link_route))
    def create_tag_link_tool(ctx: Context[Any], tag_id: UUID, subject: str) -> TagLinkOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
            linking = create_tag_link(tenant=tenant, actor=actor, tag=tag, subject=subject)
            return TagLinkOut.from_orm(linking.link)

    @server.tool(name="delete_tag_link", description=contract_of(delete_tag_link_route))
    def delete_tag_link_tool(ctx: Context[Any], link_id: UUID) -> TagLinkOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            link = get_tag_link(tenant=tenant, actor=actor, link_id=link_id)
            return TagLinkOut.from_orm(delete_tag_link(tenant=tenant, actor=actor, link=link))
