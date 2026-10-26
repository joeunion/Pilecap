"""The machine door onto notes — each tool calls the selector and service its REST twin calls."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api.docs import contract_of
from apps.core.api.pagination import cursor_page
from apps.core.mcp import acting_tenant, tool_call
from apps.core.schemas import Show
from apps.djb_notes.api import (
    archive_note_route,
    create_note_route,
    list_notes_route,
    restore_note_route,
    retrieve_note,
    update_note_route,
)
from apps.djb_notes.schemas import DjbNoteOut, DjbNotePage
from apps.djb_notes.selectors import get_note, list_notes
from apps.djb_notes.services import archive_note, create_note, restore_note, update_note


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(name="list_djb_notes", description=contract_of(list_notes_route))
    def list_notes_tool(
        ctx: Context[Any],
        subject: str,
        show: Show = "live",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> DjbNotePage:
        with tool_call(ctx) as acting:
            notes = list_notes(
                tenant=acting_tenant(acting), actor=acting.actor(), subject=subject, show=show
            )
            page = cursor_page(
                notes,
                tenant=acting_tenant(acting),
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return DjbNotePage(
                items=[DjbNoteOut.model_validate(note) for note in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="get_djb_note", description=contract_of(retrieve_note))
    def get_note_tool(ctx: Context[Any], note_id: UUID) -> DjbNoteOut:
        with tool_call(ctx) as acting:
            return DjbNoteOut.model_validate(
                get_note(tenant=acting_tenant(acting), actor=acting.actor(), note_id=note_id)
            )

    @server.tool(name="create_djb_note", description=contract_of(create_note_route))
    def create_note_tool(ctx: Context[Any], subject: str, body: str) -> DjbNoteOut:
        with tool_call(ctx) as acting:
            note = create_note(
                tenant=acting_tenant(acting), actor=acting.actor(), subject=subject, body=body
            )
            return DjbNoteOut.model_validate(note)

    @server.tool(name="update_djb_note", description=contract_of(update_note_route))
    def update_note_tool(ctx: Context[Any], note_id: UUID, body: str | None = None) -> DjbNoteOut:
        with tool_call(ctx) as acting:
            tenant, actor = acting_tenant(acting), acting.actor()
            note = get_note(tenant=tenant, actor=actor, note_id=note_id)
            return DjbNoteOut.model_validate(
                update_note(tenant=tenant, actor=actor, note=note, body=body)
            )

    @server.tool(name="archive_djb_note", description=contract_of(archive_note_route))
    def archive_note_tool(ctx: Context[Any], note_id: UUID) -> DjbNoteOut:
        with tool_call(ctx) as acting:
            tenant, actor = acting_tenant(acting), acting.actor()
            note = get_note(tenant=tenant, actor=actor, note_id=note_id)
            return DjbNoteOut.model_validate(archive_note(tenant=tenant, actor=actor, note=note))

    @server.tool(name="restore_djb_note", description=contract_of(restore_note_route))
    def restore_note_tool(ctx: Context[Any], note_id: UUID) -> DjbNoteOut:
        with tool_call(ctx) as acting:
            tenant, actor = acting_tenant(acting), acting.actor()
            note = get_note(tenant=tenant, actor=actor, note_id=note_id)
            return DjbNoteOut.model_validate(restore_note(tenant=tenant, actor=actor, note=note))
