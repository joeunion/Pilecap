"""Planted: `apps/connections` grows a machine door, and nobody proves the pair.

`connections` has a REST door and no `mcp.py` today, so it owes nothing — it is
this rule's one-door app. Adding the second door is the moment the debt is
taken on: two renderings of one capability, and rule 17 comparing the two
REGISTRIES cannot see them disagree about the wire any more than it could
see one consumer answering two credentials two ways .

`connections` has no entry in the recorded backlog, so its first pair is a
violation from birth. That is the whole point of ratcheting per app rather than
per rule: the five apps that predate the rule are a standing debt, and the sixth
door pair to arrive is not.
"""

from typing import Any


def register(server: Any) -> None:
    @server.tool(name="list_connections", description="List this tenant's connections.")
    def list_connections(ctx: Any) -> list[str]:
        return []
