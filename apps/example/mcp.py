"""The machine door onto widgets — the same six capabilities the REST door has.

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
from apps.example.api import (
    ORDERING,
    SEARCH_FIELDS,
    approve_widget_route,
    create_widget_policy_route,
    create_widget_route,
    delete_widget_route,
    get_governing_widget_policy_route,
    list_widget_entries_route,
    list_widget_policies_route,
    list_widgets_route,
    record_widget_entry_route,
    resolve_named_policy,
    retrieve_widget,
    update_widget_route,
    widget_stats,
    widget_stats_route,
)
from apps.example.models import Widget, WidgetEntry, WidgetPolicy
from apps.example.schemas import (
    WidgetEntryOut,
    WidgetEntryPage,
    WidgetFilter,
    WidgetOut,
    WidgetPage,
    WidgetPolicyOut,
    WidgetPolicyPage,
    WidgetStatsOut,
)
from apps.example.selectors import (
    get_governing_widget_policy,
    get_widget,
    list_widget_entries,
    list_widget_policies,
    list_widgets,
)
from apps.example.services import (
    approve_widget,
    create_widget,
    create_widget_policy,
    delete_widget,
    record_widget_entry,
    update_widget,
)


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
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> WidgetPage:
        with tool_call(ctx) as acting:
            # Scoped first and only narrowed after — and the type widens from
            # `ScopedQuerySet` to `QuerySet` for the same reason it does in
            # `api.py`: filtering returns the plain one, and narrowing a queryset
            # cannot widen its tenant.
            widgets: QuerySet[Widget] = WidgetFilter(name=name).filter(
                list_widgets(tenant=acting.tenant, org=acting.org)
            )
            widgets = searched(widgets, q, fields=SEARCH_FIELDS)
            widgets = ordered_by(widgets, ordering, allowed=ORDERING, default="-created_at")
            page = cursor_page(
                widgets,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return WidgetPage(
                items=[WidgetOut.from_orm(widget) for widget in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="get_widget",
        description=contract_of(retrieve_widget),
    )
    def get_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            # A widget in another tenant is `not_found`, exactly as it is over
            # HTTP: a refusal that distinguished the two would tell the caller
            # the row exists, which is the fact the tenancy was hiding.
            return WidgetOut.from_orm(
                get_widget(tenant=acting.tenant, widget_id=widget_id, org=acting.org)
            )

    @server.tool(
        name="create_widget",
        description=contract_of(create_widget_route),
    )
    def create_widget_tool(
        ctx: Context[Any], name: str, notes: str = "", policy_id: UUID | None = None
    ) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            policy = resolve_named_policy(tenant=tenant, actor=actor, policy_id=policy_id)
            # House rule 26, at the site that hands the foreign-key target over —
            # the same two lines the HTTP door writes, for the same reason.
            if policy is not None and not may_be_named(actor, policy):
                raise NotFound()
            return WidgetOut.from_orm(
                create_widget(
                    tenant=tenant,
                    actor=actor,
                    name=name,
                    notes=notes,
                    policy=policy,
                )
            )

    @server.tool(
        name="update_widget",
        description=contract_of(update_widget_route),
    )
    def update_widget_tool(
        ctx: Context[Any],
        widget_id: UUID,
        name: str | None = None,
        notes: str | None = None,
        policy_id: UUID | None = None,
    ) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org)
            policy = resolve_named_policy(tenant=tenant, actor=actor, policy_id=policy_id)
            if policy is not None and not may_be_named(actor, policy):
                raise NotFound()
            return WidgetOut.from_orm(
                update_widget(
                    tenant=tenant,
                    actor=actor,
                    widget=widget,
                    name=name,
                    notes=notes,
                    policy=policy,
                )
            )

    @server.tool(
        name="approve_widget",
        description=contract_of(approve_widget_route),
    )
    def approve_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org)
            # House rule 26: approval writes a ledger line now, so its
            # foreign-key target is checked here, as it is on the HTTP door.
            if not may_be_named(acting.actor(), widget):
                raise NotFound()
            # The same service the HTTP route calls, so an agent gets the same
            # refusal for the same reason — `conflict` on a run that has already
            # ended, `not_found` on one that was never there.
            return WidgetOut.from_orm(
                approve_widget(tenant=tenant, actor=acting.actor(), widget=widget)
            )

    @server.tool(
        name="delete_widget",
        description=contract_of(delete_widget_route),
    )
    def delete_widget_tool(ctx: Context[Any], widget_id: UUID) -> WidgetOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org)
            if not may_be_named(acting.actor(), widget):
                raise NotFound()
            # The deleted row comes back rather than a bare acknowledgement: an
            # agent that deleted the wrong widget can say which one it was. The
            # HTTP door answers 204 because HTTP has a way to say "gone"; a tool
            # result does not, so it says what went.
            return WidgetOut.from_orm(
                delete_widget(tenant=tenant, actor=acting.actor(), widget=widget)
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
            return widget_stats(tenant=acting.tenant, org=acting.org)

    @server.tool(
        name="list_widget_policies",
        description=contract_of(list_widget_policies_route),
    )
    def list_widget_policies_tool(
        ctx: Context[Any],
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> WidgetPolicyPage:
        with tool_call(ctx) as acting:
            policies: QuerySet[WidgetPolicy] = list_widget_policies(
                tenant=acting.tenant, org=acting.org
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
                get_governing_widget_policy(tenant=acting.tenant, org=acting.org)
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
                tenant=acting.tenant, org=acting.org, widget_id=widget_id
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
            widget = get_widget(tenant=tenant, widget_id=widget_id, org=acting.org)
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
