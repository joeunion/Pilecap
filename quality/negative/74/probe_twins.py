"""The probe app's machine door, planted only when no other rule's form made one.

`mode: default` — when the whole corpus runs, rule 17's negative has already
created the probe's `mcp.py` (the same loop); when `--rule 74` runs alone, this
mirrors every route the router ends up with, so the road's twins exist and rule
17 stays silent about a negative that is not its own.
"""

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api.docs import contract_of
from apps.core.checks import _VERB_TOOLS
from apps.zzz_canary.api import router


def _tool_name(url_name: str) -> str:
    noun, _, verb = url_name.rpartition("-")
    forms = _VERB_TOOLS.get(verb)
    return forms[0].format(noun=noun) if forms else f"{verb}_{noun}"


def register(server: MCPServer[Any]) -> None:
    for path_view in router.path_operations.values():
        for operation in path_view.operations:
            name = _tool_name(str(operation.url_name or ""))

            def twin(ctx: Context[Any], row_id: str = "") -> dict:
                return {"id": row_id}

            server.tool(name=name, description=contract_of(operation.view_func))(twin)
