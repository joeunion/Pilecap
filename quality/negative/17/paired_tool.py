"""Negative: the probe app's machine door, matching its REST capabilities.

The whole negative corpus is planted into ONE probe app at once, so this file is
that app's ONE `mcp.py` — it has to mirror every route the app ends up with,
whichever rule's fixture declared it. Written as a loop over the router rather
than as a hand list for exactly that reason: a rule that adds a probe route does
not have to come and edit another rule's fixture, and this fixture cannot go
stale behind one.

Each tool takes its description from the route's own docstring
(`contract_of`), which is the shape house rule 41 requires of the real doors —
so this file is a negative for rule 41 as much as for rule 17.
"""

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api.docs import contract_of
from apps.core.verbs import derive_tool_name
from apps.zzz_canary.api import router


def register(server: MCPServer[Any]) -> None:
    for path_view in router.path_operations.values():
        for operation in path_view.operations:
            # The name house rule 17 looks for, from the one derivation.
            name = derive_tool_name(str(operation.url_name or ""))

            def twin(ctx: Context[Any], row_id: str = "") -> dict:
                return {"id": row_id}

            server.tool(name=name, description=contract_of(operation.view_func))(twin)
