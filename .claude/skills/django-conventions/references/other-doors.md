# The other doors — MCP, sockets, webhooks, connections

The long form of `django-conventions` §9.

## The MCP tool

```python
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from apps.core.mcp import principal                 # Principal(user: AbstractBaseUser, tenant: Tenant | None)

def register(server: MCPServer[Any]) -> None:       # config.mcp discovers and calls this
    @server.tool(name="orders.create", description="Create an order for the caller's tenant")
    def create_order(ctx: Context[Any], body: OrderIn) -> OrderOut:
        acting = principal(ctx)                     # from the scope the middleware filled; never the payload
        if acting.tenant is None:
            raise ToolError("No tenant for this call.")
        customer = get_object_or_404(Customer.objects.for_tenant(acting.tenant), pk=body.customer_id)
        return OrderOut.from_orm(services.create_order(tenant=acting.tenant, actor=acting.actor(),
                                                       customer=customer, lines=body.lines))
```

**Sockets** — `apps/realtime` ships the one consumer: authenticate, **join the
tenant's group only**, receive pushes from the event bridge. A product app that
needs its own channel exposes `websocket_urlpatterns` in `apps/<x>/consumers.py`
with the same shape: no unauthenticated connect (`close(code=4401)`), join by
`scope["tenant"]`, never a user-supplied group name. **Push via events**; never
query the database per message — a consumer that needs a row uses
`database_sync_to_async` once, at connect.

**Webhooks inbound** — `verify → store → hand to a workflow → 202`. The
receiver (the `connections` helper, or a route on the allow-list) checks the
signature with `hmac.compare_digest`, stores the raw body, starts a workflow,
returns. **Never processed inline**: a slow or failing handler loses the event.
**Outbound** — via `emit()` (§8); never `httpx.post` from a service or a route.

**Connections** — `apps.connections` holds the per-tenant `Connection`
(provider, **encrypted credentials**, status) and the **`httpx` client factory**
(timeouts, retries, idempotency keys). External calls happen **inside
activities**, through that factory, the connection read through `for_tenant`.
Never `requests`; never a bare `httpx.Client()`; never a credential in a log
line or an exception message.
