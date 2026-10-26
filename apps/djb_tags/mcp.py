"""The machine door onto tags — each tool calls the selector and service its REST twin calls."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api.docs import contract_of
from apps.core.api.pagination import cursor_page
from apps.core.mcp import acting_tenant, tool_call
from apps.core.schemas import Show
from apps.djb_tags.api import (
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
from apps.djb_tags.schemas import DjbTagLinkOut, DjbTagLinkPage, DjbTagOut, DjbTagPage
from apps.djb_tags.selectors import get_tag, get_tag_link, list_tag_links, list_tags
from apps.djb_tags.services import (
    archive_tag,
    create_tag,
    create_tag_link,
    delete_tag_link,
    rename_tag,
    restore_tag,
)


def register(server: MCPServer[Any]) -> None:
    """Mount the tag tools on the one MCP server. Discovered by `config/mcp.py`."""

    @server.tool(name="list_djb_tags", description=contract_of(list_tags_route))
    def list_tags_tool(
        ctx: Context[Any],
        show: Show = "live",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> DjbTagPage:
        with tool_call(ctx) as acting:
            page = cursor_page(
                list_tags(tenant=acting_tenant(acting), actor=acting.actor(), show=show),
                tenant=acting_tenant(acting),
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return DjbTagPage(
                items=[DjbTagOut.from_orm(tag) for tag in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="create_djb_tag", description=contract_of(create_tag_route))
    def create_tag_tool(ctx: Context[Any], name: str) -> DjbTagOut:
        with tool_call(ctx) as acting:
            return DjbTagOut.from_orm(
                create_tag(tenant=acting_tenant(acting), actor=acting.actor(), name=name)
            )

    @server.tool(name="get_djb_tag", description=contract_of(retrieve_tag))
    def get_tag_tool(ctx: Context[Any], tag_id: UUID) -> DjbTagOut:
        with tool_call(ctx) as acting:
            return DjbTagOut.from_orm(
                get_tag(tenant=acting_tenant(acting), actor=acting.actor(), tag_id=tag_id)
            )

    @server.tool(name="rename_djb_tag", description=contract_of(rename_tag_route))
    def rename_tag_tool(ctx: Context[Any], tag_id: UUID, name: str) -> DjbTagOut:
        with tool_call(ctx) as acting:
            tenant, actor = acting_tenant(acting), acting.actor()
            tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
            return DjbTagOut.from_orm(rename_tag(tenant=tenant, actor=actor, tag=tag, name=name))

    @server.tool(name="archive_djb_tag", description=contract_of(archive_tag_route))
    def archive_tag_tool(ctx: Context[Any], tag_id: UUID) -> DjbTagOut:
        with tool_call(ctx) as acting:
            tenant, actor = acting_tenant(acting), acting.actor()
            tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
            return DjbTagOut.from_orm(archive_tag(tenant=tenant, actor=actor, tag=tag))

    @server.tool(name="restore_djb_tag", description=contract_of(restore_tag_route))
    def restore_tag_tool(ctx: Context[Any], tag_id: UUID) -> DjbTagOut:
        with tool_call(ctx) as acting:
            tenant, actor = acting_tenant(acting), acting.actor()
            tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
            return DjbTagOut.from_orm(restore_tag(tenant=tenant, actor=actor, tag=tag))

    @server.tool(name="list_djb_tag_links", description=contract_of(list_tag_links_route))
    def list_tag_links_tool(
        ctx: Context[Any],
        subject: str,
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> DjbTagLinkPage:
        with tool_call(ctx) as acting:
            page = cursor_page(
                list_tag_links(tenant=acting_tenant(acting), actor=acting.actor(), subject=subject),
                tenant=acting_tenant(acting),
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return DjbTagLinkPage(
                items=[DjbTagLinkOut.from_orm(link) for link in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="create_djb_tag_link", description=contract_of(create_tag_link_route))
    def create_tag_link_tool(ctx: Context[Any], tag_id: UUID, subject: str) -> DjbTagLinkOut:
        with tool_call(ctx) as acting:
            tenant, actor = acting_tenant(acting), acting.actor()
            tag = get_tag(tenant=tenant, actor=actor, tag_id=tag_id)
            linking = create_tag_link(tenant=tenant, actor=actor, tag=tag, subject=subject)
            return DjbTagLinkOut.from_orm(linking.link)

    @server.tool(name="delete_djb_tag_link", description=contract_of(delete_tag_link_route))
    def delete_tag_link_tool(ctx: Context[Any], link_id: UUID) -> DjbTagLinkOut:
        with tool_call(ctx) as acting:
            tenant, actor = acting_tenant(acting), acting.actor()
            link = get_tag_link(tenant=tenant, actor=actor, link_id=link_id)
            return DjbTagLinkOut.from_orm(delete_tag_link(tenant=tenant, actor=actor, link=link))
