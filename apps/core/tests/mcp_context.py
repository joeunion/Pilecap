"""The MCP door's context, faked for a tool called in-process — one copy.

A tool test that does not need the transport calls the tool's function with the
`Context` the door would have built: a request whose ASGI scope carries the
`Principal` `config.mcp`'s middleware leaves there. Fourteen modules carried
their own `_FakeRequest`/`_FakeRequestContext`/`context_for` trio, in two
disagreeing shapes — one defaulted the hat to the tenant's root, one required
it. This is the stricter: **the hat is REQUIRED**, because a principal with no
named hat is a context no door builds, and a default that quietly put every
call at the root is how a test passes for a branch it never asked about.

* `context_for(user, tenant, org)` — the context a tool sees.
* `tool(name, register=...)` — the function an app's `register(server)` binds
  to `name`, read off a server holding that app's tools and nothing else.

`tool` reads the SDK's private `_tool_manager._tools`: a test module, outside
house rule 44's walk (its own `does_not_cover` excludes test modules), and a
READ, which degrades rather than silently binding nothing. The per-app copies
retire in their own apps' rungs.

DOES NOT COVER — declared: the transport (`apps.core.tests.wire` drives the
real one), the surface a principal is resolved under (pass it on the
`Principal` yourself when a test is about one).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.accounts.models import User
from apps.core.mcp import SCOPE_KEY, Principal
from apps.core.models import Organization, Tenant
from apps.core.roads import road


@dataclass
class FakeRequest:
    """Just enough of a Starlette request: the ASGI scope, and nothing else."""

    scope: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeRequestContext:
    """Just enough of the SDK's request context: the request."""

    request: FakeRequest


@road(
    "tool_context",
    example="apps/core/tests/test_reads_ask.py::test_a_withheld_read_is_forbidden_on_the_wire_and_the_twin_says_the_same",
)
def context_for(user: User, tenant: Tenant | None, org: Organization | None) -> Context[Any]:
    """The context a tool sees, with the principal the middleware would have left. Hat required."""
    scope = {SCOPE_KEY: Principal(user=user, tenant=tenant, org=org)}
    return Context(request_context=cast(Any, FakeRequestContext(request=FakeRequest(scope=scope))))


def tool(name: str, *, register: Callable[[MCPServer[Any]], None]) -> Callable[..., Any]:
    """The function `register(server)` binds to the tool `name`, on a server of its own."""
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    found: Callable[..., Any] = cast(Any, server._tool_manager._tools[name]).fn  # noqa: SLF001
    return found
