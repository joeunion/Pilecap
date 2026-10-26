# Planted: an MCP tool composing its own refusal sentence, code and all.
from mcp.server.mcpserver.exceptions import ToolError


def canary_tool_literal_refusal() -> None:
    """Refuse with a sentence of the tool's own."""
    raise ToolError("zzz_nope: this tool refuses in words nobody registered.")
