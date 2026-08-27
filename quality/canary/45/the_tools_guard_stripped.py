"""Planted: `apps/core/mcp.py` with its tools and without its ceiling gate.

THE REGRESSION FORM, and the reason it is a whole-file plant rather than an
append. The only thing that makes `tools/call` a GUARDED surface is that
something under `apps/` calls `install_ceiling_gate`; a plant can create or
append but never delete, so the way to show the rule noticing the guard gone is
to stand in for the module that installs it. This module registers a tool
exactly as the real one does and never installs the gate — which is what the day
before looked like, and what a refactor that moves `register()` around and
drops one line would look like again.

The other fifty-odd tools the discovered apps contribute are still there, so the
finding is not about this file: it is about a dispatch surface with seventy
registrations behind it and no wall.
"""

from typing import Any


def register(server: Any) -> None:
    @server.tool(
        name="ping",
        description="Confirm the machine door is open and report the acting tenant.",
    )
    def ping(ctx: Any) -> dict[str, Any]:
        return {"ok": True}
