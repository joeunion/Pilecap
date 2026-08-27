"""The machine door onto search — the same two capabilities the REST door has.

Door parity (house rule 17): the capability `api.py` offers a person, this
offers a machine, over the *same* selector and the *same* schemas. And it
**says** the same thing out of one docstring (house rule 41): `description=` is
`contract_of(search_route)`, so the two doors cannot come to describe one
capability differently — prose drifts long before behaviour does.

Search is the capability an assistant reaches for most and the one where a
scoping mistake is least visible, so it is worth saying what this door does
*not* do: it takes no organization argument, no tenant argument and no engine
argument. Who is calling comes from the principal the token middleware left on
the ASGI scope, the acting hat rides on it, and everything else is the same
chokepoint the HTTP door calls. A tool that could name an organization would be
a tool that could read a branch its holder has no membership over.

The body is a plain `def` rather than `async def`: the transport runs a
synchronous tool on a worker thread, which is where the synchronous ORM belongs,
and `tool_call` closes the connection that thread borrowed.
"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api.docs import contract_of
from apps.core.api.pagination import cursor_page
from apps.core.mcp import acting_tenant, tool_call
from apps.search.api import kind_catalogue, list_search_kinds_route, search_route
from apps.search.schemas import SearchKindPage, SearchPage
from apps.search.selectors import search


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
            # No `except` here either, and for the same reason its REST twin has
            # none. An unreachable index is answered from Postgres now, and
            # the narrow refusal that survives is a registered `DomainError` —
            # which `tool_call` already renders through the one composer, code
            # first, with the same remedies the screen would show. The hand-made
            # `ToolError` that used to live here was the machine door's private
            # copy of a sentence the HTTP door was also keeping privately; two
            # copies of one refusal is the drift ADR core-5 closes.
            return search(
                tenant=acting.tenant,
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
        """The vocabulary, for the door that needs it most.

        An assistant is the caller most likely to send `?kinds=` a name it made
        up — it has a model of the product and no way to check it — and, previously,
        the product answered a made-up name with an empty page. So this
        twin is not a completeness exercise: it is the read that turns a guess
        into a lookup.

        The route's own function is imported rather than reimplemented, for the
        reason `list_event_types` gives one app over: a catalogue derived twice
        is two vocabularies waiting to differ.
        """
        with tool_call(ctx) as acting:
            # The REST twin refuses a request that resolved no account, so this
            # one does too — a door pair that agreed about the page and
            # disagreed about the refusal is exactly what rule 46's test is for.
            tenant = acting_tenant(acting)
            page = cursor_page(
                kind_catalogue(),
                tenant=tenant,
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
