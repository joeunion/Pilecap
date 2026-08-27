"""A new app contributing a tool — the ordinary act this rule must never refuse.

`tools/call` is ceilinged, so registering on it is exactly what an app is
supposed to do and the rule has nothing to say. If this fired, the rule would be
refusing registration rather than refusing an unwalled surface, and the first
person to meet it would work around it rather than read it.
"""

from typing import Any


def register(server: Any) -> None:
    @server.tool(name="probe_widgets", description="List this tenant's widgets.")
    def probe_widgets(ctx: Any) -> list[str]:
        return []
