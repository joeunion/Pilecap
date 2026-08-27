"""The machine door onto usage — the capabilities the REST door has, and no more.

Two of them now, and they are the two the human door has: the report, and the
vocabulary it is read against (a machine that can be refused for naming
an undeclared meter and cannot list the declared ones is a machine that has to
guess, which is the failure this pair closes).

Door parity (house rule 17): the read this offers a machine is the read `api.py`
offers a person, over the *same* selector, the *same* window builder, the *same*
catalogue function, the *same* paginator and the *same* schemas. And it **says**
the same thing out of one docstring (house rule 41): every `description=` below
is `contract_of(<the REST route>)`, so the two doors cannot come to describe one
capability differently — prose drifts long before behaviour does.

**The write door is absent here for the same reason it is absent there**, and it
is worth saying at the machine door in particular: an agent is exactly the
caller for whom "record some usage" would look like an ordinary tool, and it is
the caller who must never have it. Metering is the platform's witnessed
side-effect of work that already happened; a tool that recorded it would let a
client mint or dispute its own bill (ADR usage-1, § Doors). No parity gap
follows — rule 17 binds REST capabilities to MCP, and there is no write route on
either side to be missing from this one.

The body is a plain `def` rather than `async def`: the transport runs a
synchronous tool on a worker thread, which is where the synchronous ORM belongs,
and `tool_call` closes the connection that thread borrowed. It maps no refusals
of its own — `tool_call` turns a domain exception into a `ToolError` once, the
way `config/api.py` turns one into a status code once.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api.docs import contract_of
from apps.core.mcp import acting_tenant, tool_call
from apps.core.middleware import ORG_HEADER
from apps.usage.api import (
    list_meters_route,
    meter_page,
    report,
    require_resolved_hat,
    usage_report_route,
)
from apps.usage.schemas import MeterPage, UsageReportOut
from apps.usage.types import PeriodKind


def _requested_hat(ctx: Context[Any]) -> str | None:
    """The `X-Org` this call SENT, read at the machine door by its declared name.

    `config.mcp` resolves the header into `Principal.org` with the same
    `core.middleware.resolve_org` the HTTP door uses, and — exactly as there — a
    slug that resolves to nothing is indistinguishable from no slug at all by
    the time a tool body runs. `require_resolved_hat` needs the question the
    resolved value cannot answer, so the raw header is read here, off the ASGI
    scope the transport is already carrying, by the constant that declares its
    name (rule 40). Nothing is re-spelled and nothing is parsed: the one header,
    or `None`.

    **Why the machine door gets this and not only `_acting`.** The
    zero-bill hazard is worse here, not better. A fat-fingered hat reaching an
    agent as `{"meters": {}}` is a total an assistant will repeat to a customer
    in a sentence, and a REST-only refusal would put the two doors into open
    disagreement about one header — which is precisely what this app's rule-46
    door-pair test exists to catch.
    """
    request = ctx.request_context.request
    scope: dict[str, Any] = getattr(request, "scope", None) or {}
    headers: Iterable[tuple[bytes, bytes]] = scope.get("headers") or ()
    wanted = ORG_HEADER.lower().encode()
    for name, value in headers:
        if name.lower() == wanted:
            # latin-1, which is what the ASGI spec says a raw header byte string
            # is: a slug that is not ASCII will not resolve anyway, and guessing
            # at UTF-8 here would raise where the answer is simply "no".
            return value.decode("latin-1")
    return None


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(
        name="get_usage",
        description=contract_of(usage_report_route),
    )
    def get_usage_tool(
        ctx: Context[Any],
        period: PeriodKind = PeriodKind.MONTH,
        on: date | None = None,
        meters: list[str] | None = None,
    ) -> UsageReportOut:
        with tool_call(ctx) as acting:
            require_resolved_hat(requested_slug=_requested_hat(ctx), org=acting.org)
            # `api.report` and not a second assembly of the same body: the
            # window, the inclusive end date and the per-meter mapping are built
            # in one place, so the only thing this door can get wrong is the
            # transport — which is what the parity test drives.
            return report(
                tenant=acting_tenant(acting),
                actor=acting.actor(),
                period=period,
                on=on,
                meters=meters,
            )

    @server.tool(
        name="list_meters",
        description=contract_of(list_meters_route),
    )
    def list_meters_tool(
        ctx: Context[Any],
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> MeterPage:
        with tool_call(ctx) as acting:
            # The HTTP route's own page builder, imported rather than
            # reimplemented: a vocabulary derived twice is two vocabularies
            # waiting to differ, and an envelope assembled twice is two
            # envelopes. There is nothing left for this door to get wrong except
            # the transport, which is what the parity test drives.
            return meter_page(
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
