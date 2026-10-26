"""The machine door: every REST capability, through its one capability function."""

from __future__ import annotations

# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.example.api import (
    archive_widget_route,
    list_widgets_route,
    restore_widget_route,
    retrieve_widget,
    widget_archive,
    widget_detail,
    widget_list,
    widget_restore,
)
from apps.example.schemas import WidgetDetailOut, WidgetFilter, WidgetOut, WidgetPage
from pilecap import Show
from pilecap.api import contract_of, cursor_page
from pilecap.mcp import acting_tenant, tool_call

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: version move bulk history duplicate attach merge import begin
from apps.example.api import (
    list_widget_history_route,
    update_widget_route,
    widget_history_list,
    widget_update,
)
from pilecap import HistoryPage

# golden: noun end

# golden: version move bulk history duplicate attach merge import end
# isort: split
# golden: move bulk history duplicate attach merge import begin
from apps.example.api import move_widget_route, widget_move

# golden: move bulk history duplicate attach merge import end
# isort: split
# golden: bulk history duplicate attach merge import begin
from typing import Literal

from apps.example.api import bulk_widgets, bulk_widgets_route
from apps.example.schemas import WidgetBulkOut

# golden: bulk history duplicate attach merge import end
# isort: split
# golden: duplicate attach merge import begin
from apps.example.api import duplicate_widget_route, widget_duplicate

# golden: duplicate attach merge import end
# isort: split
# golden: merge import begin
from apps.example.api import (
    merge_widget_route,
    preview_widget_merge_route,
    widget_merge,
    widget_merge_detail,
)
from apps.example.schemas import WidgetMergePreviewOut

# golden: merge import end
# isort: split
# golden: import begin
# golden: noun begin
from apps.example.api import create_widget_route, widget_create

# golden: import end
# isort: split
from pydantic import AwareDatetime

# golden: noun end
# golden: noun begin
from apps.example.api import delete_widget_route, widget_delete

# golden: noun end
# isort: split
# golden: workflow onboard begin
from apps.example.api import approve_widget_route, widget_approve

# golden: workflow onboard end
# isort: split
# golden: child entry begin
from apps.example.api import (
    list_widget_entries_route,
    record_widget_entry_route,
    widget_entries_list,
    widget_entry_record,
)
from apps.example.schemas import WidgetEntryOut, WidgetEntryPage

# golden: child entry end
# isort: split
# golden: policy begin
from apps.example.api import (
    archive_widget_policy_route,
    create_widget_policy_route,
    get_governing_widget_policy_route,
    governing_widget_policy_detail,
    list_widget_policies_route,
    restore_widget_policy_route,
    widget_policies_list,
    widget_policy_archive,
    widget_policy_create,
    widget_policy_restore,
)
from apps.example.schemas import WidgetPolicyOut, WidgetPolicyPage

# golden: policy end

# isort: split
# golden: verb touch begin
from apps.example.api import touch_widget_route, widget_touch

# golden: verb touch end
# isort: split
# golden: enum status begin
from apps.example.api import transition_widget_route, widget_transition

# golden: enum status end
# isort: split
# golden: stat count begin
from apps.example.api import widget_stats, widget_stats_route
from apps.example.schemas import WidgetStatsOut

# golden: stat count end


