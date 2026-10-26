# A tool re-raising a refusal it was handed: no sentence of its own is composed.
from mcp.server.mcpserver.exceptions import ToolError


def neg_tool_passes_composed(composed: str) -> None:
    """Raise what the composer already wrote."""
    raise ToolError(composed)
