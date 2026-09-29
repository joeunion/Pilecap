"""The machine door onto widgets — every capability the REST door has.

**Door parity is the rule this file exists to demonstrate** (house rule 17):
every capability `api.py` offers a person, `mcp.py` offers a machine, over the
*same* selectors, the *same* services and the *same* schemas. A tool that could
do something no route can, or that answered with a different shape for the same
row, is a finding — and `tests/test_mcp.py` diffs the two registries out of
`introspect` so that it is a failing one.

**And it says what the REST door says, out of one docstring** (ADR api-1, house
rule 41). Every `description=` below is `contract_of(<the REST route>)` — the
contract half of the very function the OpenAPI document describes — so the two
doors cannot come to describe one capability differently. A description typed
here would be the first place they drift, and prose drifts long before
behaviour does.

What a tool is allowed to be is thin:

* it takes **who is calling** from the principal the token middleware left on
  the ASGI scope — never from an argument, so no caller can name a tenant, an
  organization or a user it does not hold a token for. The hat comes from the
  same `X-Org` header the HTTP door reads, resolved by the same function, which
  is what makes the two doors agree on the same rows for the same hat;
* it **calls services and selectors**, never `.objects`, never `.save()`;
* it **maps no refusals of its own**: `tool_call` turns a domain exception into
  a `ToolError` once, the way `config/api.py` turns one into a status code once.

The bodies are plain `def` rather than `async def`: the transport runs a
synchronous tool on a worker thread, which is where the synchronous ORM belongs,
and `tool_call` closes the connection that thread borrowed.
"""

from __future__ import annotations

# golden: archive version move bulk history duplicate attach merge import begin
from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api import ordered_by, searched
from apps.core.api.docs import contract_of
from apps.core.api.pagination import cursor_page
from apps.core.authz import may_be_named
from apps.core.exceptions import NotFound
from apps.core.mcp import acting_tenant, tool_call
from apps.core.verbs import with_allowed_acts
from apps.example.api import (
    ORDERING,
    SEARCH_FIELDS,
    archive_widget_route,
    list_widgets_route,
    restore_widget_route,
    retrieve_widget,
)
from apps.example.models import Widget
from apps.example.schemas import WidgetDetailOut, WidgetFilter, WidgetOut, WidgetPage
from apps.example.selectors import Show, get_widget, list_widgets
from apps.example.services import archive_widget, restore_widget

# golden: archive version move bulk history duplicate attach merge import end
# isort: split
# golden: version move bulk history duplicate attach merge import begin
from apps.core.schemas import HistoryPage
from apps.core.selectors import list_history
from apps.example.api import list_widget_history_route, update_widget_route
from apps.example.services import update_widget

# golden: version move bulk history duplicate attach merge import end
# isort: split
# golden: move bulk history duplicate attach merge import begin
from apps.example.api import move_destination, move_widget_route
from apps.example.services import move_widget

# golden: move bulk history duplicate attach merge import end
# isort: split
# golden: bulk history duplicate attach merge import begin
from typing import Literal

from apps.example.api import bulk_widgets, bulk_widgets_route
from apps.example.schemas import WidgetBulkOut

# golden: bulk history duplicate attach merge import end
# isort: split
# golden: duplicate attach merge import begin
from apps.example.api import duplicate_widget_route
from apps.example.services import duplicate_widget

# golden: duplicate attach merge import end
# isort: split
# golden: merge import begin
from apps.example.api import merge_widget_route, preview_widget_merge_route
from apps.example.schemas import RepointOut, WidgetMergePreviewOut
from apps.example.selectors import get_widget_merge_preview
from apps.example.services import merge_widget

# golden: merge import end
# isort: split
# golden: attach merge import begin
from apps.example.selectors import list_widget_tags

# golden: attach merge import end
# isort: split
# golden: import begin
from apps.example.api import create_widget_route
from apps.example.services import create_widget

