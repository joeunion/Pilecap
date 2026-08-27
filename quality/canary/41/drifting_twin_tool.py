"""Planted: the probe app's machine door, describing one capability its own way."""

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context


def register(server: MCPServer[Any]) -> None:
    @server.tool(
        name="get_doohickey",
        description="Fetch a doohickey. Handy for agents.",
    )
    def get_doohickey_tool(ctx: Context[Any], doohickey_id: str) -> dict:
        return {"id": doohickey_id}
