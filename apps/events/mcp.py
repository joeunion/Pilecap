"""The machine door onto the event spine — the same eleven capabilities `api.py` has.

**Door parity is the rule this file exists to satisfy** (house rule 17): every
capability the HTTP door offers a person, this offers a machine, over the *same*
selectors, the *same* services and the *same* schemas. A tool that could do
something no route can, or that answered with a different shape for the same
row, is a finding — and `tests/test_mcp.py` diffs the two registries out of
`introspect` so that it is a failing one.

**And it says what the REST door says, out of one docstring** (ADR api-1, house
rule 41). Every `description=` below is `contract_of(<the REST route>)` — the
contract half of the very function the OpenAPI document describes — so the two
doors cannot come to describe one capability differently. A description typed
here would be the first place they drift, and prose drifts long before behaviour
does.

**The signing key is answered once here too, and by construction rather than by
memory.** `register_endpoint` and `issue_endpoint_secret` return
`WebhookEndpointSecretOut` through the same `with_secret` the HTTP door uses,
imported rather than rewritten; every other tool returns `WebhookEndpointOut`,
which has no field for a key. An agent that has an endpoint's id can no more
read its key back than a browser can.

What a tool is allowed to be is thin:

* it takes **who is calling** from the principal the token middleware left on
  the ASGI scope — never from an argument, so no caller can name a tenant it
  does not hold a token for;
* it **calls services and selectors**, never `.objects`, never `.save()`;
* it **maps no refusals of its own**: `tool_call` turns a domain exception into a
  `ToolError` rendered from `wire_refusal`'s body, the way `config/api.py` turns
  one into a status code and the same body once. That is what makes "the refusal
  is byte-identical through both doors" true by construction.

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
from apps.core.mcp import acting_tenant, tool_call
from apps.events.api import (
    DELIVERY_ORDERING,
    ENDPOINT_ORDERING,
    ENDPOINT_SEARCH_FIELDS,
    create_endpoint_route,
    event_catalogue,
    issue_endpoint_secret_route,
    list_dead_letters_route,
    list_deliveries_route,
    list_endpoints_route,
    list_event_types_route,
    pause_endpoint_route,
    replay_dead_letter_route,
    resume_endpoint_route,
    retrieve_endpoint,
    update_endpoint_route,
    with_secret,
)
from apps.events.models import Delivery, WebhookEndpoint
from apps.events.schemas import (
    DeliveryFilter,
    DeliveryOut,
    DeliveryPage,
    EventTypePage,
    WebhookEndpointFilter,
    WebhookEndpointOut,
    WebhookEndpointPage,
    WebhookEndpointSecretOut,
)
from apps.events.selectors import (
    dead_lettered,
    get_delivery,
    get_endpoint,
    list_deliveries,
    list_endpoints,
)
from apps.events.services import (
    deactivate_endpoint,
    enqueue_replay,
    issue_endpoint_secret,
    register_endpoint,
    resume_endpoint,
    update_endpoint,
)


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(
        name="list_endpoints",
        description=contract_of(list_endpoints_route),
    )
    def list_endpoints_tool(
        ctx: Context[Any],
        is_active: bool | None = None,
        q: str | None = None,
        ordering: str = "-created_at",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> WebhookEndpointPage:
        with tool_call(ctx) as acting:
            endpoints: QuerySet[WebhookEndpoint] = WebhookEndpointFilter(
                is_active=is_active
            ).filter(list_endpoints(tenant=acting.tenant, active_only=False, actor=acting.actor()))
            endpoints = searched(endpoints, q, fields=ENDPOINT_SEARCH_FIELDS)
            endpoints = ordered_by(
                endpoints, ordering, allowed=ENDPOINT_ORDERING, default="-created_at"
            )
            page = cursor_page(
                endpoints,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return WebhookEndpointPage(
                items=[WebhookEndpointOut.from_orm(endpoint) for endpoint in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="get_endpoint",
        description=contract_of(retrieve_endpoint),
    )
    def get_endpoint_tool(ctx: Context[Any], endpoint_id: UUID) -> WebhookEndpointOut:
        with tool_call(ctx) as acting:
            # An endpoint in another tenant is `not_found`, exactly as it is over
            # HTTP: a refusal that distinguished the two would tell the caller
            # the row exists, which is the fact the tenancy was hiding.
            return WebhookEndpointOut.from_orm(
                get_endpoint(tenant=acting.tenant, endpoint_id=endpoint_id, actor=acting.actor())
            )

    @server.tool(
        name="create_endpoint",
        description=contract_of(create_endpoint_route),
    )
    def create_endpoint_tool(
        ctx: Context[Any],
        url: str,
        event_names: list[str] | None = None,
        description: str = "",
    ) -> WebhookEndpointSecretOut:
        with tool_call(ctx) as acting:
            # `with_secret` is the HTTP door's own function, imported rather than
            # reimplemented: "the key is shown once" written twice is a promise
            # one of the two doors will stop keeping.
            return with_secret(
                register_endpoint(
                    tenant=acting_tenant(acting),
                    actor=acting.actor(),
                    url=url,
                    event_names=event_names,
                    description=description,
                )
            )

    @server.tool(
        name="update_endpoint",
        description=contract_of(update_endpoint_route),
    )
    def update_endpoint_tool(
        ctx: Context[Any],
        endpoint_id: UUID,
        url: str | None = None,
        event_names: list[str] | None = None,
        description: str | None = None,
    ) -> WebhookEndpointOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            endpoint = get_endpoint(tenant=tenant, endpoint_id=endpoint_id, actor=acting.actor())
            return WebhookEndpointOut.from_orm(
                update_endpoint(
                    tenant=tenant,
                    actor=acting.actor(),
                    endpoint=endpoint,
                    url=url,
                    event_names=event_names,
                    description=description,
                )
            )

    @server.tool(
        name="issue_endpoint_secret",
        description=contract_of(issue_endpoint_secret_route),
    )
    def issue_endpoint_secret_tool(
        ctx: Context[Any], endpoint_id: UUID
    ) -> WebhookEndpointSecretOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            endpoint = get_endpoint(tenant=tenant, endpoint_id=endpoint_id, actor=acting.actor())
            return with_secret(
                issue_endpoint_secret(tenant=tenant, actor=acting.actor(), endpoint=endpoint)
            )

    @server.tool(
        name="pause_endpoint",
        description=contract_of(pause_endpoint_route),
    )
    def pause_endpoint_tool(ctx: Context[Any], endpoint_id: UUID) -> WebhookEndpointOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            endpoint = get_endpoint(tenant=tenant, endpoint_id=endpoint_id, actor=acting.actor())
            return WebhookEndpointOut.from_orm(
                deactivate_endpoint(tenant=tenant, actor=acting.actor(), endpoint=endpoint)
            )

    @server.tool(
        name="resume_endpoint",
        description=contract_of(resume_endpoint_route),
    )
    def resume_endpoint_tool(ctx: Context[Any], endpoint_id: UUID) -> WebhookEndpointOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            endpoint = get_endpoint(tenant=tenant, endpoint_id=endpoint_id, actor=acting.actor())
            return WebhookEndpointOut.from_orm(
                resume_endpoint(tenant=tenant, actor=acting.actor(), endpoint=endpoint)
            )

    @server.tool(
        name="list_event_types",
        description=contract_of(list_event_types_route),
    )
    def list_event_types_tool(
        ctx: Context[Any],
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> EventTypePage:
        with tool_call(ctx) as acting:
            # The HTTP route's own function, imported rather than reimplemented:
            # a catalogue derived twice is two vocabularies waiting to differ,
            # which is the whole reason it is derived rather than listed.
            catalogue = event_catalogue()
            page = cursor_page(
                catalogue,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
                ordering=("name",),
            )
            return EventTypePage(
                items=list(page.items),
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="list_deliveries",
        description=contract_of(list_deliveries_route),
    )
    def list_deliveries_tool(
        ctx: Context[Any],
        status: str | None = None,
        endpoint_id: UUID | None = None,
        ordering: str = "-created_at",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> DeliveryPage:
        with tool_call(ctx) as acting:
            deliveries: QuerySet[Delivery] = DeliveryFilter(
                status=status, endpoint_id=endpoint_id
            ).filter(list_deliveries(tenant=acting.tenant, actor=acting.actor()))
            deliveries = ordered_by(
                deliveries, ordering, allowed=DELIVERY_ORDERING, default="-created_at"
            )
            page = cursor_page(
                deliveries,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return DeliveryPage(
                items=[DeliveryOut.from_orm(delivery) for delivery in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="list_dead_letters",
        description=contract_of(list_dead_letters_route),
    )
    def list_dead_letters_tool(
        ctx: Context[Any],
        ordering: str = "-dead_lettered_at",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> DeliveryPage:
        with tool_call(ctx) as acting:
            deliveries: QuerySet[Delivery] = ordered_by(
                dead_lettered(tenant=acting.tenant, actor=acting.actor()),
                ordering,
                allowed=DELIVERY_ORDERING,
                default="-dead_lettered_at",
            )
            page = cursor_page(
                deliveries,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return DeliveryPage(
                items=[DeliveryOut.from_orm(delivery) for delivery in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="replay_dead_letter",
        description=contract_of(replay_dead_letter_route),
    )
    def replay_dead_letter_tool(ctx: Context[Any], delivery_id: UUID) -> DeliveryOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            delivery = get_delivery(tenant=tenant, delivery_id=delivery_id, actor=acting.actor())
            # The same service the HTTP route calls, so an agent gets the same
            # refusal for the same reason — `invalid` on a delivery that was
            # never dead-lettered, `not_found` on one in another tenant.
            return DeliveryOut.from_orm(
                enqueue_replay(tenant=tenant, actor=acting.actor(), delivery=delivery)
            )