# golden: import end
# isort: split
from apps.example.api import (
    approve_widget_route,
    archive_widget_policy_route,
    create_widget_policy_route,
    delete_widget_route,
    get_governing_widget_policy_route,
    list_widget_entries_route,
    list_widget_policies_route,
    record_widget_entry_route,
    resolve_named_policy,
    restore_widget_policy_route,
    widget_stats,
    widget_stats_route,
)
from apps.example.models import WidgetEntry, WidgetPolicy
from apps.example.schemas import (
    WidgetEntryOut,
    WidgetEntryPage,
    WidgetPolicyOut,
    WidgetPolicyPage,
    WidgetStatsOut,
)
from apps.example.selectors import (
    get_governing_widget_policy,
    get_widget_policy,
    list_widget_entries,
    list_widget_policies,
)
from apps.example.services import (
    approve_widget,
    archive_widget_policy,
    create_widget_policy,
    delete_widget,
    record_widget_entry,
    restore_widget_policy,
)


# golden: archive version move bulk history duplicate attach merge import begin
def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(
        name="list_widgets",
        description=contract_of(list_widgets_route),
    )
    def list_widgets_tool(
        ctx: Context[Any],
        name: str | None = None,
        q: str | None = None,
        ordering: str = "-created_at",
        show: Show = "live",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
        # golden: archive version move bulk history duplicate attach merge import end
        policy: UUID | None = None,
        # golden: archive version move bulk history duplicate attach merge import begin
    ) -> WidgetPage:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            filters = WidgetFilter(name=name)
            # golden: archive version move bulk history duplicate attach merge import end
            filters.policy = policy
            # golden: archive version move bulk history duplicate attach merge import begin
            # Scoped first and only narrowed after — and the type widens from
            # `ScopedQuerySet` to `QuerySet` for the same reason it does in
            # `api.py`: filtering returns the plain one, and narrowing a queryset
            # cannot widen its tenant.
            widgets: QuerySet[Widget] = filters.filter(
                list_widgets(tenant=acting.tenant, org=acting.org, actor=actor, show=show)
            )
            widgets = searched(widgets, q, fields=SEARCH_FIELDS)
            widgets = ordered_by(widgets, ordering, allowed=ORDERING, default="-created_at")
            # `actor=` is what makes this the family's page: every row's
            # `allowed_acts` and the list's own, from the seam the REST door's
            # `ActsPagination` calls, so the two doors cannot disagree about
            # who may do what.
            page = cursor_page(
                widgets,
                tenant=acting.tenant,
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

    @server.tool(
        name="get_widget",
        description=contract_of(retrieve_widget),
    )
    def get_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetDetailOut:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            # A widget in another tenant is `not_found`, exactly as it is over
            # HTTP: a refusal that distinguished the two would tell the caller
            # the row exists, which is the fact the tenancy was hiding.
            widget = get_widget(
                tenant=acting.tenant, widget_id=widget_id, org=acting.org, actor=actor
            )
            # golden: archive version move bulk history duplicate end
            widget.tags = list_widget_tags(  # type: ignore[attr-defined]
                tenant=acting.tenant, actor=actor, widget=widget
            )
            # golden: archive version move bulk history duplicate begin
            return WidgetDetailOut.from_orm(with_allowed_acts([widget], actor)[0])

    # golden: archive version move bulk history duplicate attach merge end
    @server.tool(
        name="create_widget",
        description=contract_of(create_widget_route),
    )
    def create_widget_tool(
        ctx: Context[Any],
        name: str,
        notes: str = "",
        external_ref: str = "",
        # golden: import end
        policy_id: UUID | None = None,
        # golden: import begin
    ) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            # golden: import end
            policy = resolve_named_policy(tenant=tenant, actor=actor, policy_id=policy_id)
            # House rule 26, at the site that hands the foreign-key target over —
            # the same two lines the HTTP door writes, for the same reason.
            if policy is not None and not may_be_named(actor, policy):
                raise NotFound()
            # golden: import begin
            return WidgetOut.from_orm(
                with_allowed_acts(
                    [
                        create_widget(
                            tenant=tenant,
                            actor=actor,
                            name=name,
                            notes=notes,
                            external_ref=external_ref,
                            # golden: import end
                            policy=policy,
                            # golden: import begin
                        )
                    ],
                    actor,
                )[0]
            )

    # golden: import end

    # golden: version move bulk history duplicate attach merge import begin
    @server.tool(
        name="update_widget",
        description=contract_of(update_widget_route),
    )
    def update_widget_tool(
        ctx: Context[Any],
        widget_id: UUID,
        version: int,
        name: str | None = None,
        notes: str | None = None,
        # golden: version move bulk history duplicate attach merge import end
        policy_id: UUID | None = None,
        # golden: version move bulk history duplicate attach merge import begin
    ) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org, actor=actor)
            # What was sent and nothing else, exactly as the HTTP door passes it.
            changes: dict[str, Any] = {
                field: value
                for field, value in {"name": name, "notes": notes}.items()
                if value is not None
            }
            # golden: version move bulk history duplicate attach merge import end
            policy = resolve_named_policy(tenant=tenant, actor=actor, policy_id=policy_id)
            if policy is not None and not may_be_named(actor, policy):
                raise NotFound()
            if policy is not None:
                changes["policy"] = policy
            # golden: version move bulk history duplicate attach merge import begin
            updated = update_widget(
                tenant=tenant, actor=actor, widget=widget, version=version, **changes
            )
            return WidgetOut.from_orm(with_allowed_acts([updated], actor)[0])

    @server.tool(
        name="list_widget_history",
        description=contract_of(list_widget_history_route),
    )
    def list_widget_history_tool(
        ctx: Context[Any],
        widget_id: UUID,
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> HistoryPage:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            widget = get_widget(
                tenant=acting.tenant, widget_id=widget_id, org=acting.org, actor=actor
            )
            page = cursor_page(
                list_history(tenant=acting.tenant, actor=actor, row=widget),
                tenant=acting.tenant,
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

    # golden: version end
    @server.tool(
        name="move_widget",
        description=contract_of(move_widget_route),
    )
    def move_widget_tool(
        ctx: Context[Any],
        widget_id: UUID,
        version: int,
        organization_id: UUID | None = None,
        owner_id: UUID | None = None,
    ) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org, actor=actor)
            if not may_be_named(actor, widget):
                raise NotFound()
            moved = move_widget(
                tenant=tenant,
                actor=actor,
                widget=widget,
                organization=move_destination(
                    tenant=tenant, actor=actor, widget=widget, to=organization_id
                ),
                owner_id=owner_id,
                version=version,
            )
            return WidgetOut.from_orm(with_allowed_acts([moved], actor)[0])

    # golden: move end
    @server.tool(
        name="bulk_widgets",
        description=contract_of(bulk_widgets_route),
    )
    def bulk_widgets_tool(
        ctx: Context[Any],
        verb: Literal["archive", "restore", "move"],
        ids: list[UUID],
        organization_id: UUID | None = None,
        owner_id: UUID | None = None,
    ) -> WidgetBulkOut:
        with tool_call(ctx) as acting:
            # The HTTP door's own function: one batch, whichever door it came in by.
            return bulk_widgets(
                tenant=acting_tenant(acting),
                actor=acting.actor(),
                verb=verb,
                ids=ids,
                organization_id=organization_id,
                owner_id=owner_id,
            )

    # golden: bulk history end
    @server.tool(
        name="duplicate_widget",
        description=contract_of(duplicate_widget_route),
    )
    def duplicate_widget_tool(
        ctx: Context[Any], widget_id: UUID, idempotency_key: str = ""
    ) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org, actor=actor)
            if not may_be_named(actor, widget):
                raise NotFound()
            # The key rides as an argument here and as the `Idempotency-Key`
            # header over HTTP — one promise, each protocol's own grammar.
            copy = duplicate_widget(
                tenant=tenant, actor=actor, widget=widget, idempotency_key=idempotency_key
            )
            return WidgetOut.from_orm(with_allowed_acts([copy], actor)[0])

    # golden: duplicate attach end
    @server.tool(
        name="get_widget_merge",
        description=contract_of(preview_widget_merge_route),
    )
    def get_widget_merge_tool(
        ctx: Context[Any], widget_id: UUID, into: UUID
    ) -> WidgetMergePreviewOut:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            widget = get_widget(
                tenant=acting.tenant, widget_id=widget_id, org=acting.org, actor=actor
            )
            survivor = get_widget(tenant=acting.tenant, widget_id=into, org=acting.org, actor=actor)
            return WidgetMergePreviewOut(
                loser_id=widget.pk,
                into_id=survivor.pk,
                repoints=[
                    RepointOut(title=repointed.title, left=repointed.left)
                    for repointed in get_widget_merge_preview(
                        tenant=acting.tenant, actor=actor, widget=widget, into=survivor
                    )
                ],
            )

    @server.tool(
        name="merge_widget",
        description=contract_of(merge_widget_route),
    )
    def merge_widget_tool(
        ctx: Context[Any], widget_id: UUID, into_id: UUID, version: int, into_version: int
    ) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org, actor=actor)
            survivor = get_widget(tenant=tenant, widget_id=into_id, org=acting.org, actor=actor)
            if not may_be_named(actor, widget) or not may_be_named(actor, survivor):
                raise NotFound()
            merged = merge_widget(
                tenant=tenant,
                actor=actor,
                widget=widget,
                into=survivor,
                version=version,
                into_version=into_version,
            )
            return WidgetOut.from_orm(with_allowed_acts([merged], actor)[0])

    # golden: merge import end
    @server.tool(
        name="approve_widget",
        description=contract_of(approve_widget_route),
    )
    def approve_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org, actor=actor)
            # House rule 26: approval writes a ledger line now, so its
            # foreign-key target is checked here, as it is on the HTTP door.
            if not may_be_named(actor, widget):
                raise NotFound()
            # The same service the HTTP route calls, so an agent gets the same
            # refusal for the same reason — `conflict` on a run that has already
            # ended, `not_found` on one that was never there.
            return WidgetOut.from_orm(
                with_allowed_acts(
                    [approve_widget(tenant=tenant, actor=actor, widget=widget)], actor
                )[0]
            )

    @server.tool(
        name="delete_widget",
        description=contract_of(delete_widget_route),
    )
    def delete_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org, actor=actor)
            if not may_be_named(actor, widget):
                raise NotFound()
            # The deleted row comes back rather than a bare acknowledgement: an
            # agent that deleted the wrong widget can say which one it was. The
            # HTTP door answers 204 because HTTP has a way to say "gone"; a tool
            # result does not, so it says what went.
            return WidgetOut.from_orm(
                # No acts: nothing can be pressed on a row that is gone.
                delete_widget(tenant=tenant, actor=actor, widget=widget)
            )

    @server.tool(
        name="get_widget_stats",
        description=contract_of(widget_stats_route),
    )
    def get_widget_stats_tool(ctx: Context[Any]) -> WidgetStatsOut:
        with tool_call(ctx) as acting:
            # The HTTP route's own function, imported rather than reimplemented:
            # a measured number computed twice is two numbers waiting to differ,
            # which is the whole reason `MeasuredOut` exists.
            return widget_stats(tenant=acting.tenant, org=acting.org, actor=acting.actor())

    @server.tool(
        name="list_widget_policies",
        description=contract_of(list_widget_policies_route),
    )
    def list_widget_policies_tool(
        ctx: Context[Any],
        show: Show = "live",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> WidgetPolicyPage:
        with tool_call(ctx) as acting:
            policies: QuerySet[WidgetPolicy] = list_widget_policies(
                tenant=acting.tenant, org=acting.org, actor=acting.actor(), show=show
            )
            page = cursor_page(
                policies,
                tenant=acting.tenant,
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
            return WidgetPolicyOut.from_orm(
                get_governing_widget_policy(
                    tenant=acting.tenant, org=acting.org, actor=acting.actor()
                )
            )

    @server.tool(
        name="create_widget_policy",
        description=contract_of(create_widget_policy_route),
    )
    def create_widget_policy_tool(ctx: Context[Any], name: str, body: str = "") -> WidgetPolicyOut:
        with tool_call(ctx) as acting:
            return WidgetPolicyOut.from_orm(
                create_widget_policy(
                    tenant=acting_tenant(acting),
                    actor=acting.actor(),
                    name=name,
                    body=body,
                )
            )

    @server.tool(
        name="list_widget_entries",
        description=contract_of(list_widget_entries_route),
    )
    def list_widget_entries_tool(
        ctx: Context[Any],
        widget_id: UUID | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> WidgetEntryPage:
        with tool_call(ctx) as acting:
            entries: QuerySet[WidgetEntry] = list_widget_entries(
                tenant=acting.tenant, org=acting.org, widget_id=widget_id, actor=acting.actor()
            )
            page = cursor_page(
                entries,
                tenant=acting.tenant,
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

    @server.tool(
        name="record_widget_entry",
        description=contract_of(record_widget_entry_route),
    )
    def record_widget_entry_tool(
        ctx: Context[Any],
        widget_id: UUID,
        kind: str = "note",
        note: str = "",
        organization_slug: str | None = None,
    ) -> WidgetEntryOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org, actor=actor)
            # House rule 26, at the site that hands the foreign-key target over.
            if not may_be_named(actor, widget):
                raise NotFound()
            return WidgetEntryOut.from_orm(
                record_widget_entry(
                    tenant=tenant,
                    actor=actor,
                    widget=widget,
                    kind=kind,
                    note=note,
                    organization_slug=organization_slug,
                )
            )

    @server.tool(
        name="archive_widget_policy",
        description=contract_of(archive_widget_policy_route),
    )
    def archive_widget_policy_tool(ctx: Context[Any], policy_id: UUID) -> WidgetPolicyOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            policy = get_widget_policy(
                tenant=tenant, policy_id=policy_id, org=acting.org, actor=actor
            )
            if not may_be_named(actor, policy):
                raise NotFound()
            return WidgetPolicyOut.from_orm(
                archive_widget_policy(tenant=tenant, actor=actor, policy=policy)
            )

    @server.tool(
        name="restore_widget_policy",
        description=contract_of(restore_widget_policy_route),
    )
    def restore_widget_policy_tool(ctx: Context[Any], policy_id: UUID) -> WidgetPolicyOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            policy = get_widget_policy(
                tenant=tenant, policy_id=policy_id, org=acting.org, actor=actor
            )
            if not may_be_named(actor, policy):
                raise NotFound()
            return WidgetPolicyOut.from_orm(
                restore_widget_policy(tenant=tenant, actor=actor, policy=policy)
            )

    # golden: archive version move bulk history duplicate attach merge import begin
    @server.tool(
        name="archive_widget",
        description=contract_of(archive_widget_route),
    )
    def archive_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org, actor=actor)
            if not may_be_named(actor, widget):
                raise NotFound()
            # The same service the HTTP route calls: a repeat press answers the
            # archived widget unchanged, a member is refused with the key's own
            # sentence, and a live child holding it is `archive_blocked`.
            return WidgetOut.from_orm(
                with_allowed_acts(
                    [archive_widget(tenant=tenant, actor=actor, widget=widget)], actor
                )[0]
            )

    @server.tool(
        name="restore_widget",
        description=contract_of(restore_widget_route),
    )
    def restore_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org, actor=actor)
            if not may_be_named(actor, widget):
                raise NotFound()
            return WidgetOut.from_orm(
                with_allowed_acts(
                    [restore_widget(tenant=tenant, actor=actor, widget=widget)], actor
                )[0]
            )


# golden: archive version move bulk history duplicate attach merge import end