# golden: archive version move bulk history duplicate attach merge import begin
# golden: noun begin
def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(name="list_widgets", description=contract_of(list_widgets_route))
    def list_widgets_tool(
        ctx: Context[Any],
        # golden: filter name begin
        name: str | None = None,
        # golden: filter name end
        q: str | None = None,
        ordering: str = "-created_at",
        show: Show = "live",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
        # golden: noun end
        # golden: archive version move bulk history duplicate attach merge import end
        # golden: policy begin
        policy: UUID | None = None,
        # golden: policy end
        # golden: noun begin
        due_before: AwareDatetime | None = None,
        due_after: AwareDatetime | None = None,
        # golden: archive version move bulk history duplicate attach merge import begin
    ) -> WidgetPage:
        with tool_call(ctx) as acting:
            tenant, actor = acting_tenant(acting), acting.actor()
            filters = WidgetFilter()
            # golden: filter name begin
            filters.name = name
            # golden: filter name end
            # golden: noun end
            # golden: archive version move bulk history duplicate attach merge import end
            # golden: policy begin
            filters.policy = policy
            # golden: policy end
            # golden: noun begin
            filters.due_before = due_before
            filters.due_after = due_after
            # golden: archive version move bulk history duplicate attach merge import begin
            widgets = widget_list(
                tenant=tenant, actor=actor, filters=filters, q=q, ordering=ordering, show=show
            )
            # `actor=` puts every row's acts and the page's own on, as `ActsPagination` does.
            page = cursor_page(
                widgets,
                tenant=tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
                actor=actor,
            )
            return WidgetPage(
                items=[WidgetOut.from_orm(widget) for widget in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
                allowed_acts=list(page.allowed_acts or ()),
            )

    @server.tool(name="get_widget", description=contract_of(retrieve_widget))
    def get_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetDetailOut:
        with tool_call(ctx) as acting:
            return widget_detail(
                tenant=acting_tenant(acting), actor=acting.actor(), widget_id=widget_id
            )

    # golden: archive version move bulk history duplicate attach merge end
    @server.tool(name="create_widget", description=contract_of(create_widget_route))
    def create_widget_tool(
        ctx: Context[Any],
        name: str,
        notes: str = "",
        # golden: noun end
        external_ref: str = "",
        # golden: import end
        # golden: policy begin
        policy_id: UUID | None = None,
        # golden: policy end
        # golden: noun begin
        # golden: field due_at begin
        due_at: AwareDatetime | None = None,
        # golden: field due_at end
        # golden: import begin
    ) -> WidgetOut:
        with tool_call(ctx) as acting:
            return widget_create(
                tenant=acting_tenant(acting),
                actor=acting.actor(),
                name=name,
                notes=notes,
                # golden: noun end
                external_ref=external_ref,
                # golden: import end
                # golden: policy begin
                policy_id=policy_id,
                # golden: policy end
                # golden: noun begin
                # golden: field due_at begin
                due_at=due_at,
                # golden: field due_at end
                # golden: import begin
            )

    # golden: import end

    # golden: version move bulk history duplicate attach merge import begin
    @server.tool(name="update_widget", description=contract_of(update_widget_route))
    def update_widget_tool(
        ctx: Context[Any],
        widget_id: UUID,
        version: int,
        name: str | None = None,
        notes: str | None = None,
        # golden: noun end
        # golden: version move bulk history duplicate attach merge import end
        # golden: policy begin
        policy_id: UUID | None = None,
        # golden: policy end
        # golden: noun begin
        # golden: field due_at begin
        due_at: AwareDatetime | None = None,
        clear_due_at: bool | None = None,
        # golden: field due_at end
        # golden: version move bulk history duplicate attach merge import begin
    ) -> WidgetOut:
        with tool_call(ctx) as acting:
            return widget_update(
                tenant=acting_tenant(acting),
                actor=acting.actor(),
                widget_id=widget_id,
                version=version,
                name=name,
                notes=notes,
                # golden: noun end
                # golden: version move bulk history duplicate attach merge import end
                # golden: policy begin
                policy_id=policy_id,
                # golden: policy end
                # golden: noun begin
                # golden: field due_at begin
                due_at=due_at,
                clear_due_at=bool(clear_due_at),
                # golden: field due_at end
                # golden: version move bulk history duplicate attach merge import begin
            )

    @server.tool(name="list_widget_history", description=contract_of(list_widget_history_route))
    def list_widget_history_tool(
        ctx: Context[Any],
        widget_id: UUID,
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> HistoryPage:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            page = cursor_page(
                widget_history_list(tenant=tenant, actor=acting.actor(), widget_id=widget_id),
                tenant=tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return HistoryPage.model_validate(
                {
                    "items": list(page.items),
                    "has_more": page.has_more,
                    "next_cursor": page.next_cursor,
                    "count": page.count,
                }
            )
            # golden: noun end

    # golden: version end
    @server.tool(name="move_widget", description=contract_of(move_widget_route))
    def move_widget_tool(
        ctx: Context[Any],
        widget_id: UUID,
        version: int,
        organization_id: UUID | None = None,
        owner_id: UUID | None = None,
    ) -> WidgetOut:
        with tool_call(ctx) as acting:
            return widget_move(
                tenant=acting_tenant(acting),
                actor=acting.actor(),
                widget_id=widget_id,
                version=version,
                organization_id=organization_id,
                owner_id=owner_id,
            )

    # golden: move end
    @server.tool(name="bulk_widgets", description=contract_of(bulk_widgets_route))
    def bulk_widgets_tool(
        ctx: Context[Any],
        verb: Literal["archive", "restore", "move"],
        ids: list[UUID],
        organization_id: UUID | None = None,
        owner_id: UUID | None = None,
    ) -> WidgetBulkOut:
        with tool_call(ctx) as acting:
            return bulk_widgets(
                tenant=acting_tenant(acting),
                actor=acting.actor(),
                verb=verb,
                ids=ids,
                organization_id=organization_id,
                owner_id=owner_id,
            )

    # golden: bulk history end
    @server.tool(name="duplicate_widget", description=contract_of(duplicate_widget_route))
    def duplicate_widget_tool(
        ctx: Context[Any], widget_id: UUID, idempotency_key: str = ""
    ) -> WidgetOut:
        # The key rides as an argument here and as the `Idempotency-Key` header over HTTP.
        with tool_call(ctx) as acting:
            return widget_duplicate(
                tenant=acting_tenant(acting),
                actor=acting.actor(),
                widget_id=widget_id,
                idempotency_key=idempotency_key,
            )

    # golden: duplicate attach end
    @server.tool(name="get_widget_merge", description=contract_of(preview_widget_merge_route))
    def get_widget_merge_tool(
        ctx: Context[Any], widget_id: UUID, into: UUID
    ) -> WidgetMergePreviewOut:
        with tool_call(ctx) as acting:
            return widget_merge_detail(
                tenant=acting_tenant(acting), actor=acting.actor(), widget_id=widget_id, into=into
            )

    @server.tool(name="merge_widget", description=contract_of(merge_widget_route))
    def merge_widget_tool(
        ctx: Context[Any], widget_id: UUID, into_id: UUID, version: int, into_version: int
    ) -> WidgetOut:
        with tool_call(ctx) as acting:
            return widget_merge(
                tenant=acting_tenant(acting),
                actor=acting.actor(),
                widget_id=widget_id,
                into_id=into_id,
                version=version,
                into_version=into_version,
            )

    # golden: merge import end
    # golden: workflow onboard begin
    @server.tool(name="approve_widget", description=contract_of(approve_widget_route))
    def approve_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            return widget_approve(
                tenant=acting_tenant(acting), actor=acting.actor(), widget_id=widget_id
            )

    # golden: workflow onboard end
    # golden: noun begin
    @server.tool(name="delete_widget", description=contract_of(delete_widget_route))
    def delete_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        # HTTP answers 204; a tool result has no "gone", so it answers the row that went.
        with tool_call(ctx) as acting:
            return widget_delete(
                tenant=acting_tenant(acting), actor=acting.actor(), widget_id=widget_id
            )

    # golden: noun end

    # golden: stat count begin
    @server.tool(name="get_widget_stats", description=contract_of(widget_stats_route))
    def get_widget_stats_tool(ctx: Context[Any]) -> WidgetStatsOut:
        with tool_call(ctx) as acting:
            return widget_stats(tenant=acting_tenant(acting), actor=acting.actor())

    # golden: stat count end

    # golden: policy begin
    @server.tool(name="list_widget_policies", description=contract_of(list_widget_policies_route))
    def list_widget_policies_tool(
        ctx: Context[Any],
        show: Show = "live",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> WidgetPolicyPage:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            page = cursor_page(
                widget_policies_list(tenant=tenant, actor=acting.actor(), show=show),
                tenant=tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return WidgetPolicyPage(
                items=[WidgetPolicyOut.from_orm(policy) for policy in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="get_governing_widget_policy",
        description=contract_of(get_governing_widget_policy_route),
    )
    def get_governing_widget_policy_tool(ctx: Context[Any]) -> WidgetPolicyOut:
        with tool_call(ctx) as acting:
            return governing_widget_policy_detail(
                tenant=acting_tenant(acting), actor=acting.actor()
            )

    @server.tool(name="create_widget_policy", description=contract_of(create_widget_policy_route))
    def create_widget_policy_tool(ctx: Context[Any], name: str, body: str = "") -> WidgetPolicyOut:
        with tool_call(ctx) as acting:
            return widget_policy_create(
                tenant=acting_tenant(acting), actor=acting.actor(), name=name, body=body
            )

    # golden: policy end
    # golden: child entry begin
    @server.tool(name="list_widget_entries", description=contract_of(list_widget_entries_route))
    def list_widget_entries_tool(
        ctx: Context[Any],
        widget_id: UUID | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> WidgetEntryPage:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            page = cursor_page(
                widget_entries_list(tenant=tenant, actor=acting.actor(), widget_id=widget_id),
                tenant=tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return WidgetEntryPage(
                items=[WidgetEntryOut.from_orm(entry) for entry in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="record_widget_entry", description=contract_of(record_widget_entry_route))
    def record_widget_entry_tool(
        ctx: Context[Any],
        widget_id: UUID,
        kind: str = "note",
        note: str = "",
        organization_slug: str | None = None,
    ) -> WidgetEntryOut:
        with tool_call(ctx) as acting:
            return widget_entry_record(
                tenant=acting_tenant(acting),
                actor=acting.actor(),
                widget_id=widget_id,
                kind=kind,
                note=note,
                organization_slug=organization_slug,
            )

    # golden: child entry end
    # golden: policy begin
    @server.tool(name="archive_widget_policy", description=contract_of(archive_widget_policy_route))
    def archive_widget_policy_tool(ctx: Context[Any], policy_id: UUID) -> WidgetPolicyOut:
        with tool_call(ctx) as acting:
            return widget_policy_archive(
                tenant=acting_tenant(acting), actor=acting.actor(), policy_id=policy_id
            )

    @server.tool(name="restore_widget_policy", description=contract_of(restore_widget_policy_route))
    def restore_widget_policy_tool(ctx: Context[Any], policy_id: UUID) -> WidgetPolicyOut:
        with tool_call(ctx) as acting:
            return widget_policy_restore(
                tenant=acting_tenant(acting), actor=acting.actor(), policy_id=policy_id
            )

    # golden: policy end
    # golden: verb touch begin
    @server.tool(name="touch_widget", description=contract_of(touch_widget_route))
    def touch_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            return widget_touch(
                tenant=acting_tenant(acting), actor=acting.actor(), widget_id=widget_id
            )

    # golden: verb touch end
    # golden: enum status begin
    @server.tool(name="transition_widget", description=contract_of(transition_widget_route))
    def transition_widget_tool(ctx: Context[Any], widget_id: UUID, status: str) -> WidgetOut:
        with tool_call(ctx) as acting:
            return widget_transition(
                tenant=acting_tenant(acting),
                actor=acting.actor(),
                widget_id=widget_id,
                status=status,
            )

    # golden: enum status end
    # golden: archive version move bulk history duplicate attach merge import begin
    # golden: noun begin
    @server.tool(name="archive_widget", description=contract_of(archive_widget_route))
    def archive_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            return widget_archive(
                tenant=acting_tenant(acting), actor=acting.actor(), widget_id=widget_id
            )

    @server.tool(name="restore_widget", description=contract_of(restore_widget_route))
    def restore_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            return widget_restore(
                tenant=acting_tenant(acting), actor=acting.actor(), widget_id=widget_id
            )

    # golden: noun end


# golden: archive version move bulk history duplicate attach merge import end
