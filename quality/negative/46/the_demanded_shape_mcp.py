"""The machine half of a two-door app that DOES prove its pair. Silent.

Planted with `api.py`, `apps.py` and a test carrying the marker, because the
subject is a RELATION between three files and a fixture that planted one of them
would prove nothing. This is the shape the rule demands, and a rule that fired
here would be a rule nobody could satisfy.
"""

from typing import Any


def register(server: Any) -> None:
    @server.tool(name="probe_widgets", description="List this tenant's widgets.")
    def probe_widgets(ctx: Any) -> list[str]:
        return []
